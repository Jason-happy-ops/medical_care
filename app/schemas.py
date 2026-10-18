"""Pydantic 请求 / 响应模型。

为什么用 Pydantic 做数据模型：
- 请求体在进入业务逻辑之前就完成类型与取值范围校验，非法数据被提前拦截；
- 响应模型保证返回结构稳定，前端可以放心按字段渲染，不怕后端悄悄改结构；
- 校验失败会抛 RequestValidationError，由 main.py 统一转成中文 422 提示。
"""

from typing import Optional

from pydantic import BaseModel, Field

# 10 项输入指标的固定顺序（视觉提取、表单渲染、计算都用它，避免各处写死不同顺序）
MARKER_FIELDS = [
    "albumin",
    "creatinine",
    "glucose",
    "crp",
    "lymphocyte_pct",
    "mcv",
    "rdw",
    "alp",
    "wbc",
    "age",
]

# 字段名 -> 中文名，用于把 Pydantic 的校验错误翻译成用户能看懂的提示
FIELD_LABELS = {
    "albumin": "白蛋白",
    "creatinine": "肌酐",
    "glucose": "葡萄糖",
    "crp": "C 反应蛋白",
    "lymphocyte_pct": "淋巴细胞百分比",
    "mcv": "平均红细胞体积",
    "rdw": "红细胞分布宽度",
    "alp": "碱性磷酸酶",
    "wbc": "白细胞计数",
    "age": "实际年龄",
}


class MarkerExtraction(BaseModel):
    """单项生物标志物的提取结果。

    注意：这里的 value 已经是后端按 §4.1 换算到标准单位后的数值，
    raw_text 保留报告原文片段，方便用户核对 AI 有没有看错。
    """

    value: Optional[float] = None
    unit: Optional[str] = None
    raw_text: Optional[str] = None
    confidence: Optional[float] = None
    censored: bool = False  # 报告写 "<0.x" 等低于检测限时标记为 True


class ExtractResponse(BaseModel):
    """POST /api/extract 的响应体。"""

    extracted: dict[str, Optional[MarkerExtraction]]
    missing: list[str]  # 未识别出的字段 key，前端据此提示用户手填
    image_id: str  # 用于排查问题的图片标识


class CalculateRequest(BaseModel):
    """POST /api/calculate 的请求体：10 项标准单位数值。

    范围检查采用「宽于临床极限」的合理边界：既能挡住明显错误（如年龄填 0、
    百分比填 500），又不会误伤真实报告里的极端值。
    """

    albumin: float = Field(ge=10, le=80, description="白蛋白 g/L")
    creatinine: float = Field(ge=10, le=2000, description="肌酐 μmol/L")
    glucose: float = Field(ge=1, le=60, description="葡萄糖 mmol/L")
    # crp 允许为 0（部分报告低于检测限显示 <1），公式内部会 clamp 到 0.01
    crp: float = Field(ge=0, le=1000, description="C 反应蛋白 mg/L")
    lymphocyte_pct: float = Field(ge=1, le=80, description="淋巴细胞百分比 %")
    mcv: float = Field(ge=50, le=150, description="平均红细胞体积 fL")
    rdw: float = Field(ge=8, le=40, description="红细胞分布宽度 %")
    alp: float = Field(ge=10, le=2000, description="碱性磷酸酶 U/L")
    wbc: float = Field(ge=0.1, le=100, description="白细胞计数 10^9/L")
    age: float = Field(ge=1, le=120, description="实际年龄 岁")


class CalculateResult(BaseModel):
    """POST /api/calculate 的响应体。"""

    pheno_age: float
    age: float
    age_gap: float
    # 单人场景下直接用 PhenoAge - age 作为加速度的简化值，
    # 与学术论文中对同龄人群回归残差的 PhenoAgeAccel 不完全等同（见 README §4.2）
    phenoage_accel: float
    mortality_10y: float  # 小数形式（0.0158 = 1.58%），前端自行转百分比
    tier: str  # average / older / younger
    interpretation: str
    disclaimer: str


class DiagnoseResponse(BaseModel):
    """POST /api/diagnose 的响应体：提取结果 + 可能存在的计算结果。"""

    extracted: dict[str, Optional[MarkerExtraction]]
    missing: list[str]
    image_id: str
    result: Optional[CalculateResult] = None  # 指标齐全时才不为 None
