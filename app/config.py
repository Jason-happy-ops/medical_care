"""应用配置模块：统一从环境变量与 .env 文件读取所有可配置项。

为什么这么做：
- 密钥（AI_API_KEY 等）绝不能写进代码或提交进 Git，统一放 .env，并通过
  .gitignore 排除，从源头避免泄露；
- pydantic-settings 会对配置做类型校验，配置缺失或类型错误能在启动阶段
  暴露出来，而不是运行到一半才出现难以排查的 KeyError / 类型错误；
- 集中管理配置，业务代码只通过 get_settings() 取用，改配置不需要改动业务逻辑。
"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """全部可配置项。

    字段名与 .env 中的大写变量名一一对应（pydantic-settings 匹配环境变量时
    大小写不敏感），例如 ai_api_key 对应 .env 里的 AI_API_KEY。
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        # .env 中多出的未知变量不报错，方便部署方自行扩展配置
        extra="ignore",
    )

    # 应用基础信息
    app_name: str = "PhenoAge 生理年龄测算"

    # ---- 视觉 AI 配置（默认 Moonshot Kimi，可切换任意 OpenAI 兼容服务）----
    ai_api_key: str = ""
    ai_base_url: str = "https://api.moonshot.cn/v1"
    ai_model: str = "kimi-k3"
    ai_timeout_seconds: float = 60.0

    # ---- 上传限制与隐私 ----
    max_upload_bytes: int = 10 * 1024 * 1024  # 10 MB
    upload_dir: Path = Path("uploads")
    upload_retention_hours: int = 24

    # ---- 可选：匿名化计算日志（SQLite），默认关闭 ----
    storage_enabled: bool = False
    storage_path: Path = Path("logs/phenoage.db")

    def ensure_secrets(self) -> None:
        """启动时校验必要配置。

        缺失密钥时抛出带清晰中文提示的 RuntimeError，而不是让程序带着空密钥
        运行到视觉识别阶段才失败（验收标准第 4 条）。
        """
        if not self.ai_api_key:
            raise RuntimeError(
                "未配置 AI_API_KEY。请先复制 .env.example 为 .env，并在其中填入"
                "你的 Moonshot（或其他 OpenAI 兼容服务）API Key 后再启动。"
            )


@lru_cache
def get_settings() -> Settings:
    """进程内只解析一次配置，避免每次请求都重新读取 .env 文件。"""
    return Settings()
