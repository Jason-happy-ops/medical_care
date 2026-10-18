"""可选的匿名化计算日志（SQLite）。

默认关闭（.env 中 STORAGE_ENABLED=false）。即使开启，也只记录「数值 + 计算结果」，
绝不记录姓名、照片、IP 等身份信息，符合 README §9 的隐私要求。
"""

import json
import sqlite3
from datetime import datetime, timezone

from app.config import Settings
from app.schemas import MARKER_FIELDS


def log_calculation(
    settings: Settings, markers: dict[str, float], result: dict
) -> None:
    """把一次计算匿名化写入 SQLite；未开启时直接返回，零开销。"""
    if not settings.storage_enabled:
        return

    settings.storage_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(settings.storage_path)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS calculations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                age REAL NOT NULL,
                pheno_age REAL NOT NULL,
                age_gap REAL NOT NULL,
                mortality_10y REAL NOT NULL,
                tier TEXT NOT NULL,
                markers_json TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            INSERT INTO calculations
                (created_at, age, pheno_age, age_gap, mortality_10y, tier, markers_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.now(timezone.utc).isoformat(),
                markers["age"],
                result["pheno_age"],
                result["age_gap"],
                result["mortality_10y"],
                result["tier"],
                json.dumps({k: markers.get(k) for k in MARKER_FIELDS}, ensure_ascii=False),
            ),
        )
        conn.commit()
    finally:
        conn.close()
