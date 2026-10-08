# Minitest 中心服务运行包

该包仅提供管理页面、API 和 MySQL 数据读写，不包含：

- Excel、Excel 生成脚本和旧 Flow。
- Minium、微信开发者工具、小程序项目和 `config.json`。
- 测试用例执行器、截图、历史报告或本机密钥。

## 部署

1. 将包解压到服务器，例如 `/opt/minitest-center`。
2. 执行 `chmod +x install_center.sh start_center.sh`。
3. 执行 `./install_center.sh`，填写生成的 `.env`。
4. 手动验证时执行 `./start_center.sh`，再由 Nginx/Caddy 反向代理到 `127.0.0.1:8765`。
5. 正式持续运行时执行：

   ```bash
   chmod +x install_center_service.sh
   sudo ./install_center_service.sh
   ```

   该脚本会创建并启用 `minitest-center.service`，实现后台运行、异常重启和开机自启。

如果不使用 Nginx/Caddy，需要直接通过 `http://服务器IP:8765` 访问：

```bash
sudo ./install_center_service.sh --host 0.0.0.0
```

`.env` 默认设置 `MINITEST_ENABLE_CENTER_EXECUTION=false`。因此管理页面只能派发到 Windows 执行机，中心服务不会尝试调用本机开发者工具。

MySQL 数据迁移请使用完整数据库备份恢复，不要运行 Excel 导入脚本。

已有数据库启用迭代定时任务前，请执行 `database/migrations/20260930_schedule_iteration_target.sql`；它会把能明确归属迭代的旧任务自动回填，其余旧任务需在页面手动选择迭代。迁移后重启中心服务。

## 定时任务使用

定时任务由中心服务定时检查并执行所选迭代下所有已启用正式用例。执行目标在创建或编辑任务时选择：

- **中心机（当前服务所在电脑）**：适合本机调试。服务和测试项目在同一台电脑时，不需要启动 Agent。
- **远程执行机**：适合正式部署。需要先启动 Windows 执行机 Agent，在线执行机会出现在“执行目标”下拉框中。

### 本机调试

如果当前是在本机启动 `case_editor_server.py` 调试，请确保 `.env` 中允许中心机执行：

```env
MINITEST_ENABLE_CENTER_EXECUTION=true
```

启动服务后打开：

```text
http://127.0.0.1:8765/schedules
```

点击“新建任务”，选择执行迭代，再在“执行目标”中选择“中心机（当前服务所在电脑）”和执行时间即可。此时不需要配置 `MINITEST_AGENT_SERVER`，也不需要启动远程 Agent。

### 远程执行

正式部署时，中心服务通常只负责调度，因此可以设置：

```env
MINITEST_ENABLE_CENTER_EXECUTION=false
MINITEST_ENABLE_REMOTE_AGENTS=true
```

启动并连接 Windows Agent 后，在“执行目标”中选择对应执行机。若列表中没有执行机，请先检查 Agent 是否在线，以及 Agent 的 `MINITEST_AGENT_SERVER` 是否指向当前中心服务地址。

### 页面和 Cron 填写

- `/schedules`：查看任务列表、下次执行时间和最近状态。
- `/schedules/new`：新建定时任务。
- `/schedules/edit?id=<任务ID>`：编辑已有任务。

Cron 使用 5 个字段，顺序是“分 时 日 月 周”。常用示例：

| Cron | 含义 |
| --- | --- |
| `*/5 * * * *` | 每 5 分钟 |
| `0 * * * *` | 每小时整点 |
| `0 9 * * *` | 每天 09:00 |
| `0 9 * * 1-5` | 工作日 09:00 |
| `0 9 1 * *` | 每月 1 日 09:00 |

保存任务后，中心服务每 15 秒检查一次到期任务。服务进程停止时不会执行任务，重新启动后会继续按数据库中的计划检查。
