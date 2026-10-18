"""单位归一化：把视觉 AI 返回的原始单位换算到标准单位（README §4.1）。

这是整个项目最容易出错的地方：
- 公式系数是经验证的，只能代入标准单位；
- 视觉 AI 只能「原样读取」报告上的数值和单位，换算必须由后端完成；
- 若原始单位无法识别，宁可把该指标标记为「无法确认」让用户手填，
  也不能瞎猜一个系数导致结果离谱。

设计：每个指标定义「标准单位」和一张「别名 -> 换算系数」表，
normalize_value(value, unit) = value * factor。
"""

from typing import Optional


class UnknownUnitError(ValueError):
    """单位无法识别时抛出；调用方应把该指标标记为「无法确认」。"""


def _norm_unit_text(unit: str) -> str:
    """统一单位字符串，消除全角/希腊字母/上标/空格带来的差异。

    例如 "μmol/L"、"µmol/L"、"umol/L" 都应视为同一种单位。
    """
    return (
        unit.strip()
        .lower()
        .replace("µ", "u")
        .replace("μ", "u")
        .replace("³", "3")
        .replace("⁹", "9")
        .replace("²", "2")
        .replace("×", "x")
        .replace(" ", "")
    )


# field -> (标准单位, {归一化后的单位别名: 换算系数})
_UNIT_TABLE: dict[str, tuple[str, dict[str, float]]] = {
    "albumin": (
        "g/L",
        {
            "g/l": 1.0,
            "g/dl": 10.0,   # 1 g/dL = 10 g/L
            "g%": 10.0,     # g% 与 g/dL 等价
            "mg/dl": 0.01,  # 1 mg/dL = 0.01 g/L
        },
    ),
    "creatinine": (
        "μmol/L",
        {
            "umol/l": 1.0,
            "mg/dl": 88.4,   # 1 mg/dL ≈ 88.4 μmol/L（肌酐摩尔质量 113.12）
            "mmol/l": 1000.0,  # 1 mmol/L = 1000 μmol/L
        },
    ),
    "glucose": (
        "mmol/L",
        {
            "mmol/l": 1.0,
            # 1 mg/dL ≈ 0.0555 mmol/L（葡萄糖摩尔质量 180.16，故除以 18.016）
            "mg/dl": 1 / 18.016,
            "g/l": 5.55,  # 1 g/L = 100 mg/dL ≈ 5.55 mmol/L（少见，防呆）
        },
    ),
    "crp": (
        "mg/L",
        {
            "mg/l": 1.0,
            "ug/ml": 1.0,  # μg/mL 与 mg/L 数值等价
            "mg/dl": 10.0,  # 1 mg/dL = 10 mg/L
        },
    ),
    "lymphocyte_pct": ("%", {"%": 1.0}),
    "mcv": (
        "fL",
        {
            "fl": 1.0,
            "um3": 1.0,  # 1 fL = 1 μm³
        },
    ),
    "rdw": ("%", {"%": 1.0}),
    "alp": (
        "U/L",
        {
            "u/l": 1.0,
            "iu/l": 1.0,
            "ukat/l": 60.0,  # 1 μkat/L = 60 U/L
        },
    ),
    "wbc": (
        "10^9/L",
        {
            # 血常规里 10^3/μL、G/L、/mm³ 与 10^9/L 数值等价
            "10^9/l": 1.0,
            "10^3/ul": 1.0,
            "10^3/mm3": 1.0,
            "g/l": 1.0,
            "x10^9/l": 1.0,
            "10e9/l": 1.0,
        },
    ),
}


def standard_unit_for(field: str) -> str:
    """返回某指标的标准单位字符串。"""
    return _UNIT_TABLE[field][0]


def normalize_value(field: str, value: float, unit: Optional[str]) -> float:
    """把某指标在原始单位下的数值换算到标准单位。

    无法识别单位时抛 UnknownUnitError，由调用方决定如何处理
    （本项目约定：标记为「无法确认」，让用户手填）。
    """
    if field not in _UNIT_TABLE:
        raise UnknownUnitError(f"未知指标字段：{field}")
    if unit is None:
        raise UnknownUnitError("缺少单位，无法换算")

    _, factors = _UNIT_TABLE[field]
    factor = factors.get(_norm_unit_text(unit))
    if factor is None:
        raise UnknownUnitError(f"无法识别的单位：{unit}")
    return value * factor
