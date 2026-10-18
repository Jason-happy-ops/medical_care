# PhenoAge 生理年龄测算网站

> 上传血检报告照片 → AI 视觉 API 自动提取 9 项生物标志物 + 实际年龄 → 服务端代入 Levine PhenoAge 公式计算生理年龄 → 输出结果与解读。
> 本 README 是完整需求文档，请按本文档实现整个项目。

---

## 1. 项目目标

- 本网站部署在公网可访问的链接上，服务器为开发者自己的个人电脑（Windows）。
- 用户通过手机/电脑浏览器访问链接，上传一份血检报告照片（血常规 + 生化）。
- 后端调用多模态 AI API（视觉大模型）从照片中自动识别并结构化提取 10 个数值。
- 后端按公开的 Levine PhenoAge 公式计算**表型年龄（PhenoAge）**、**10 年死亡风险**、**生理年龄加速值（PhenoAgeAccel）**，并生成通俗解读。
- 前端展示结果卡片，显著位置标注"仅供健康参考，不构成医疗诊断"。

## 2. 用户流程

1. 用户打开公网链接 → 单页应用：上传照片（jpg / png，≤ 10 MB），或跳过上传直接手动录入指标。
2. 前端 `POST /api/extract` 上传照片，后端调用视觉 AI 返回结构化 JSON（含每项指标的原文字符串与单位，识别不到为 `null`）。
3. 前端将结果填入可编辑表单，用户核对/修正缺失项（年龄通常不在报告上，必须手填），点击"开始计算"。
4. 前端 `POST /api/calculate` 提交 10 项数值，后端校验并计算，返回结果。
5. 前端展示：PhenoAge（保留 1 位小数）、实际年龄、差值（偏"老"/偏"年轻"）、10 年死亡风险（%）、分档解读文案、免责声明。
6. （可选）生成结果卡片图片供保存。

## 3. 技术栈

| 层 | 选型 | 理由 |
|---|---|---|
| 后端 | Python 3.11 + FastAPI + uvicorn | 轻量、异步、自带文档；生态成熟 |
| 视觉 AI | Moonshot Kimi 视觉模型（默认），OpenAI 兼容接口 | 国内可直接访问，OpenAI SDK 换 base_url 即可；做成 provider 可切换（备选：通义千问 `qwen-vl-max`、OpenAI `gpt-4o`） |
| 前端 | 原生 HTML/CSS/JS 单页（无构建步骤），FastAPI 挂载 `static/` | 个人项目足够，部署最简单 |
| 公网暴露 | cloudflared（Cloudflare Tunnel） | 免费、无需公网 IP、自动 HTTPS；备选见 §8 |
| 配置 | pydantic-settings + python-dotenv，全部密钥放 `.env` | 密钥不进代码库 |
| 校验 | Pydantic v2 | 请求/响应模型 |
| 测试 | pytest + httpx | 公式与 API 单元测试 |
| （可选）存储 | SQLite（记录匿名化计算日志） | 默认可关 |

**依赖（requirements.txt）**：`fastapi`、`uvicorn[standard]`、`pydantic`、`pydantic-settings`、`python-dotenv`、`openai`、`python-multipart`、`httpx`、`pytest`

## 4. 核心公式（**严格按此实现，已核对文献**）

### 4.1 输入指标与单位约定（**关键，勿改单位**）

公式系数来自 Levine et al. 2018（NHANES III），经验证应直接代入**中国医院检验报告常用单位**：

| 字段（JSON key） | 中文名 | 单位 | 备注 |
|---|---|---|---|
| `albumin` | 白蛋白 | g/L | 报告常见 35–55 |
| `creatinine` | 肌酐 | μmol/L | 报告常见 40–110 |
| `glucose` | 葡萄糖（血糖） | mmol/L | 最好是空腹血糖 |
| `crp` | C 反应蛋白 | mg/L | 必须 > 0，取自然对数 |
| `lymphocyte_pct` | 淋巴细胞百分比 | % | 血常规 |
| `mcv` | 平均红细胞体积 | fL | 血常规 |
| `rdw` | 红细胞分布宽度 | %（RDW-CV） | 血常规 |
| `alp` | 碱性磷酸酶 | U/L | 生化 |
| `wbc` | 白细胞计数 | 10⁹/L | 数值等同 10³/μL |
| `age` | 实际年龄 | 岁 | 手填 |

> 单位是本项目最大的坑：若误用美国单位（白蛋白 g/dL、肌酐 mg/dL、血糖 mg/dL）代入，结果会荒谬（数百岁）。视觉 AI 提取时必须连原始单位一起返回，由 `normalize` 函数统一换算到上表单位；前端表单每项指标旁标注单位。

### 4.2 计算步骤

**第 1 步：线性组合得分 xb**

