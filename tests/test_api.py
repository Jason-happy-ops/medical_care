"""API 单元测试：健康检查、计算正常路径与参数校验。"""

import os

os.environ.setdefault("AI_API_KEY", "test-dummy-key")

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

VALID = {
    "albumin": 45,
    "creatinine": 80,
    "glucose": 5.5,
    "crp": 3,
    "lymphocyte_pct": 30,
    "mcv": 90,
    "rdw": 13,
    "alp": 80,
    "wbc": 6,
    "age": 40,
}


def test_healthz():
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_index_serves_html():
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


def test_calculate_ok():
    resp = client.post("/api/calculate", json=VALID)
    assert resp.status_code == 200
    data = resp.json()
    assert abs(data["pheno_age"] - 37.9) <= 0.1
    assert "disclaimer" in data
    assert data["phenoage_accel"] == data["age_gap"]


def test_calculate_missing_field_returns_422():
    payload = {k: v for k, v in VALID.items() if k != "age"}
    resp = client.post("/api/calculate", json=payload)
    assert resp.status_code == 422


def test_calculate_out_of_range_returns_chinese_422():
    resp = client.post("/api/calculate", json={**VALID, "age": 0})
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert any("实际年龄" in item for item in detail)


def test_extract_rejects_bad_extension():
    resp = client.post(
        "/api/extract",
        files={"file": ("evil.txt", b"hello", "text/plain")},
    )
    assert resp.status_code == 400


def test_extract_rejects_oversize():
    big = b"x" * (11 * 1024 * 1024)
    resp = client.post(
        "/api/extract",
        files={"file": ("big.png", big, "image/png")},
    )
    assert resp.status_code == 413
