# PhenoAge 生理年龄测算

上传血检报告照片，自动提取 10 项生物标志物并计算生理年龄（PhenoAge）、
10 年死亡风险与老化加速值。结果以可编辑表单核对后展示为结果卡片，
支持手动录入、无需上传照片。

项目由 FastAPI + 原生前端构成，可在个人电脑上运行，并通过
Cloudflare Tunnel 暴露到公网，自动获得 HTTPS。

> 结果由公开公式计算，仅供健康参考，不构成医疗诊断。

## 功能特性

- 照片识别：支持一次上传多张报告照片（如血常规 + 生化），调用 OpenAI 兼容的
  多模态视觉模型逐张识别后按置信度合并结果。
- Provider 可切换：默认 Moonshot Kimi，修改 `.env` 即可替换为其他兼容服务。
- 单位归一化：后端统一把报告原始单位换算到公式要求的标准单位，避免因单位
  错误导致结果失真。
- 可编辑核对：识别结果自动回填表单，支持人工修正与补填。
- 手动录入：不上传照片也可直接输入 10 项指标计算。
- 结果卡片：展示 PhenoAge、与实际年龄的差值、10 年死亡风险和分档解读，
  支持导出为 PNG。
- 隐私友好：密钥只存 `.env`，上传照片 24 小时自动清理，不收集身份信息。

## 快速开始

### 环境要求

- Python 3.11 及以上
- Windows / macOS / Linux
- Moonshot API Key（或其他 OpenAI 兼容服务的 Key）

### 安装与运行

```bash
# 1. 进入项目根目录
# 2. 创建虚拟环境并安装依赖
python -m venv .venv

# Windows
.venv\Scripts\activate
# macOS / Linux
# source .venv/bin/activate

pip install -r requirements.txt

# 3. 配置环境变量
# Windows
copy .env.example .env
# macOS / Linux
# cp .env.example .env

# 编辑 .env，填入 AI_API_KEY

# 4. 启动服务
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

浏览器打开 <http://127.0.0.1:8000> 即可使用。健康检查地址为
<http://127.0.0.1:8000/healthz>。

Windows 下双击 `scripts/start_all.bat` 即可一键启动后端与 Cloudflare 隧道。

## 配置

全部配置通过环境变量或 `.env` 提供，模板见 `.env.example`。

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `AI_API_KEY` | - | 必填，视觉模型的 API Key |
| `AI_BASE_URL` | `https://api.moonshot.cn/v1` | OpenAI 兼容接口地址 |
| `AI_MODEL` | `kimi-k3` | 视觉识别模型（如遇问题可回退 `kimi-k2.6`） |
| `AI_TIMEOUT_SECONDS` | `60` | 单次识别超时（秒） |
| `MAX_UPLOAD_BYTES` | `10485760` | 上传大小上限（10 MB） |
| `UPLOAD_RETENTION_HOURS` | `24` | 上传照片保留时长 |
| `STORAGE_ENABLED` | `false` | 是否启用匿名化计算日志 |

## 使用流程

1. 上传一张或多张血检报告照片（jpg / png / webp，单张不超过 10 MB），
   或跳过上传手动录入。
2. 后端调用视觉模型提取 10 项指标，并返回原始单位与置信度。
3. 在表单中核对、补填指标（年龄通常不在报告上，需要手动填写）。
4. 点击「开始计算」，查看结果卡片。
5. 可选：保存结果卡片为图片。

## 核心算法

实现基于 Levine et al. (2018) 的 PhenoAge 公式，实现在
`app/services/phenoage.py`。

10 项输入指标采用中国医院检验报告常用单位，这是本项目最容易出错的地方。
视觉模型只负责原样读取报告上的数值与单位，换算由后端
`app/services/normalize.py` 统一完成。

| 字段 | 中文名 | 单位 |
| --- | --- | --- |
| `albumin` | 白蛋白 | g/L |
| `creatinine` | 肌酐 | μmol/L |
| `glucose` | 葡萄糖（血糖） | mmol/L |
| `crp` | C 反应蛋白 | mg/L |
| `lymphocyte_pct` | 淋巴细胞百分比 | % |
| `mcv` | 平均红细胞体积 | fL |
| `rdw` | 红细胞分布宽度（RDW-CV） | % |
| `alp` | 碱性磷酸酶 | U/L |
| `wbc` | 白细胞计数 | 10⁹/L |
| `age` | 实际年龄 | 岁 |