```
xb = -19.907
   - 0.0336  × albumin
   + 0.0095  × creatinine
   + 0.1953  × glucose
   + 0.0954  × ln(crp)          # crp ≤ 0 时 clamp 到 0.01（应对 "<0.x" 报告值）
   - 0.0120  × lymphocyte_pct
   + 0.0268  × mcv
   + 0.3306  × rdw
   + 0.00188 × alp
   + 0.0554  × wbc
   + 0.0804  × age
```

**第 2 步：10 年死亡风险 M（Gompertz 参数化）**

```
γ = 0.0076927
M = 1 - exp( -exp(xb) × (exp(120 × γ) - 1) / γ )
```

**第 3 步：PhenoAge**

```
PhenoAge = 141.50225 + ln( -0.00553 × ln(1 - M) ) / 0.090165
```

**推荐实现（log 空间等价式，避免 M 在浮点中四舍五入为 1 导致溢出）**：

```python
GAMMA = 0.0076927
LOG_SCALE = math.log(0.00553 * math.expm1(120 * GAMMA) / GAMMA)  # ≈ 0.08673
pheno_age = 141.50225 + (xb + LOG_SCALE) / 0.090165
```

**衍生指标**：

- `age_gap = PhenoAge - age`（> 0 偏"老"，< 0 偏"年轻"）
- `phenoage_accel = age_gap`（单人场景直接用差值；学术论文中的 PhenoAgeAccel 为对同龄人群回归的残差，README 与前端文案注明此简化）
- `mortality_10y = M`（展示为百分比）

**解读分档（前端文案）**：

- `|gap| ≤ 2` 岁：生理状态与同龄人基本持平
- `gap > 2` 岁：生理年龄超前，提示多系统老化加速风险，建议改善生活方式并咨询医生
- `gap < -2` 岁：生理年龄优于同龄人

**验证用例（写入单元测试，允许误差 ±0.1 岁）**：
输入 albumin=45, creatinine=80, glucose=5.5, crp=3, lymphocyte_pct=30, mcv=90, rdw=13, alp=80, wbc=6, age=40 → PhenoAge ≈ 37.9。

## 5. API 设计

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/` | 前端单页 |
| GET | `/healthz` | 健康检查，返回 `{"status":"ok"}` |
| POST | `/api/extract` | multipart 上传照片（字段名 `file`），返回提取的结构化指标 |
| POST | `/api/calculate` | body 为 10 项数值，返回计算结果 |
| POST | `/api/diagnose` | 一步到位：上传照片 + 计算（可选便捷接口，内部复用上面两步） |

`/api/extract` 响应示例：

```json
{
  "extracted": {
    "albumin": {"value": 46.2, "unit": "g/L", "raw_text": "白蛋白 46.2 g/L", "confidence": 0.98},
    "creatinine": {"value": 79.0, "unit": "μmol/L", "raw_text": "肌酐 79", "confidence": 0.95},
    "glucose": null,
    "crp": {"value": 0.5, "unit": "mg/L", "raw_text": "C反应蛋白 <1.0", "confidence": 0.6, "censored": true},
    "...": "...",
    "age": null
  },
  "missing": ["glucose", "age"],
  "image_id": "uuid-用于调试"
}
```

`/api/calculate` 响应示例：

```json
{
  "pheno_age": 37.9, "age": 40, "age_gap": -2.1, "mortality_10y": 0.0158,
  "tier": "younger", "interpretation": "……（中文解读文案）",
  "disclaimer": "结果仅供健康参考，不构成医疗诊断建议。"
}
```

校验规则：10 个字段全部为必填数值；范围合理性检查（如 age 1–120、lymphocyte_pct 1–80），越界返回 422 与中文错误信息。

## 6. 视觉 AI 接入要点（`services/vision.py`）

- 使用 OpenAI 兼容 SDK：`base_url` 与 `api_key` 从 `.env` 读取（默认 `https://api.moonshot.cn/v1`，模型名默认 `moonshot-v1-8k-vision-preview`，均可配置切换 provider）。
- 图片以 base64 data URL 随请求发送；限制单张 ≤ 10 MB。
- System prompt 必须要求模型**只输出 JSON**（用 `response_format={"type":"json_object"}`），字段同 §5 的 `extracted` 结构；规定：
  - 识别不到或无法确认的项输出 `null`，禁止编造；
  - 必须连同原始单位一起返回（单位换算在后端完成）；
  - 报告为 "<0.x"、"<x" 时，value 取该阈值的一半并标记 `censored: true`；
  - 报告上通常没有年龄，age 恒为 `null`，由用户手填。
- 解析失败 / API 超时（默认 60 s）时返回 502 与友好中文提示，前端引导用户改用手动录入。
- `.env.example` 提供全部配置项模板，`.env` 加入 `.gitignore`。

## 7. 项目目录结构

