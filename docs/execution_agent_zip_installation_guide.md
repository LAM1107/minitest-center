# Windows 执行机 ZIP 安装指南

本文说明如何安装 `minitest-agent-runtime-版本号.zip`，并让 Windows 执行机连接中心服务、在本机调用微信开发者工具执行测试。

执行机不是 Web 服务，不监听 `8766` 或其他 HTTP 端口。它会主动轮询中心服务，所以一般不需要给执行机配置入站端口。

## 1. 执行机的职责

Windows 执行机需要负责：

- 运行 Agent 进程。
- 连接中心服务并领取任务。
- 在本机启动 Minium 和微信开发者工具。
- 读取本机小程序项目。
- 将执行状态、日志和报告回传中心服务。

中心服务部署在哪里，执行机就通过网络访问哪里的中心服务。

## 2. 地址先搞清楚

### 2.1 本地联调

中心服务和执行机在同一台 Windows 电脑时：

```text
浏览器  -> http://127.0.0.1:8765/cases
Agent   -> http://127.0.0.1:8765
MySQL   -> 127.0.0.1:3306
```

执行机 `.env`：

```env
MINITEST_AGENT_SERVER=http://127.0.0.1:8765
```

### 2.2 中心机在服务器

中心服务和 Windows 执行机分开时：

```text
浏览器  -> https://中心域名/cases
Agent   -> https://中心域名
MySQL   -> 服务器内网 IP:3306，或本机 SSH 隧道
```

执行机 `.env` 示例：

```env
MINITEST_AGENT_SERVER=https://minitest.example.com
```

或者中心机直接开放 `8765` 端口：

```env
MINITEST_AGENT_SERVER=http://服务器IP:8765
```

**不要修改 `start_agent.cmd` 来写死服务器地址。** `start_agent.cmd` 只负责启动 Agent，中心地址应该配置在 `.env` 的 `MINITEST_AGENT_SERVER` 中。以后更换服务器，只改 `.env` 即可。

### 2.3 `127.0.0.1` 的判断规则

`127.0.0.1` 永远代表“当前这台机器”：

- 写在 Agent 的 `MINITEST_AGENT_SERVER` 中：代表 Windows 执行机自己。
- 写在 Agent 的 `MINITEST_DB_HOST` 中：代表 Windows 执行机自己。
- 写在中心机的 `MINITEST_DB_HOST` 中：代表中心服务器自己。
- 写在服务器启动参数 `--host` 中：代表限制中心服务只接受服务器本机请求。

因此，服务器部署场景下 Agent 的中心地址不能写 `127.0.0.1`，除非使用的是 Windows 本机 SSH 隧道或中心服务确实运行在同一台 Windows 电脑上。

## 3. 安装前准备

Windows 执行机需要具备：

- Python 3.12。
- 微信开发者工具。
- 可正常打开的小程序项目。
- 可以访问中心服务 URL 的网络。
- 可以访问同一套 MySQL 的网络，或已经建立 SSH 隧道/VPN。

中心机 `.env` 至少需要：

```env
MINITEST_ENABLE_REMOTE_AGENTS=true
MINITEST_ENABLE_CENTER_EXECUTION=false
```

## 4. 解压 ZIP

建议每个版本使用独立目录，不要直接覆盖正在运行的旧版本：

```text
D:\minitest-agent-runtime-2026.08.19.1\
```

解压后，目录中至少应包含：

```text
agent.env.example
config.example.json
install_agent.ps1
start_agent.cmd
requirements.txt
run.py
tools\minitest_agent.py
framework\
cases\
runtime_version.json
README.md
INSTALLATION_GUIDE.md
```

安装脚本的正确文件名是：

```text
install_agent.ps1
```

## 5. 首次安装

在 ZIP 解压目录打开 PowerShell：

```powershell
cd D:\minitest-agent-runtime-2026.08.19.1
Set-ExecutionPolicy -Scope Process Bypass
.\install_agent.ps1
```

安装脚本会：

1. 检查 Python 3.12。
2. 从 `agent.env.example` 创建 `.env`。
3. 从 `config.example.json` 创建 `config.json`。
4. 创建 `.venv` 虚拟环境。
5. 安装 `requirements.txt` 中的依赖。

脚本执行成功后，先不要马上启动 Agent，继续完成第 6 节和第 7 节配置。

### 5.1 PowerShell 5.1 编码问题

新版 ZIP 中的 `install_agent.ps1` 使用 UTF-8 BOM，兼容 Windows PowerShell 5.1 和 PowerShell 7。

如果旧 ZIP 运行时出现以下错误：

```text
表达式或语句中包含意外的标记
语句块或类型定义中缺少右“}”
FullyQualifiedErrorId : UnexpectedToken
```

