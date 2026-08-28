# AI Usage Monitor

跨平台托盘工具（macOS / Windows / Linux），定时查询 OpenAI Codex、GLM 和火山方舟 Coding Plan 的剩余额度。

- **macOS**：菜单栏应用（rumps），标题常显各平台剩余百分比
- **Windows**：系统托盘（pystray），托盘图标颜色表示状态，左键点击弹出详情浮窗（tkinter）
- **Linux**：应用指示器（AyatanaAppIndicator），label 常显标题，下拉菜单查看详情

## 启动

统一入口 `start.py`（自动创建虚拟环境、检测并安装依赖，然后启动）：

- **macOS / Linux**：`python3 start.py`（前台运行）
- **Windows**：双击 `start.bat`，或 `python start.py`

macOS / Linux 也可以后台启动（启动后可关闭终端，自动防重复启动）：

```bash
./run.sh
```

Linux（Ubuntu/Debian）首次使用需安装系统包（GUI 后端依赖，无法自动安装）：

```bash
sudo apt install python3-gi gir1.2-ayatanaappindicator3-0.1 \
                 gir1.2-gtk-3.0 gir1.2-notify-0.7
```

Linux 如需登录自启动，可创建 systemd 用户服务 `~/.config/systemd/user/ai-usage-monitor.service`：

```ini
[Unit]
Description=AI Usage Monitor

[Service]
ExecStart=%h/ai-usage/.venv/bin/python %h/ai-usage/app.py
Restart=on-failure

[Install]
WantedBy=graphical-session.target
```

```bash
systemctl --user enable --now ai-usage-monitor
```

唯一前提：系统已安装 Python 3.8+（Windows 需自行安装 [Python](https://www.python.org/downloads/)）。运行后点击菜单中的“立即刷新”可随时查询。

## 配置

配置文件：`~/.config/ai-usage-monitor/config.json`

```json
{
  "refresh_interval": 300,
  "codex": {
    "enabled": true
  },
  "glm": {
    "enabled": true,
    "api_key": "",
    "base_url": "https://open.bigmodel.cn"
  },
  "ark": {
    "enabled": true,
    "cookie": "",
    "web_id": ""
  }
}
```

配置文件目录权限为 `0700`，文件权限为 `0600`。

### Codex

通过 Codex CLI 的 `app-server` 实时查询 ChatGPT 服务端额度，无需额外配置。程序自动查找系统中已安装的 Codex CLI（IDE 缓存、PATH 等）。菜单会显示：

- 套餐周期剩余百分比
- 重置时间
- 超额额度余额
- 数据源“服务端实时”

只有实时查询失败时才退回本地 rollout 快照，并明确显示警告。

### GLM

如需启用，将 `glm.enabled` 改为 `true`，并临时填写 BigModel Coding Plan API Key。首次刷新时程序会把 Key 迁移到系统凭据存储（macOS Keychain / Windows 凭据管理器 / Linux Secret Service），并立即清空配置文件中的明文值（与火山方舟凭据的处理方式一致）。

### 火山方舟

程序优先使用官方 [Ark CLI](https://github.com/volcengine/ark-cli) 查询（推荐，无需手动抓 Cookie）：

```bash
npm install -g @volcengine/ark-cli
arkcli auth login volc-sso   # 浏览器授权一次，之后凭据自动续期
```

未安装 arkcli 或未登录时，自动回退到控制台 Cookie 方式（Cookie 过期后需要重新获取）：

1. 登录火山方舟控制台。
2. 在开发者工具 Network 中找到 `GetCodingPlanUsage`。
3. 从请求中取得完整 Cookie 和 `x-web-id`。
4. 临时填入配置中的 `ark.cookie` 和 `ark.web_id`，点击“立即刷新”；或直接复制请求的 cURL（右键 → Copy as cURL）后运行 `./update-ark.sh`。
5. 程序会把凭据迁移到系统凭据存储，并立即清空配置文件中的明文值。

程序和日志不会输出 Cookie、CSRF Token 或 `x-web-id`。

## 显示规则

- 标题示例：`CX 96% · GLM 23%· ARK 45%`（macOS 菜单栏 / Linux label 常显；Windows 显示在托盘悬停提示中）
- Windows 无常显标题：托盘图标颜色表示整体状态（绿/橙/红），左键点击弹出详情浮窗
- 所有百分比均表示“剩余”而非“已用”
- 一个套餐存在多个额度窗口时，标题显示最低剩余额度
- 详情显示各窗口的进度条和重置倒计时

## 数据来源

| 平台 | 查询方式 | 认证 | 凭据存放 |
|---|---|---|---|
| Codex | `codex app-server` → `account/rateLimits/read` | `~/.codex/auth.json` 中现有 Codex 登录状态 | — |
| GLM | 官方 Coding Plan 用量 API | API Key（Bearer） | 系统凭据存储* |
| Ark | 优先 `arkcli usage plan`（官方 CLI），回退控制台 `GetCodingPlanUsage` 内部接口 | arkcli SSO 登录态；回退时用 Cookie、CSRF 和 Web ID | 系统凭据存储* |

\* 系统凭据存储：macOS Keychain / Windows 凭据管理器 / Linux Secret Service（通过 `keyring` 库自动选择）。

Ark 回退路径是非公开控制台接口，页面升级或 Cookie 失效时可能需要更新适配；程序会显示明确错误，不会伪造额度数据。

## 隐私说明

- 所有查询凭据（GLM API Key、火山方舟 Cookie 等）仅存放在本机系统凭据存储（macOS Keychain / Windows 凭据管理器 / Linux Secret Service），只发送至对应官方服务，无任何遥测或第三方上报。
- 实时查询失败时，Codex 回退逻辑会在本机读取 `~/.codex/sessions/` 下的会话记录文件（包含你与 Codex 的对话内容）以提取最近一次额度快照，**仅本地解析、绝不上传**。
- 程序不产生日志文件，不会输出 Cookie、CSRF Token 或 API Key。

## 开发与测试

```bash
python -m unittest discover -s tests -v
```

- 业务逻辑（`core.py`）、providers、凭据存储的测试在三平台均可运行
- macOS UI 测试仅在 macOS 上执行（其余平台自动跳过）
- CI 在 macOS / Ubuntu / Windows 三平台矩阵上自动运行（`.github/workflows/tests.yml`）
