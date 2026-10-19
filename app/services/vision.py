"""视觉 AI 接入：调用 OpenAI 兼容的多模态模型，从血检报告照片提取指标。

默认使用 Moonshot Kimi（国内可直接访问），通过 .env 里的 BASE_URL / MODEL
即可切换为通义千问、OpenAI 等其他 provider，业务代码无需改动。

为什么把「识别」和「单位换算」分开：
- 模型只负责原样读取报告上的数值与单位（它更擅长看图，不擅长做医学单位换算）；
- 单位换算在后端 normalize 模块完成，逻辑集中、可测试、可控；
- 模型可能看错单位，后端统一换算 + 前端人工核对，双重保险。
"""

import asyncio
import base64
import io
import json
import logging
import re
from typing import Optional

import openai

try:
    from PIL import Image, ImageOps

    try:
        from pillow_heif import register_heif_opener

        register_heif_opener()
    except ImportError:  # pragma: no cover - 未安装 pillow-heif 时不支持 HEIC
        pass

    _HAS_PIL = True
except ImportError:  # pragma: no cover - 未安装 Pillow 时降级为直接发送原图
    Image = None
    ImageOps = None
    _HAS_PIL = False

from app.config import Settings
from app.schemas import MARKER_FIELDS

logger = logging.getLogger(__name__)


class VisionServiceError(Exception):
    """视觉识别服务异常，message 为可直接展示给用户的友好中文提示。"""


_MAX_IMAGE_EDGE = 2400
_JPEG_QUALITY = 90


def _prepare_image(image_bytes: bytes, original_mime: str) -> tuple[bytes, str]:
    """预处理照片：按 EXIF 转正、透明通道铺白底、限制最长边并统一转 JPEG。

    手机竖拍照片常带 EXIF 旋转标记，直接发送会被模型看成横躺图，导致整张
    无法识别；过大的原图也更容易超时或失败。iPhone 等设备拍照产生的 HEIC
    会先解码再统一转成 JPEG。处理后，视觉模型看到的始终是「摆正、RGB、
    尺寸适中」的图片，可显著提高识别成功率。

    预处理失败时退回原始图片，绝不让预处理阻断主流程。
    """
    if not _HAS_PIL:
        return image_bytes, original_mime
    try:
        img = Image.open(io.BytesIO(image_bytes))
        img = ImageOps.exif_transpose(img)
        if img.mode in ("RGBA", "LA") or (
            img.mode == "P" and "transparency" in img.info
        ):
            rgba = img.convert("RGBA")
            background = Image.new("RGB", rgba.size, (255, 255, 255))
            background.paste(rgba, mask=rgba.getchannel("A"))
            img = background
        else:
            img = img.convert("RGB")

        if max(img.size) > _MAX_IMAGE_EDGE:
            ratio = _MAX_IMAGE_EDGE / max(img.size)
            new_size = (
                max(1, int(round(img.width * ratio))),
                max(1, int(round(img.height * ratio))),
            )
            img = img.resize(new_size, Image.Resampling.LANCZOS)

        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=_JPEG_QUALITY)
        logger.info(
            "图片预处理完成：%s -> JPEG %dx%d", original_mime, img.width, img.height
        )
        return buf.getvalue(), "image/jpeg"
    except Exception as exc:  # noqa: BLE001 - 预处理失败不应阻断识别
        logger.warning("图片预处理失败，使用原始图片：%s", exc)
        return image_bytes, original_mime


