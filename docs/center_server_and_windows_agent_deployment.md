# Minitest 中心机服务器部署指南

本文说明将 Minitest 中心服务部署到 Linux 服务器，并让 Windows 执行机通过网络连接中心服务的完整流程。

## 1. 部署后的架构

```text
浏览器
  -> 中心服务 URL
  -> Linux 服务器上的 Minitest 中心机
       -> MySQL
       -> 任务队列

Windows 执行机 Agent
  -> 主动访问中心服务 URL
  -> 领取任务
  -> 在本机启动微信开发者工具和 Minium
  -> 将执行状态、日志和报告回传中心机
```

中心机只负责管理页面、API、MySQL 数据读写和任务派发。微信开发者工具、小程序项目和真正的测试执行必须放在 Windows 执行机上。

## 2. 先说结论：要不要修改 `start_agent.cmd`

**通常不需要修改 `start_agent.cmd`。**

`start_agent.cmd` 只负责启动执行机程序，中心服务地址由执行机目录中的 `.env` 配置：

```env
MINITEST_AGENT_SERVER=http://服务器IP:8765
```

服务器部署后，不能继续使用下面这个地址：

```env
MINITEST_AGENT_SERVER=http://127.0.0.1:8765
```

因为这里的 `127.0.0.1` 指的是 Windows 执行机自己，不是 Linux 服务器。

只有在“中心机和执行机位于同一台 Windows 电脑”时，才使用：

```env
MINITEST_AGENT_SERVER=http://127.0.0.1:8765
```

## 3. `127.0.0.1` 在不同配置中的含义

不要把所有配置里的 `127.0.0.1` 当成同一个地址。它表示“当前程序所在的这台机器”。

| 配置位置 | `127.0.0.1` 表示 | 服务器部署时是否可以继续使用 |
| --- | --- | --- |
| 中心机 `.env` 的 `MINITEST_DB_HOST` | 中心服务器本机 | 可以，前提是 MySQL 也在中心服务器 |
| 中心机启动参数 `--host 127.0.0.1` | 只允许服务器本机访问中心服务 | 只有前面有 Nginx/Caddy 反向代理时可以 |
| 执行机 `.env` 的 `MINITEST_AGENT_SERVER` | Windows 执行机本机 | 服务器和执行机分开时不可以 |
| 执行机 `.env` 的 `MINITEST_DB_HOST` | Windows 执行机本机 | 只有 MySQL 也装在 Windows 执行机时可以 |
| Windows 上的 SSH 隧道端口 | Windows 本机的隧道入口 | 可以，见本文第 8 节 |

如果中心服务直接对外提供 `8765` 端口，监听地址必须是 `0.0.0.0`。`0.0.0.0` 只是服务端监听用的地址，浏览器和执行机不要填写 `http://0.0.0.0:8765`，而应该填写服务器 IP 或域名。

## 4. 服务器准备

以下命令以 Debian/Ubuntu、部署目录 `/opt/minitest-center` 为例。

服务器需要：

- Git
- Python 3
- Python 虚拟环境组件 `venv`
- MySQL，或能访问 MySQL 的网络
- 对外提供中心服务 URL 的网络入口

安装基础依赖：

```bash
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip mysql-client
```

如果 MySQL 也安装在本机，再按服务器实际情况安装并启用 MySQL 服务。

## 5. 首次部署中心机

### 5.1 从 GitHub 拉取代码

```bash
sudo mkdir -p /opt
sudo chown "$USER":"$USER" /opt
git clone https://github.com/LAM1107/minitest-center.git /opt/minitest-center
cd /opt/minitest-center
```

如果仓库是私有仓库，先在服务器配置 SSH Key 或 GitHub Token，再使用对应的 Git 地址。

### 5.2 初始化数据库

首次部署或新建数据库时导入表结构：

```bash
mysql -u root -p < database/minitest_mysql_schema.sql
```

创建中心机数据库账号。请把示例密码替换成真实的强密码：

```sql
CREATE USER IF NOT EXISTS 'minitest_app'@'localhost'
  IDENTIFIED BY '替换为强密码';
GRANT ALL PRIVILEGES ON minitest.* TO 'minitest_app'@'localhost';
FLUSH PRIVILEGES;
```

如果 Windows 执行机需要通过服务器内网地址直接连接 MySQL，则还要：

1. 在 MySQL 中创建允许执行机来源访问的账号。
2. 在服务器防火墙和云安全组中限制 3306 的来源。
3. 优先使用公司内网、VPN 或 SSH 隧道，不要把 3306 无限制暴露到公网。

例如仅用于内网验证时：

```sql
CREATE USER IF NOT EXISTS 'minitest_app'@'%'
  IDENTIFIED BY '替换为强密码';
GRANT ALL PRIVILEGES ON minitest.* TO 'minitest_app'@'%';
FLUSH PRIVILEGES;
```

### 5.3 安装中心机依赖

```bash
cd /opt/minitest-center
chmod +x install_center.sh start_center.sh
./install_center.sh
```

### 5.4 配置中心机 `.env`

复制模板：

```bash
cp central.env.example .env
```

编辑 `/opt/minitest-center/.env`：

