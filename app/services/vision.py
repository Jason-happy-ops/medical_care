"""视觉 AI 接入：调用 OpenAI 兼容的多模态模型，从血检报告照片提取指标。

默认使用 Moonshot Kimi（国内可直接访问），通过 .env 里的 BASE_URL / MODEL
即可切换为通义千问、OpenAI 等其他 provider，业务代码无需改动。

为什么把「识别」和「单位换算」分开：
- 模型只负责原样读取报告上的数值与单位（它更擅长看图，不擅长做医学单位换算）；
- 单位换算在后端 normalize 模块完成，逻辑集中、可测试、可控；
- 模型可能看错单位，后端统一换算 + 前端人工核对，双重保险。
"""

import base64
import json
import re
from typing import Optional

import openai

from app.config import Settings
from app.schemas import MARKER_FIELDS


class VisionServiceError(Exception):
    """视觉识别服务异常，message 为可直接展示给用户的友好中文提示。"""


# System prompt 是整个识别质量的关键：要求只输出 JSON、禁止编造、
# 保留原始单位、正确处理低于检测限的 "<x" 值。
_SYSTEM_PROMPT = (
    "你是医学检验报告数据提取助手。请从用户上传的血检报告照片中提取以下 10 项指标：\n"
    "albumin(白蛋白)、creatinine(肌酐)、glucose(葡萄糖)、crp(C反应蛋白)、"
    "lymphocyte_pct(淋巴细胞百分比)、mcv(平均红细胞体积)、rdw(红细胞分布宽度RDW-CV)、"
    "alp(碱性磷酸酶)、wbc(白细胞计数)、age(实际年龄)。\n\n"
    "严格按以下 JSON 结构输出，只输出 JSON，不要输出任何解释文字：\n"
    '{"albumin": {"value": 数字或null, "unit": "报告上的原始单位", '
    '"raw_text": "报告原文片段", "confidence": 0到1的小数, "censored": true或false}, '
    '"creatinine": {...}, ...}\n\n'
    "规则：\n"
    "1. 识别不到或无法确认的项，value 输出 null，禁止编造数值；\n"
    "2. 必须连同报告上的原始单位一起返回（例如 g/L、μmol/L、mg/dL），"
    "单位换算由后端完成，你只负责原样读取；\n"
    '3. 报告写 "<0.x" 或 "<x"（低于检测限）时，value 取该阈值的一半，并把 censored 设为 true；\n'
    "4. 年龄通常不在报告上，age 恒为 null，由用户手动填写；\n"
    "5. confidence 表示你对这项提取结果的把握（0-1 的小数）。"
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

    async def extract(self, image_bytes: bytes, mime: str) -> dict:
        """上传图片字节，返回按字段分组的原始提取结果（未做单位换算）。

        返回值形如：{"albumin": {"value": 4.62, "unit": "g/dL", ...}}
        """
        data_url = (
            f"data:{mime};base64,{base64.b64encode(image_bytes).decode('ascii')}"
        )
        client = self._get_client()

        try:
            response = await client.chat.completions.create(
                model=self._settings.ai_model,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": "请提取这份血检报告照片中的上述指标。",
                            },
                            {
                                "type": "image_url",
                                "image_url": {"url": data_url},
                            },
                        ],
                    },
                ],
                # 强制 JSON 输出，减少模型输出解释性文字导致解析失败的概率
                response_format={"type": "json_object"},
            )
        except openai.APITimeoutError as exc:
            raise VisionServiceError("视觉识别超时，请稍后重试，或改用手动录入。") from exc
        except openai.APIConnectionError as exc:
            raise VisionServiceError("无法连接视觉识别服务，请检查网络与 API 配置。") from exc
        except openai.APIStatusError as exc:
            raise VisionServiceError(
                f"视觉识别服务返回错误（状态码 {exc.status_code}），请稍后重试。"
            ) from exc
        except openai.APIError as exc:
            raise VisionServiceError("视觉识别服务异常，请稍后重试。") from exc

        content = response.choices[0].message.content
        return self._parse(content)

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
