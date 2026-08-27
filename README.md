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