计算流程：

```text
xb = -19.907 - 0.0336×albumin + 0.0095×creatinine + 0.1953×glucose
   + 0.0954×ln(crp) - 0.0120×lymphocyte_pct + 0.0268×mcv
   + 0.3306×rdw + 0.00188×alp + 0.0554×wbc + 0.0804×age

M = 1 - exp(-exp(xb) × (exp(120×γ) - 1) / γ)     # γ = 0.0076927
PhenoAge = 141.50225 + (xb + log_scale) / 0.090165
age_gap = PhenoAge - age
```

其中 `crp ≤ 0` 时 clamp 到 `0.01` 再取对数，以应对「<0.x」这类低于检测限
的报告值；`PhenoAge` 采用 log 空间等价式计算，避免 `M` 接近 1 时的数值溢出。

解读分档：`|age_gap| ≤ 2` 为基本持平，`> 2` 为偏「老」，`< -2` 为偏「年轻」。

## API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/` | 前端单页 |
| GET | `/healthz` | 健康检查 |
| POST | `/api/extract` | 上传照片，返回提取指标 |
| POST | `/api/calculate` | 提交 10 项数值，返回计算结果 |
| POST | `/api/diagnose` | 上传照片并计算（便捷接口） |

`/api/calculate` 响应示例：

```json
{
  "pheno_age": 37.9,
  "age": 40.0,
  "age_gap": -2.1,
  "phenoage_accel": -2.1,
  "mortality_10y": 0.0158,
  "tier": "younger",
  "interpretation": "你的生理年龄低于实际年龄，整体状态优于同龄人。",
  "disclaimer": "本结果由公开公式计算，仅供健康参考。"
}
```

## 项目结构

```text
.
├── app/
│   ├── main.py             # 应用入口：路由挂载、静态资源、异常处理
│   ├── config.py           # 配置读取（pydantic-settings）
│   ├── schemas.py          # 请求 / 响应模型
│   ├── routers/
│   │   └── diagnose.py     # /api 三个接口
│   ├── services/
│   │   ├── phenoage.py     # PhenoAge 公式与解读
│   │   ├── normalize.py    # 单位归一化
│   │   ├── vision.py       # 视觉模型接入
│   │   └── storage.py      # 可选匿名化日志
│   └── static/
│       ├── index.html
│       ├── style.css
│       └── app.js
├── scripts/
│   ├── start_all.bat       # 一键启动后端 + Cloudflare 隧道
│   ├── cloudflared.exe     # 隧道客户端（本地二进制，不入库）
│   └── smoke_vision.py     # 视觉识别端到端冒烟测试
├── tests/
│   ├── test_phenoage.py
│   └── test_api.py
├── docs/
│   └── deploy.md           # 部署说明
├── requirements.txt
├── .env.example
├── .gitignore
├── conftest.py
└── pytest.ini
```

## 测试

```bash
pytest
```

覆盖公式验证用例（PhenoAge ≈ 37.9，误差 ±0.1）、CRP 为 0 或负数的边界、
极端指标不抛异常，以及 API 参数校验。

## 部署

详细步骤见 `docs/deploy.md`。整体思路是：本地 FastAPI 服务监听
`127.0.0.1:8000`，由 cloudflared 隧道将 `medicalcare.work` 等域名转发到本机，
无需公网 IP 即可获得 HTTPS 访问。

## 安全与隐私

- 密钥仅存于 `.env`，该文件已被 `.gitignore` 排除。
- 上传校验：扩展名与 MIME 白名单、10 MB 上限、随机文件名落盘。
- 上传照片默认 24 小时自动清理，不记录姓名等身份信息。
- 对外的错误信息不暴露内部实现细节。

## 免责声明

本结果由公开公式计算，仅供健康参考，不构成医疗诊断或医疗建议；如有不适请就医。

## 参考

- Levine ME, et al. "An epigenetic biomarker of aging for lifespan and
  healthspan." *Aging* 2018;10(4):573-591.