可能是旧脚本没有 BOM，先执行：

```powershell
$path = (Resolve-Path ".\install_agent.ps1").Path
$content = [System.IO.File]::ReadAllText(
    $path,
    [System.Text.Encoding]::UTF8
)
$utf8Bom = New-Object System.Text.UTF8Encoding($true)
[System.IO.File]::WriteAllText(
    $path,
    $content,
    $utf8Bom
)
```

然后重新运行：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\install_agent.ps1
```

## 6. 配置执行机 `.env`

安装脚本生成 `.env` 后，按部署场景修改。

### 6.1 与中心机同机

```env
MINITEST_STORAGE=mysql
MINITEST_DB_HOST=127.0.0.1
MINITEST_DB_PORT=3306
MINITEST_DB_USER=minitest_app
MINITEST_DB_PASSWORD=本机MySQL密码
MINITEST_DB_NAME=minitest

MINITEST_AGENT_SERVER=http://127.0.0.1:8765
MINITEST_AGENT_ID=local-win-agent-01
MINITEST_AGENT_NAME=本机执行机
MINITEST_AGENT_POLL_INTERVAL=3
```

### 6.2 中心机在服务器

通过内网或 VPN 访问服务器 MySQL：

```env
MINITEST_STORAGE=mysql
MINITEST_DB_HOST=服务器MySQL内网IP
MINITEST_DB_PORT=3306
MINITEST_DB_USER=minitest_app
MINITEST_DB_PASSWORD=服务器MySQL密码
MINITEST_DB_NAME=minitest

MINITEST_AGENT_SERVER=http://服务器IP:8765
MINITEST_AGENT_ID=win-agent-01
MINITEST_AGENT_NAME=测试人员电脑-执行机01
MINITEST_AGENT_POLL_INTERVAL=3
```

如果中心服务通过 HTTPS 域名访问：

```env
MINITEST_AGENT_SERVER=https://minitest.example.com
```

如果中心服务挂载在 `/minitest`：

```env
MINITEST_AGENT_SERVER=https://minitest.example.com/minitest
```

每台 Windows 执行机的 `MINITEST_AGENT_ID` 必须唯一，例如：

```text
win-agent-01
win-agent-02
win-agent-03
```

### 6.3 通过 SSH 隧道访问服务器 MySQL

如果不开放服务器 3306，可以在 Windows 单独打开一个 PowerShell 窗口：

```powershell
ssh -N -L 13306:127.0.0.1:3306 用户名@服务器IP
```

保持该窗口运行，执行机 `.env` 改为：

```env
MINITEST_DB_HOST=127.0.0.1
MINITEST_DB_PORT=13306
```

这里 `127.0.0.1:13306` 是 Windows 本机的 SSH 隧道入口，实际连接的是服务器 MySQL。

`.env` 有数据库密码，不要提交 Git 或发送到群聊。

## 7. 配置本机 `config.json`

填写 Windows 上真实存在的路径：

```json
{
  "project_path": "D:\\mini-program\\stable",
  "dev_tool_path": "C:\\Program Files (x86)\\Tencent\\微信web开发者工具\\cli.bat",
  "debug_mode": "debug",
  "enable_network_panel": true,
  "enable_app_log": true
}
```

字段说明：

- `project_path`：小程序项目根目录。
- `dev_tool_path`：微信开发者工具的 `cli.bat`。
- `debug_mode`、网络面板和 App 日志：按当前测试需要配置。

检查路径：

```powershell
Test-Path "D:\mini-program\stable"
Test-Path "C:\Program Files (x86)\Tencent\微信web开发者工具\cli.bat"
```

路径不存在、微信开发者工具未安装或未登录时，任务会在执行机失败。

## 8. 启动与验证

先启动中心服务，再启动 Agent。

如果中心机与执行机同机，中心服务窗口：

```powershell
cd D:\project\minitest-center
.\start_center.cmd
```

执行机窗口：

```powershell
cd D:\minitest-agent-runtime-2026.08.19.1
.\start_agent.cmd
```

服务器部署场景下，不需要在 Windows 再启动中心服务，只启动执行机 Agent。

正常启动后应看到类似日志：

```text
[AGENT] agent_id=win-agent-01 agent_ip=... server=http://服务器IP:8765
```

这行日志中的 `server=` 就是 Agent 实际使用的中心地址。它应该是服务器 IP、服务器域名或本机联调地址。

验证中心页面：

1. 打开 `http://服务器IP:8765/cases`，或打开正式域名。
2. 进入用例或需求迭代页面。
3. 在“执行位置”中看到 `win-agent-01`。
4. 选择该执行机。
5. 先执行一个简单用例，再执行完整迭代。

验证网络：

```powershell
Test-NetConnection 服务器IP -Port 8765
```