```
phenoage-app/
├── README.md                 # 本文件
├── requirements.txt
├── .env.example              # AI_API_KEY / MODEL / BASE_URL / 隧道配置等
├── .gitignore                # .env / uploads/ / __pycache__
├── app/
│   ├── main.py               # FastAPI 入口：挂载路由与 static/
│   ├── config.py             # pydantic-settings 读取 .env
│   ├── schemas.py            # ExtractResponse / CalculateRequest / CalculateResult 等 Pydantic 模型
│   ├── routers/
│   │   └── diagnose.py       # /api/extract、/api/calculate、/api/diagnose
│   ├── services/
│   │   ├── vision.py         # 视觉 AI provider（可切换 Kimi/通义/OpenAI）
│   │   ├── normalize.py      # 单位标准化：原始单位 → §4.1 约定单位
│   │   └── phenoage.py       # §4.2 公式实现（log 空间等价式）+ 解读文案
│   └── static/
│       ├── index.html        # 单页：上传 → 核对表单 → 结果卡片
│       ├── style.css
│       └── app.js            # fetch 调用 /api/*，表单回显与编辑
├── uploads/                  # 上传照片落盘目录（默认不持久化，可配置保留天数）
├── scripts/
│   ├── start.bat             # Windows 启动：uvicorn app.main:app --host 127.0.0.1 --port 8000
│   └── start_tunnel.bat      # 启动 cloudflared 隧道（见 §8）
└── tests/
    ├── test_phenoage.py      # 公式单元测试：§4.2 验证用例 + 边界（crp=0、极端值）
    └── test_api.py           # /api/calculate 参数校验与正常路径
```

## 8. 公网部署（个人电脑作服务器，Windows）

家用宽带通常无公网 IP，采用内网穿透隧道方案；按优先级：

1. **cloudflared（首选）**：官网下载 Windows 版 → `cloudflared.exe tunnel --url http://127.0.0.1:8000` 得到 `https://*.trycloudflare.com` 临时域名（免费、免注册、自动 HTTPS，重启隧道会变域名）。需要固定域名时，注册 Cloudflare 账号 + 自有域名，建 named tunnel 绑定 `xxx.yourdomain.com`。
2. **natapp / cpolar（国内备选）**：国内节点延迟低，免费版有流量/域名限制。
3. **ngrok**：免费版随机域名，国内访问可能不稳。
4. **有公网 IP 或云服务器**：路由器端口映射 / 云服务器跑 frp；注意自行配置 HTTPS 与防火墙。

开机自启：用 Windows"任务计划程序"将 `scripts/start.bat` 与 `scripts/start_tunnel.bat` 设为登录时启动；cloudflared 也可注册为 Windows 服务。README 附分步截图位（Codex 在 `docs/deploy.md` 中以文字步骤说明）。

## 9. 安全与合规（必做）

- 密钥仅存 `.env`；仓库不得含真实 key；所有对外错误信息不泄露内部细节。
- 上传校验：扩展名 + MIME 白名单（jpeg/png/webp）、≤ 10 MB、文件名随机化后落盘、禁止路径穿越。
- 页面与结果卡片固定展示免责声明："本结果由公开公式计算，仅供健康参考，不构成医疗诊断或医疗建议；如有不适请就医。"
- 隐私：照片仅用于本次识别（发送给 AI API 是必要的），默认 24 h 后自动清理 `uploads/`；不记录姓名等身份信息（表单不含身份字段）。
- 可选：`slowapi` 简单限流（如每 IP 每分钟 10 次），防止 key 被盗刷。

## 10. 验收标准

1. `pytest` 全绿：公式用例 PhenoAge ≈ 37.9（±0.1）；crp ≤ 0、极端指标不抛异常。
2. 本地 `uvicorn` 启动后，浏览器走完 §2 全流程（用一份真实/模拟血检报告照片测试 extract → 核对 → calculate）。
3. 隧道启动后，外网手机浏览器（关闭 WiFi）可通过公网链接完成全流程。
4. 无 `.env` 密钥时服务给出清晰启动报错而非堆栈泄露。
5. 前端任何页面可见免责声明。

## 11. 开发任务分解（建议实现顺序）

1. 脚手架：`config.py`、`schemas.py`、`main.py`，跑通 `/healthz`。
2. `services/phenoage.py` + `tests/test_phenoage.py`（先让公式正确）。
3. `services/vision.py` + `normalize.py`，用一张样例报告照片联调 `/api/extract`。
4. `routers/diagnose.py` 三个接口。
5. 前端三个页面状态（上传中 → 表单核对 → 结果卡片）。
6. `scripts/` 启动脚本 + `docs/deploy.md` 隧道部署说明。
7. 按 §10 验收清单逐项核对后交付。

---

参考：Levine ME, et al. "An epigenetic biomarker of aging for lifespan and healthspan." *Aging* 2018;10(4):573-591（PhenoAge 公式出处）。
