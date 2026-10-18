"""公式单元测试：README §4.2 的验证用例与边界情况。"""

import math

from app.services.phenoage import (
    calculate,
    pheno_age_from_xb,
    mortality_10y,
    compute_xb,
    tier_and_interpretation,
)

# README §4.2 验证用例的基准输入
BASE = {
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


def test_reference_case_matches_paper():
    """验证用例：PhenoAge 应约为 37.9，允许 ±0.1 误差。"""
    result = calculate(BASE)
    assert abs(result["pheno_age"] - 37.9) <= 0.1


def test_log_space_equivalent_to_original_form():
    """log 空间等价式应与原式一致（在 M 不接近 1 的正常区间）。"""
    xb = compute_xb(BASE)
    m = mortality_10y(xb)
    original = 141.50225 + math.log(-0.00553 * math.log(1 - m)) / 0.090165
    assert math.isclose(pheno_age_from_xb(xb), original, rel_tol=1e-9)


def test_crp_zero_is_clamped():
    """crp=0（报告低于检测限）不应抛异常，且结果有限。"""
    result = calculate({**BASE, "crp": 0})
    assert math.isfinite(result["pheno_age"])
    assert math.isfinite(result["mortality_10y"])


def test_crp_negative_is_clamped():
    """crp 为负数（异常输入）也应被 clamp，不抛异常。"""
    result = calculate({**BASE, "crp": -5})
    assert math.isfinite(result["pheno_age"])


def test_extreme_values_do_not_raise():
    """极端指标不应抛异常，且死亡风险保持在 [0,1]。"""
    extreme = {
        "albumin": 80,
        "creatinine": 2000,
        "glucose": 60,
        "crp": 1000,
        "lymphocyte_pct": 80,
        "mcv": 150,
        "rdw": 40,
        "alp": 2000,
        "wbc": 100,
        "age": 120,
    }
    result = calculate(extreme)
    assert math.isfinite(result["pheno_age"])
    assert 0.0 <= result["mortality_10y"] <= 1.0


def test_mortality_within_range():
    result = calculate(BASE)
    assert 0.0 < result["mortality_10y"] < 1.0


def test_age_gap_sign():
    result = calculate(BASE)
    assert result["age_gap"] == result["pheno_age"] - BASE["age"]


def test_tier_boundaries():
    """分档边界：|gap|<=2 持平，>2 偏老，<-2 偏年轻。"""
    assert tier_and_interpretation(0)[0] == "average"
    assert tier_and_interpretation(2)[0] == "average"
    assert tier_and_interpretation(-2)[0] == "average"
    assert tier_and_interpretation(2.1)[0] == "older"
    assert tier_and_interpretation(-2.1)[0] == "younger"
