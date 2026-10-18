# 部署说明：把 PhenoAge 部署到公网（个人 Windows 电脑作服务器）

本教程按「先跑起来 → 临时公网链接 → 固定域名（可选，需购买域名）」的顺序展开。

## 0. 前置条件

- 安装 Python 3.11（或更高）：<https://www.python.org/downloads/>。安装时勾选
  “Add Python to PATH”。
- 一个 Moonshot（Kimi）API Key：<https://platform.moonshot.cn/> 注册后在控制台创建。

## 1. 安装依赖并启动服务

在项目根目录（本 README 所在目录）打开 PowerShell 或 CMD：

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

用记事本打开 `.env`，填入：

```ini
AI_API_KEY=sk-你的真实Key
```

然后启动后端：

```bat
scripts\start.bat
```

看到 “Uvicorn running on http://127.0.0.1:8000” 后，浏览器打开
`http://127.0.0.1:8000` 应能走完整流程。健康检查：
`http://127.0.0.1:8000/healthz`。

## 2. 用 cloudflared 获得临时公网链接（免费、免注册、免域名）

1. 下载 Windows 版 `cloudflared.exe`：
   <https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/>
2. 把 `cloudflared.exe` 放到 `scripts\` 目录（或加入 PATH）。
3. 保持 `start.bat` 运行，另开一个 CMD 运行：

   ```bat
   scripts\start_tunnel.bat
   ```

4. 终端会打印一个 `https://xxxx.trycloudflare.com` 地址，用手机（关闭 WiFi、
   走移动数据）打开即可访问。

缺点：该地址是临时的，每次重启隧道都会变化。需要稳定地址请看第 3 步。

## 3. 固定域名（需要先购买域名，下面手把手教你）

### 3.1 怎么买域名（以 Cloudflare Registrar 为例，推荐）

推荐用 Cloudflare 官方注册商，理由：成本价、无加价、无隐藏续费，而且后面
绑隧道 + 自动 HTTPS 全程在同一个后台完成，最省事。

1. 注册 Cloudflare 账号：<https://dash.cloudflare.com/sign-up>
2. 在首页点击 “Register domain”（注册域名）。
3. 搜索你想要的名字，例如 `yourname.com`、`yourname.cn`、`yourname.top`。
   系统会列出可注册的域名和价格。提示：`.com` 通用性强、辨识度高；`.cn`
   等国内后缀在部分注册商处需要实名认证。
4. 选择域名，点 “Purchase”（购买），按提示付款。首年通常几十到一百多元，
   之后按年续费（到期不续费域名会被释放，记得开自动续费）。
5. 付款后域名默认托管在 Cloudflare DNS（免配置，最省事）。

> 如果更喜欢国内注册商，也可以在阿里云（万网）、腾讯云购买，流程类似：
> 搜索域名 → 实名认证 → 付款 → 完成后到 DNS 解析控制台。之后仍可把域名
> 的 NS（域名服务器）改成 Cloudflare 的，再回到 Cloudflare 绑定隧道。
> 通过 Cloudflare Tunnel 对外提供服务、流量走 Cloudflare 边缘节点，
> 不需要国内服务器备案（ICP 备案只针对部署在大陆服务器且用大陆访问的场景）。

### 3.2 在 Cloudflare 创建命名隧道并绑定域名

1. 打开 Zero Trust 控制台：<https://one.dash.cloudflare.com/>
2. 左侧依次进入 Networks → Tunnels → Create a tunnel。
3. 选择 Cloudflared，命名（如 `phenoage`），按页面提示把安装命令在本机执行
   （或直接使用你已下载的 `cloudflared.exe` 运行 `cloudflared tunnel login`）。
4. 创建后进入该隧道的 Public Hostnames 配置：
   - Subdomain：填 `phenoage`（最终是 `phenoage.yourdomain.com`）
   - Domain：选你刚买的域名
   - Service：选 `HTTP`，URL 填 `127.0.0.1:8000`
5. 保存后，在本机运行隧道：

   ```bat
   cloudflared tunnel run phenoage
   ```

6. 等 DNS 生效（通常几分钟），访问 `https://phenoage.yourdomain.com` 即可。
   Cloudflare 自动签发并续期 HTTPS 证书，无需手动配置。

### 3.3 把域名换成其他注册商购买时怎么接

如果域名是在阿里云/腾讯云买的，只需把域名的 DNS 服务器（NS）改成 Cloudflare
分配的 NS：先在 Cloudflare 后台 “Add a site” 添加域名，它会给出两条 NS 地址，
回到原注册商把 NS 改成这两条，等生效后即可继续用第 3.2 节绑定隧道。

## 4. 开机自启（可选）

用 Windows “任务计划程序” 把两个脚本设为登录时启动：

1. 打开 “任务计划程序” → 创建基本任务。
2. 触发器选 “当前用户登录时”。
3. 操作选 “启动程序”，分别指向 `scripts\start.bat` 和 `scripts\start_tunnel.bat`
   （各建一个任务，启动目录填脚本所在目录）。
4. 勾选 “使用最高权限运行” 视需要而定，一般不必。

也可以把 cloudflared 注册为 Windows 服务，见 Cloudflare 官方文档
“Run as a service”。

## 5. 安全与隐私提示

- 密钥只放 `.env`，不要提交到 Git。
- 默认仅监听 `127.0.0.1`，公网流量只能通过 cloudflared 隧道进入，不直接暴露端口。
- 照片默认 24 小时后自动清理；接口不收集姓名等身份信息。
- 如需防 API Key 被盗刷，可自行加 `slowapi` 做每 IP 限流（README §9 可选项）。