```env
MINITEST_STORAGE=mysql
MINITEST_DB_HOST=127.0.0.1
MINITEST_DB_PORT=3306
MINITEST_DB_USER=minitest_app
MINITEST_DB_PASSWORD=服务器MySQL密码
MINITEST_DB_NAME=minitest

# 启用 Windows 远程执行机
MINITEST_ENABLE_REMOTE_AGENTS=true

# 中心服务器不运行微信开发者工具
MINITEST_ENABLE_CENTER_EXECUTION=false

# 根路径部署时留空；如果反向代理挂载在 /minitest，再填写 /minitest
MINITEST_URL_PREFIX=
MINITEST_CORS_ORIGIN=
```

`.env` 包含数据库密码，不能提交 Git，也不能复制到公开位置。

## 6. 启动中心服务

### 6.1 方案 A：直接暴露服务器端口

适用于已经有内网、VPN 或其他网关，不需要 Nginx/Caddy 的场景。

手动启动：

```bash
cd /opt/minitest-center
./.venv/bin/python tools/case_editor_server.py \
  --host 0.0.0.0 \
  --port 8765 \
  --no-open
```

然后放行服务器和云安全组的 TCP `8765`。正式环境建议只允许公司网段、VPN 网段或指定公网 IP。

中心页面：

```text
http://服务器IP:8765/cases
```

Windows 执行机 `.env`：

```env
MINITEST_AGENT_SERVER=http://服务器IP:8765
```

### 6.2 方案 B：Nginx/Caddy 反向代理

这是更适合正式环境的方式。中心 Python 服务只监听服务器本机：

```bash
./.venv/bin/python tools/case_editor_server.py \
  --host 127.0.0.1 \
  --port 8765 \
  --no-open
```

Nginx/Caddy 对外提供 HTTPS，并将请求转发到 `127.0.0.1:8765`。此时浏览器和 Windows 执行机都使用对外域名，例如：

```env
MINITEST_AGENT_SERVER=https://minitest.example.com
```

不要因为 Python 服务监听了 `127.0.0.1`，就把这个地址填写到 Windows 执行机。执行机要填写 Nginx/Caddy 对外可访问的域名。

如果反向代理使用 `/minitest` 作为路径前缀，中心机 `.env` 配置：

```env
MINITEST_URL_PREFIX=/minitest
```

执行机配置：

```env
MINITEST_AGENT_SERVER=https://minitest.example.com/minitest
```

## 7. 配置为 systemd 服务

`start_center.sh` 是前台启动脚本，适合手动验证。正式部署请安装仓库提供的 systemd 服务：

```bash
cd /opt/minitest-center
chmod +x install_center_service.sh
sudo ./install_center_service.sh
```

默认按 Nginx/Caddy 反向代理场景监听 `127.0.0.1:8765`。安装脚本会自动创建：

```text
/etc/systemd/system/minitest-center.service
```

并立即启动、设置开机自启和异常自动重启。

如果不使用反向代理，需要直接通过 `http://服务器IP:8765` 访问：

```bash
sudo ./install_center_service.sh --host 0.0.0.0
```

如果需要指定运行用户或端口：

```bash
sudo ./install_center_service.sh \
  --user ubuntu \
  --host 127.0.0.1 \
  --port 8765
```

管理服务和查看日志：

```bash
sudo systemctl status minitest-center
sudo systemctl restart minitest-center
sudo systemctl stop minitest-center
journalctl -u minitest-center -f
```

检查端口：

```bash
ss -lntp | grep 8765
```

## 8. 执行机访问服务器 MySQL 的方式

当前执行机除了访问中心 API，还会使用 MySQL 读取待执行的用例数据。因此执行机必须能访问与中心机相同的 MySQL 数据库。

### 8.1 通过内网或 VPN 访问

执行机 `.env`：

```env
MINITEST_DB_HOST=服务器MySQL内网IP
MINITEST_DB_PORT=3306
MINITEST_DB_USER=minitest_app
MINITEST_DB_PASSWORD=服务器MySQL密码
MINITEST_DB_NAME=minitest
```

### 8.2 通过 SSH 隧道访问

Windows 执行机打开一个 PowerShell 窗口，保持下面的命令持续运行：

```powershell
ssh -N -L 13306:127.0.0.1:3306 用户名@服务器IP
```

执行机 `.env` 配置：

```env
MINITEST_DB_HOST=127.0.0.1
MINITEST_DB_PORT=13306
```

这里的 `127.0.0.1:13306` 是 Windows 本机的 SSH 隧道入口，实际转发到服务器上的 MySQL。

## 9. GitHub 发布与服务器更新流程

推荐把“中心服务源码”和“执行机 ZIP”分开发布：

- 中心服务代码：GitHub 仓库代码，服务器通过 Git 更新。
- 执行机代码：构建成 ZIP，作为 GitHub Release 附件发布。
- `.env`、`config.json`、数据库密码、报告和截图：只保留在对应机器，不进入 Git。

### 9.1 本地修改中心机代码

在本地完成修改后：

```bash
git status
git diff
```

先做本地验证，例如启动中心服务并打开页面，确认 MySQL 连接、用例保存、任务创建等关键流程正常。

