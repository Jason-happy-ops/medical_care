"""/api 路由：上传提取、手动计算、一步到位诊断。

关键设计：
- 上传校验（扩展名 + MIME 白名单 + 大小上限）和落盘采用随机文件名，
  从源头杜绝路径穿越与恶意文件；
- 视觉识别失败统一转成 502 + 友好中文提示，前端据此引导用户改用手动录入；
- /api/diagnose 复用了 extract 与 calculate 的同一套逻辑，避免复制粘贴。
"""

import logging
import time
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import ValidationError

from app.config import get_settings
from app.schemas import (
    MARKER_FIELDS,
    CalculateRequest,
    CalculateResult,
    DiagnoseResponse,
    ExtractResponse,
    MarkerExtraction,
)
from app.services import storage
from app.services.normalize import (
    UnknownUnitError,
    normalize_value,
    standard_unit_for,
)
from app.services.phenoage import DISCLAIMER, calculate
from app.services.vision import VisionClient, VisionServiceError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")

settings = get_settings()
vision_client = VisionClient(settings)

_ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
_ALLOWED_MIME = {"image/jpeg", "image/png", "image/webp"}
_EXT_TO_MIME = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}


async def _read_limited(file: UploadFile, limit: int) -> bytes:
    """分块读取上传内容并在超过上限时立即中断，避免超大文件占满内存。"""
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(1024 * 1024)  # 每次读 1 MB
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise HTTPException(status_code=413, detail="图片大小不能超过 10 MB。")
        chunks.append(chunk)
    return b"".join(chunks)


def _validate_upload(filename: Optional[str], content_type: Optional[str], size: int) -> str:
    """校验扩展名 / MIME / 大小，返回带点的合法扩展名。"""
    ext = Path(filename or "").suffix.lower()
    if ext not in _ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="仅支持 jpg / png / webp 格式的图片。")
    if content_type not in _ALLOWED_MIME:
        raise HTTPException(status_code=400, detail="文件类型不合法，仅支持 jpg / png / webp。")
    if size > settings.max_upload_bytes:
        raise HTTPException(status_code=400, detail="图片大小不能超过 10 MB。")
    return ext


def _save_upload(content: bytes, ext: str, image_id: str) -> None:
    """用随机 image_id 作为文件名落盘，天然避免路径穿越与重名冲突。"""
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    (settings.upload_dir / f"{image_id}{ext}").write_bytes(content)


def _cleanup_old_uploads(now: Optional[float] = None) -> None:
    """按保留时长清理旧照片。只删除 uploads 目录内带合法图片扩展名的文件，
    且不做递归，保证清理范围严格受控。"""
    now = time.time() if now is None else now
    max_age = settings.upload_retention_hours * 3600
    if max_age <= 0 or not settings.upload_dir.exists():
        return
    for path in settings.upload_dir.iterdir():
        if not path.is_file() or path.suffix.lower() not in _ALLOWED_EXTENSIONS:
            continue
        try:
            if now - path.stat().st_mtime > max_age:
                path.unlink()
        except OSError:
            logger.warning("清理上传文件失败：%s", path, exc_info=True)


async def _extract_markers(
    file: UploadFile,
) -> tuple[dict[str, Optional[MarkerExtraction]], list[str], str]:
    """提取 + 校验 + 落盘 + 归一化，供 /api/extract 与 /api/diagnose 复用。"""
    content = await _read_limited(file, settings.max_upload_bytes)
    ext = _validate_upload(file.filename, file.content_type, len(content))
    mime = file.content_type or _EXT_TO_MIME[ext]
    image_id = uuid.uuid4().hex
    _save_upload(content, ext, image_id)
    _cleanup_old_uploads()

    try:
        raw = await vision_client.extract(content, mime)
    except VisionServiceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    extracted: dict[str, Optional[MarkerExtraction]] = {}
    missing: list[str] = []
    for field in MARKER_FIELDS:
        item = raw.get(field)
        if item is None:
            extracted[field] = None
            missing.append(field)
            continue
        try:
            # 关键步骤：把原始单位换算到标准单位；换算不了就标记为未识别
            value = normalize_value(field, item["value"], item["unit"])
        except UnknownUnitError:
            extracted[field] = None
            missing.append(field)
            continue
        extracted[field] = MarkerExtraction(
            value=round(value, 4),
            unit=standard_unit_for(field),
            raw_text=item.get("raw_text"),
            confidence=item.get("confidence"),
            censored=item.get("censored", False),
        )

    return extracted, missing, image_id


def _build_result(markers: dict[str, float]) -> CalculateResult:
    """把 10 项标准单位数值算成结果模型（calculate 与 diagnose 共用）。"""
    result = calculate(markers)
    storage.log_calculation(settings, markers, result)
    return CalculateResult(
        pheno_age=round(result["pheno_age"], 1),
        age=markers["age"],
        age_gap=round(result["age_gap"], 1),
        phenoage_accel=round(result["age_gap"], 1),
        mortality_10y=result["mortality_10y"],
        tier=result["tier"],
        interpretation=result["interpretation"],
        disclaimer=DISCLAIMER,
    )


@router.post("/extract", response_model=ExtractResponse)
async def extract(file: UploadFile = File(...)) -> ExtractResponse:
    """上传血检报告照片，返回结构化提取结果（值已归一化到标准单位）。"""
    extracted, missing, image_id = await _extract_markers(file)
    return ExtractResponse(extracted=extracted, missing=missing, image_id=image_id)


@router.post("/calculate", response_model=CalculateResult)
async def calculate_endpoint(req: CalculateRequest) -> CalculateResult:
    """提交 10 项标准单位数值，计算 PhenoAge 及相关指标。"""
    markers = req.model_dump()
    return _build_result(markers)


@router.post("/diagnose", response_model=DiagnoseResponse)
async def diagnose(
    file: UploadFile = File(...),
    age: Optional[float] = Form(default=None),
) -> DiagnoseResponse:
    """一步到位：上传照片并（若用户补充年龄后指标齐全）直接给出结果。

    注意：年龄通常不在报告上，所以本接口额外接收 age 表单字段；
    其他缺失指标仍需用户在前端补填后走 /api/calculate。
    """
    extracted, missing, image_id = await _extract_markers(file)

    markers: dict[str, float] = {}
    for field in MARKER_FIELDS:
        if field == "age":
            value = age
        else:
            item = extracted.get(field)
            value = item.value if item else None
        if value is None:
            if field not in missing:
                missing.append(field)
        else:
            markers[field] = value

    result: Optional[CalculateResult] = None
    if not missing:
        try:
            req = CalculateRequest(**markers)
        except ValidationError:
            raise HTTPException(
                status_code=422, detail="指标数值超出合理范围，请核对后重试。"
            )
        result = _build_result(req.model_dump())

    return DiagnoseResponse(
        extracted=extracted, missing=missing, image_id=image_id, result=result
    )
