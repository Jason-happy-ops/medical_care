"""Levine PhenoAge 公式实现（Levine et al. 2018, NHANES III）。

本模块只做纯计算，不依赖 FastAPI，便于直接做单元测试。

单位约定（关键，勿改，见 README §4.1）：
- 白蛋白 g/L、肌酐 μmol/L、血糖 mmol/L、CRP mg/L、ALP U/L、WBC 10^9/L，
  其余为 % / fL / 岁。这些是「中国医院检验报告常用单位」。
- 公式系数是经验证的：若误代入美国单位（白蛋白 g/dL、肌酐 mg/dL、血糖 mg/dL），
  结果会荒谬（数百岁）。因此单位归一化必须在进入本模块之前完成。
"""

import math

# Gompertz 死亡率模型参数，文献给定值
GAMMA = 0.0076927

# log 空间等价式中的常数项（≈ 0.08673），推导见 README §4.2 的推荐实现。
# 先算好避免每次请求都重复计算，也避免 M 接近 1 时取对数带来的数值不稳定。
LOG_SCALE = math.log(0.00553 * math.expm1(120 * GAMMA) / GAMMA)

# 全站统一的免责声明，前端与接口共用，保证文案一致
DISCLAIMER = (
    "本结果由公开公式计算，仅供健康参考，不构成医疗诊断或医疗建议；如有不适请就医。"
)


def compute_xb(markers: dict[str, float]) -> float:
    """第 1 步：计算 10 项指标线性组合得分 xb。

    参数 markers 必须是已归一化到标准单位的数值字典（键见 schemas.MARKER_FIELDS）。
    """
    # CRP 需要取自然对数。报告里常见 "<0.x"（低于检测限）这类值，
    # 实际数值未知，按 README 约定 clamp 到 0.01 再取对数，避免 log(0) 报错。
    ln_crp = math.log(max(markers["crp"], 0.01))

    xb = (
        -19.907
        - 0.0336 * markers["albumin"]
        + 0.0095 * markers["creatinine"]
        + 0.1953 * markers["glucose"]
        + 0.0954 * ln_crp
        - 0.0120 * markers["lymphocyte_pct"]
        + 0.0268 * markers["mcv"]
        + 0.3306 * markers["rdw"]
        + 0.00188 * markers["alp"]
        + 0.0554 * markers["wbc"]
        + 0.0804 * markers["age"]
    )
    return xb


def mortality_10y(xb: float) -> float:
    """第 2 步：10 年死亡风险 M = 1 - exp(-exp(xb) * (exp(120γ) - 1) / γ)。

    当 xb 很大时 exp(xb) 仍可能在 double 范围内，但 exp(-很大的正数) 会直接
    下溢为 0，Python 不会报错；这里显式判断内层参数 > 709（exp(709) 已接近
    double 上限），直接返回 1.0，保证数值稳定且语义正确。
    """
    inner = math.exp(xb) * math.expm1(120 * GAMMA) / GAMMA
    if inner > 709.0:
        return 1.0
    return 1.0 - math.exp(-inner)


def pheno_age_from_xb(xb: float) -> float:
    """第 3 步：由 xb 计算 PhenoAge（log 空间等价式）。

    原式为 PhenoAge = 141.50225 + ln(-0.00553 * ln(1 - M)) / 0.090165。
    当 M 非常接近 1 时 ln(1-M) 数值不稳定；README 推荐的等价式直接基于 xb
    计算，数学上等价且不会因浮点舍入溢出。
    """
    return 141.50225 + (xb + LOG_SCALE) / 0.090165


def tier_and_interpretation(age_gap: float) -> tuple[str, str]:
    """根据 PhenoAge 与实际年龄的差值给出分档与通俗解读。"""
    if abs(age_gap) <= 2:
        return (
            "average",
            "你的生理年龄与实际年龄基本持平，整体状态与同龄人相当。",
        )
    if age_gap > 2:
        return (
            "older",
            "你的生理年龄高于实际年龄，提示可能存在多系统老化加速风险。"
            "建议关注睡眠、饮食与运动，并定期体检；如有疑问请咨询医生。",
        )
    return (
        "younger",
        "你的生理年龄低于实际年龄，整体状态优于同龄人，请继续保持。",
    )


def calculate(markers: dict[str, float]) -> dict:
    """一站式计算：返回 xb、10 年死亡风险、PhenoAge、差值、分档与解读。"""
    xb = compute_xb(markers)
    m = mortality_10y(xb)
    pheno_age = pheno_age_from_xb(xb)
    age_gap = pheno_age - markers["age"]
    tier, interpretation = tier_and_interpretation(age_gap)

    return {
        "xb": xb,
        "mortality_10y": m,
        "pheno_age": pheno_age,
        "age_gap": age_gap,
        "tier": tier,
        "interpretation": interpretation,
    }