确认没有把 `.env`、密码、报告或虚拟环境加入提交：

```bash
git status --short
```

提交并推送：

```bash
git add path/to/changed/file docs/center_server_and_windows_agent_deployment.md
git commit -m "描述本次修改"
git push origin main
```

把 `path/to/changed/file` 替换成这次实际修改的文件，不要为了方便把整个 `tools/` 或 `framework/` 目录一次性加入提交。

如果团队使用 Pull Request，则先推送分支，审核合并后再部署 `main`。

### 9.2 服务器拉取中心机更新

生产环境建议使用 Git Tag 或明确的 commit，而不是无记录地跟随最新代码。最简单的 `main` 更新方式如下：

```bash
cd /opt/minitest-center
sudo systemctl stop minitest-center

cp .env /tmp/minitest-center.env.backup
git status --short
git pull --ff-only origin main

./.venv/bin/python -m pip install -r requirements-center.txt

sudo systemctl start minitest-center
sudo systemctl status minitest-center
```

注意：

- `git pull` 不会覆盖服务器上的 `.env`。
- `git pull` 不会更新 MySQL 数据。
- 如果有数据库结构变更，必须先执行对应的数据库迁移或经过备份的 SQL。
- 如果服务器 `git status` 显示有本地代码修改，先确认来源，不要直接覆盖。
- 更新失败时可以回到上一个 commit 或 tag，再重启服务。

更稳妥的版本发布流程：

```bash
git tag center-2026.08.19.1
git push origin center-2026.08.19.1
```

服务器部署指定版本：

```bash
cd /opt/minitest-center
sudo systemctl stop minitest-center
git fetch --tags origin
git checkout center-2026.08.19.1
./.venv/bin/python -m pip install -r requirements-center.txt
sudo systemctl start minitest-center
```

## 10. 执行机 ZIP 的发布关系

中心仓库中的 `tools/build_agent_runtime.py` 会从完整执行机源码目录构建 ZIP。默认源码目录是：

```text
D:\project\minitest
```

在本地构建：

```powershell
cd D:\project\minitest-center
python .\tools\build_agent_runtime.py `
  --source-root D:\project\minitest `
  --version 2026.08.19.1
```

输出目录默认是：

```text
D:\project\minitest-center\release
```

构建后得到：

```text
minitest-agent-runtime-2026.08.19.1.zip
minitest-agent-runtime-2026.08.19.1.zip.sha256
```

`release/` 被 `.gitignore` 忽略，ZIP 不会随着服务器 `git pull` 自动出现。推荐：

1. 在 GitHub 创建 Release，例如 `agent-2026.08.19.1`。
2. 上传 ZIP。
3. 同时上传 `.sha256` 校验文件。
4. Windows 执行机从该 Release 下载并安装。

Windows 校验：

```powershell
Get-FileHash .\minitest-agent-runtime-2026.08.19.1.zip -Algorithm SHA256
```

## 11. 上线检查清单

- [ ] 中心服务器可以连接 MySQL。
- [ ] `database/minitest_mysql_schema.sql` 已导入。
- [ ] 中心机 `.env` 的 `MINITEST_ENABLE_REMOTE_AGENTS=true`。
- [ ] 中心机 `.env` 的 `MINITEST_ENABLE_CENTER_EXECUTION=false`。
- [ ] 中心服务监听 `0.0.0.0:8765`，或反向代理已转发到 `127.0.0.1:8765`。
- [ ] 浏览器可以打开中心页面。
- [ ] Windows 执行机可以访问中心服务 URL。
- [ ] 执行机 `MINITEST_AGENT_SERVER` 填的是服务器 IP/域名，不是错误的 `127.0.0.1`。
- [ ] 执行机可以访问同一套 MySQL。
- [ ] 每个执行机的 `MINITEST_AGENT_ID` 唯一。
- [ ] 中心页面的执行位置能看到 Windows Agent 在线。

## 12. 常见问题

### 中心页面能打开，执行机不在线

在 Windows 执行机执行：

```powershell
Test-NetConnection 服务器IP -Port 8765
```

如果使用域名或 HTTPS，检查执行机 `.env` 的 `MINITEST_AGENT_SERVER` 是否完整，是否包含正确的 `/minitest` 前缀。

### 任务一直是 `queued`

检查：

- `start_agent.cmd` 窗口仍在运行。
- 页面选择的是当前 Agent ID。
- 中心机已启用 `MINITEST_ENABLE_REMOTE_AGENTS=true`。
- Agent 与中心机使用同一个 MySQL。
- 数据库中存在 `mt_agents` 和任务相关表。

### Agent 在线但执行时报 MySQL 错误

当前 Agent 不是只调用中心 API，还要从 MySQL 读取用例。检查执行机 `.env` 中的数据库主机、端口、账号、密码和防火墙策略。

### 中心服务更新后页面打不开

检查：

```bash
sudo systemctl status minitest-center
journalctl -u minitest-center -n 100 --no-pager
```

常见原因是 `.env` 未配置、虚拟环境依赖未安装、端口已被占用或反向代理的路径前缀不一致。