# System prompt 是整个识别质量的关键：要求只输出 JSON、禁止编造、
# 保留原始单位、正确处理低于检测限的 "<x" 值。别名对照表用于减少漏识别。
_SYSTEM_PROMPT = (
    "你是医学检验报告数据提取助手。请从血检报告照片中逐行、逐项仔细提取以下 10 项指标，"
    "不要遗漏任何一项。\n\n"
    "指标中英文名与常见缩写对照（据此识别，括号内是参考范围，不要取）：\n"
    "- albumin：白蛋白，常见缩写 ALB、Alb\n"
    "- creatinine：肌酐，常见缩写 CREA、Cr、CRE\n"
    "- glucose：葡萄糖/血糖，常见缩写 GLU、GLUC、BS\n"
    "- crp：C反应蛋白，常见写法 CRP、超敏C反应蛋白、hs-CRP、hsCRP\n"
    "- lymphocyte_pct：淋巴细胞百分比，常见写法 LYMPH%、LYM%、LY%、淋巴细胞%\n"
    "- mcv：平均红细胞体积，常见缩写 MCV\n"
    "- rdw：红细胞分布宽度(RDW-CV)，常见写法 RDW、RDW-CV、RDW-SD（有多个时优先取 RDW-CV）\n"
    "- alp：碱性磷酸酶，常见缩写 ALP、AKP\n"
    "- wbc：白细胞计数，常见写法 WBC、白细胞、LEU\n"
    "- age：实际年龄，通常不在报告上，恒为 null\n\n"
    "读取规则：\n"
    "1. 只取「结果值」，不要取括号里的参考范围；结果值通常在参考范围之前或上方；\n"
    "2. 数值可能是整数或小数，注意小数点；↑↓箭头、H/L 标记只代表异常，不要算进数值；\n"
    "3. 同一指标若出现多个数值，取最像本次结果的第一个结果值；\n"
    '4. 报告写 "<0.x" 或 "<x"（低于检测限）时，value 取该阈值的一半，并把 censored 设为 true；\n'
    "5. 识别不到或无法确认的项，value 输出 null，绝不编造；\n"
    "6. 必须原样返回报告上的数值与单位，单位换算由后端完成，不要自行换算；\n"
    "7. confidence 表示你对该项提取结果的把握（0-1 的小数）；\n"
    "8. 照片可能只包含报告的一部分，仍要输出全部 10 个字段，识别不到的输出 value:null。\n\n"
    "严格按以下 JSON 结构输出，只输出 JSON，不要输出任何解释文字：\n"
    '{"albumin":{"value":数字或null,"unit":"报告原始单位","raw_text":"报告原文片段",'
    '"confidence":0到1,"censored":true或false},"creatinine":{...},...}'
)


