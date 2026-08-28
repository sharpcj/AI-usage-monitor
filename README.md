# AI Usage Monitor

macOS 菜单栏工具，每 5 分钟查询 OpenAI Codex、GLM 和火山方舟 Coding Plan 的剩余额度。

## 启动

```bash
cd ai-usage   # 进入项目目录
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
./run.sh
```

启动命令返回后可以关闭终端。点击菜单中的“立即刷新”可随时查询。

## 配置

配置文件：`~/.config/ai-usage-monitor/config.json`

```json
{
  "refresh_interval": 300,
  "codex": {
    "enabled": true
  },
  "glm": {
    "enabled": false,
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

如需启用，将 `glm.enabled` 改为 `true`，并临时填写 BigModel Coding Plan API Key。首次刷新时程序会把 Key 迁移到 macOS Keychain，并立即清空配置文件中的明文值（与火山方舟凭据的处理方式一致）。

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
4. 临时填入配置中的 `ark.cookie` 和 `ark.web_id`。
5. 点击“立即刷新”。程序会把凭据迁移到 macOS Keychain，并立即清空配置文件中的明文值。

程序和日志不会输出 Cookie、CSRF Token 或 `x-web-id`。

## 显示规则

- 标题示例：`CX 96% · ARK 47%`
- 所有百分比均表示“剩余”而非“已用”
- 一个套餐存在多个额度窗口时，标题显示最低剩余额度
- 详情显示各窗口的进度条和重置倒计时

## 数据来源

| 平台 | 查询方式 | 认证 |
|---|---|---|
| Codex | `codex app-server` → `account/rateLimits/read` | `~/.codex/auth.json` 中现有 Codex 登录状态 |
| GLM | 官方 Coding Plan 用量 API | macOS Keychain 中的 API Key |
| Ark | 优先 `arkcli usage plan`（官方 CLI），回退控制台 `GetCodingPlanUsage` 内部接口 | arkcli SSO 登录态；回退时用 macOS Keychain 中的 Cookie、CSRF 和 Web ID |

Ark 回退路径是非公开控制台接口，页面升级或 Cookie 失效时可能需要更新适配；程序会显示明确错误，不会伪造额度数据。

## 隐私说明

- 所有查询凭据（GLM API Key、火山方舟 Cookie 等）仅存放在本机（macOS Keychain），只发送至对应官方服务，无任何遥测或第三方上报。
- 实时查询失败时，Codex 回退逻辑会在本机读取 `~/.codex/sessions/` 下的会话记录文件（包含你与 Codex 的对话内容）以提取最近一次额度快照，**仅本地解析、绝不上传**。
- 程序不产生日志文件，不会输出 Cookie、CSRF Token 或 API Key。