如果使用 HTTPS 域名，应同时确认域名解析、证书和反向代理路径正确。

## 9. 运行限制

- 同一个 Agent 目录不要重复启动多个 `start_agent.cmd`。
- 执行期间保持 Windows 登录，避免锁屏、休眠或关机。
- 不要同时手动操作同一个小程序项目和微信开发者工具。
- 中心机和执行机必须使用同一个 MySQL 数据库。
- 执行机报告、截图和日志主要保存在执行机本地；中心页面保存回传的执行结果和报告 HTML 快照。

## 10. 常见问题

### `start_agent.cmd` 需要改成服务器 IP 吗？

不需要。地址在 `.env`：

```env
MINITEST_AGENT_SERVER=http://服务器IP:8765
```

只有在你想改变启动参数、Python 路径或日志行为时，才需要修改 `start_agent.cmd`。

### 管理页面没有显示执行机

按顺序检查：

1. `start_agent.cmd` 窗口是否仍在运行。
2. `.env` 是否配置了 `MINITEST_AGENT_SERVER`。
3. `MINITEST_AGENT_SERVER` 是否能从 Windows 访问。
4. `MINITEST_AGENT_ID` 是否为空或与其他执行机重复。
5. 中心机是否配置 `MINITEST_ENABLE_REMOTE_AGENTS=true`。
6. 中心机和执行机是否连接同一个 MySQL。
7. 数据库中是否存在 `mt_agents` 表。

### 任务一直是 `queued`

确认页面选择的是当前在线 Agent，并查看 Agent 窗口是否持续发送心跳和领取任务。也要确认中心服务没有连接错误。

### MySQL `Access denied`

`MINITEST_DB_USER` 是 MySQL 用户名，`MINITEST_DB_HOST` 才是主机地址。例如：

```env
MINITEST_DB_HOST=服务器MySQL内网IP
MINITEST_DB_USER=minitest_app
```

### 找不到 Python 或 pip 安装失败

检查：

```powershell
python --version
py -3.12 --version
```

如果虚拟环境已经创建，可以单独重试：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## 11. 更新执行机 ZIP

执行机更新不要直接覆盖正在运行的旧目录，建议并行保留旧版本，方便回退。

### 11.1 开发者构建新 ZIP

在本地中心仓库执行：

```powershell
cd D:\project\minitest-center
python .\tools\build_agent_runtime.py `
  --source-root D:\project\minitest `
  --version 2026.08.19.1
```

把生成的以下文件上传到 GitHub Release：

```text
minitest-agent-runtime-2026.08.19.1.zip
minitest-agent-runtime-2026.08.19.1.zip.sha256
```

`release/` 已被 `.gitignore` 忽略，不能依赖服务器 `git pull` 获取 ZIP。

### 11.2 Windows 执行机升级

1. 关闭旧版本的 `start_agent.cmd`。
2. 下载新 ZIP，并解压到新的版本目录。
3. 将旧目录的 `.env` 和 `config.json` 复制到新目录。
4. 在新目录运行 `install_agent.ps1`。
5. 检查 `.env` 和 `config.json` 中的路径、服务器地址和 Agent ID。
6. 启动新的 `start_agent.cmd`。
7. 在中心页面确认新 Agent 在线。
8. 确认可以执行一个简单用例后，再删除旧目录。

不要复制旧目录的 `.venv`，让新版本重新创建虚拟环境并安装依赖。

## 12. 本地开发、GitHub 和服务器的推荐流程

### 12.1 只修改中心服务代码

```text
本地修改中心代码
  -> 本地启动并验证
  -> git commit
  -> git push GitHub
  -> 服务器 git pull 或 checkout 指定 tag
  -> 安装依赖
  -> 重启中心服务
```

这种情况通常不需要重新安装 Windows 执行机 ZIP。

### 12.2 修改执行机代码

```text
本地修改完整执行机源码
  -> 本地验证 Agent
  -> 重新构建执行机 ZIP
  -> 上传 GitHub Release
  -> Windows 执行机下载新 ZIP
  -> 复制 .env 和 config.json
  -> 安装并启动新版本
```

如果执行机 API 协议或数据库结构也变了，应先确认中心机和执行机版本兼容，再安排更新顺序。

### 12.3 修改数据库结构

```text
备份数据库
  -> 执行迁移 SQL
  -> 更新中心服务
  -> 更新执行机
  -> 验证保存、派发、执行和报告
```

`git pull` 不会自动修改服务器 `.env`，也不会自动执行数据库迁移。

## 13. 执行机私密文件

以下文件只保留在 Windows 执行机本地：

```text
.env
config.json
.venv/
outputs/
reports/
final_report/
截图
日志
数据库密码
```