class VisionClient:
    """OpenAI 兼容视觉模型的轻量封装。"""

    def __init__(self, settings: Settings):
        self._settings = settings
        # 延迟创建 SDK 客户端：没有密钥时也能正常导入应用，
        # 只有真正发起识别请求时才报「未配置密钥」的友好错误。
        self._client: Optional[openai.AsyncOpenAI] = None

    def _get_client(self) -> openai.AsyncOpenAI:
        if self._client is None:
            if not self._settings.ai_api_key:
                raise VisionServiceError("未配置 AI_API_KEY，无法进行视觉识别。")
            self._client = openai.AsyncOpenAI(
                base_url=self._settings.ai_base_url,
                api_key=self._settings.ai_api_key,
                timeout=self._settings.ai_timeout_seconds,
            )
        return self._client

    async def extract(self, images: list[tuple[bytes, str]]) -> dict:
        """识别多张照片并合并结果（每个字段取置信度最高的一项）。

        为什么逐张识别而不是一次发送多图：
        - 不同 provider 对「一次多图」的支持不一致，逐张调用更通用；
        - 血常规与生化通常在不同页，逐张识别后按置信度合并更稳定。
        """
        tasks = [self._extract_one(data, mime) for data, mime in images]
        outcomes = await asyncio.gather(*tasks, return_exceptions=True)

        successes = [o for o in outcomes if isinstance(o, dict)]
        failures = [o for o in outcomes if isinstance(o, Exception)]
        if not successes:
            for exc in failures:
                logger.warning("照片识别失败：%s", exc)
            first = failures[0] if failures else None
            if isinstance(first, VisionServiceError):
                raise first
            raise VisionServiceError("照片识别失败，请重试或改用手动录入。")
        for exc in failures:
            logger.warning("其中一张照片识别失败，已跳过：%s", exc)
        return self._merge(successes)

    async def _extract_one(self, image_bytes: bytes, mime: str) -> dict:
        """识别单张照片，返回按字段分组的原始提取结果（未做单位换算）。

        返回值形如：{"albumin": {"value": 4.62, "unit": "g/dL", ...}}
        """
        image_bytes, mime = _prepare_image(image_bytes, mime)
        data_url = (
            f"data:{mime};base64,{base64.b64encode(image_bytes).decode('ascii')}"
        )
        client = self._get_client()
        content = await self._chat(
            client,
            [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "请逐项提取这份血检报告照片中的全部 10 项指标。",
                        },
                        {
                            "type": "image_url",
                            "image_url": {"url": data_url},
                        },
                    ],
                },
            ],
        )
        return self._parse(content)

    async def _chat(self, client: openai.AsyncOpenAI, messages: list) -> Optional[str]:
        """调用视觉模型并返回文本内容，带一次降级重试。

        - 第一次强制 JSON 输出，降低解析失败概率；
        - 若模型不支持 response_format（返回 400），自动降级为普通输出再试；
        - 超时 / 连接失败各多试一次。
        """
        for use_json_format in (True, False):
            kwargs = (
                {"response_format": {"type": "json_object"}} if use_json_format else {}
            )
            try:
                response = await client.chat.completions.create(
                    model=self._settings.ai_model,
                    messages=messages,
                    **kwargs,
                )
                return response.choices[0].message.content
            except openai.APITimeoutError as exc:
                logger.warning("视觉识别超时（json_format=%s）：%s", use_json_format, exc)
            except openai.APIConnectionError as exc:
                logger.warning(
                    "视觉识别连接失败（json_format=%s）：%s", use_json_format, exc
                )
            except openai.APIStatusError as exc:
                if use_json_format and exc.status_code == 400:
                    logger.warning("模型不支持 json_object，降级为普通输出后重试")
                    continue
                raise VisionServiceError(
                    f"视觉识别服务返回错误（状态码 {exc.status_code}），请稍后重试。"
                ) from exc
            except openai.APIError as exc:
                raise VisionServiceError("视觉识别服务异常，请稍后重试。") from exc
        raise VisionServiceError("视觉识别失败（多次尝试），请重试或改用手动录入。")

    @staticmethod
    def _merge(results: list[dict]) -> dict:
        """多张照片的识别结果按字段合并，每个字段取置信度最高的一项。"""
        merged: dict = {}
        for field in MARKER_FIELDS:
            candidates = [r[field] for r in results if r.get(field) is not None]
            if not candidates:
                continue
            merged[field] = max(
                candidates,
                key=lambda c: (
                    c.get("confidence") if c.get("confidence") is not None else -1.0
                ),
            )
        return merged

    @staticmethod
    def _parse(content: Optional[str]) -> dict:
        """把模型返回的文本解析成结构化 dict，失败抛友好异常。"""
        text = (content or "").strip()
        # 模型偶尔会在 JSON 外包裹 ```json ... ``` 围栏，防御性剥掉
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise VisionServiceError("视觉识别返回的内容无法解析，请重试或改用手动录入。") from exc
        if not isinstance(data, dict):
            raise VisionServiceError("视觉识别返回的结构不正确，请重试或改用手动录入。")

        result: dict = {}
        for field in MARKER_FIELDS:
            item = data.get(field)
            if not isinstance(item, dict):
                # null / 缺失 / 结构不对都视为「未识别」，交给前端引导手填
                continue
            raw_value = item.get("value")
            if raw_value is None:
                continue
            try:
                value = float(raw_value)
            except (TypeError, ValueError):
                continue
            result[field] = {
                "value": value,
                "unit": item.get("unit") if isinstance(item.get("unit"), str) else None,
                "raw_text": item.get("raw_text"),
                "confidence": _coerce_float(item.get("confidence")),
                "censored": bool(item.get("censored")),
            }
        return result


def _coerce_float(value) -> Optional[float]:
    """把任意值安全地转成 float，失败返回 None。"""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
