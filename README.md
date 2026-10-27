# ResearchMail Agent

面向科研人员的 macOS 邮件助理，按里程碑开发。当前为 **M0 / 0.1.0 工程预览**。

已实现原生 PySide6 工作区、六项导航、首次引导、后台数据库初始化、版本化 SQLite
迁移、引导状态持久化、数据库一致性备份和受限事件日志。数据库预建后续功能实体，
但 **M0 尚未连接邮箱、调用模型或发送邮件**。界面中的后续功能明确显示阶段状态。

## 开发运行

需要 Python 3.12 与 uv；Ollama 非启动必需。首次安装开发依赖：

```bash
uv sync --locked --all-groups
uv run --locked researchmail-agent
```

这是开发者运行方式。面向普通用户的独立 `.app` 与开发版 `.dmg` 在 M1 提供；
M0 没有安装包，也未签名或公证。

## 验证

```bash
bash scripts/check.sh
uv run --locked python scripts/gui_smoke.py
uv build --wheel
```

所有测试使用合成数据和临时数据库。GUI 测试默认由检查脚本以 offscreen 平台执行，
smoke 脚本可在本机使用真实 Cocoa 平台，截图在 `artifacts/gui/`，不提交到 Git。
CI 已配置；远端运行结果必须与本地结果分别核验。

## 本地数据

- 数据库：`~/Library/Application Support/ResearchMailAgent/researchmail.sqlite3`
- 备份：同目录下 `backups/`（未加密）
- 日志：`~/Library/Logs/ResearchMailAgent/events.log`

目录权限 0700，数据库与日志权限 0600。SQLite 启用 WAL、外键和参数化数据查询。
迁移在事务内执行并核对历史校验和；损坏、过新或历史异常的数据库会拒绝加载，原文件保留。
不会自动删除数据库或重置用户数据。M0 的日志接口只接受固定事件，不记录邮件、异常正文或凭据。
本地数据库未加密；此版本尚不处理真实科研邮件。

**公共仓库**不应包含授权码、API Key、真实邮件、附件、数据库、日志或签名证书。
未来凭据只通过本机设置写入 macOS Keychain。不要把凭据放入聊天、Issue 或源码。
`.gitignore` 与提交前扫描是辅助措施，提交内容仍须人工审查。

## 里程碑

| 阶段 | 范围 | 状态 |
| --- | --- | --- |
| M0 | 工程、基础 GUI、存储、测试、CI | 本地验收通过；远端状态见阶段交付记录 |
| M1 | 163 Keychain、只读增量同步、开发 DMG | 未开始 |
| M2 | 本地/云端模型、分类、Skills、任务与提醒 | 未开始 |
| M3 | 草稿审批、受控 SMTP、防重复发送 | 未开始 |
| M4 | Developer ID、公证、正式 DMG、Release | 未开始 |

参阅 [架构](docs/architecture.md)、[环境检测](docs/environment.md)、
[设计依据](docs/design.md)、[使用说明](docs/user-guide.md) 和 [M0 报告](docs/M0-report.md)。
