"""FastAPI 应用入口：挂载路由、静态资源，并统一处理中文校验错误。"""

import logging
import re
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.routers import diagnose
from app.schemas import FIELD_LABELS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    """启动 / 关闭时的生命周期钩子。

    启动即校验密钥：缺失时打印清晰中文提示并退出，而不是带空密钥运行到
    视觉识别阶段才抛出一堆 SDK 堆栈（验收标准第 4 条）。
    """
    try:
        settings.ensure_secrets()
    except RuntimeError as exc:
        logger.error("启动失败：%s", exc)
        print(f"\n[启动失败] {exc}\n")
        raise SystemExit(1)
    logger.info("%s 启动，视觉模型=%s", settings.app_name, settings.ai_model)
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.include_router(diagnose.router)

# 前端静态资源：/static/... 提供 css/js 等资源；/ 返回单页 HTML
STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    """返回前端单页。"""
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/healthz")
async def healthz() -> dict:
    """健康检查，供隧道 / 监控探活使用。"""
    return {"status": "ok"}


def _translate_validation_msg(err: dict) -> str:
    """把 Pydantic v2 的英文校验信息翻译成中文。"""
    err_type = err.get("type")
    msg = str(err.get("msg", ""))
    if err_type == "missing":
        return "必填，不能为空"
    if err_type in ("float_parsing", "int_parsing", "float_type", "int_type"):
        return "必须是数字"

    # 越界类信息形如 "Input should be greater than or equal to 10"
    match = re.search(r"greater than or equal to ([\d.]+)", msg)
    if match:
        return f"不能小于 {match.group(1)}"
    match = re.search(r"less than or equal to ([\d.]+)", msg)
    if match:
        return f"不能大于 {match.group(1)}"
    match = re.search(r"greater than ([\d.]+)", msg)
    if match:
        return f"必须大于 {match.group(1)}"
    match = re.search(r"less than ([\d.]+)", msg)
    if match:
        return f"必须小于 {match.group(1)}"
    return msg


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    _: Request, exc: RequestValidationError
) -> JSONResponse:
    """把请求参数校验失败统一转成 422 + 中文错误列表，不向外部泄露堆栈。"""
    errors: list[str] = []
    for err in exc.errors():
        loc = [str(part) for part in err.get("loc", ()) if part != "body"]
        field = loc[-1] if loc else ""
        label = FIELD_LABELS.get(field, field)
        errors.append(f"{label}：{_translate_validation_msg(err)}")
    return JSONResponse(status_code=422, content={"detail": errors})
