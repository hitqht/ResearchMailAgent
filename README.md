# ResearchMail Agent

面向科研人员的 macOS 邮件助理，按里程碑开发。当前为 **M1 / 0.2.0 只读邮箱开发版**。

已实现邮箱账户配置、macOS Keychain、SSL IMAP 连接与目录读取、UID 增量同步、MIME
解析、纯文本邮件浏览、搜索、进度与停止同步，以及本地数据库迁移和备份。
**M1 没有模型调用或 SMTP 路径**，不会发送、删除、移动或归档服务器邮件。

## 本机安装开发版

构建产物位于 `dist/ResearchMailAgent-0.2.0-arm64-dev.dmg`（本次交付 arm64）。
打开 DMG，将 ResearchMailAgent.app 拖到 Applications，然后打开应用，无需安装 Python、uv 或 Ollama。
这是 ad-hoc 签名、未公证的本地开发版，不能视为正式 Developer ID 分发版本。
本次已在 macOS 26.1 实机验证；其他系统和另一种 CPU 架构尚未实机验证。

在设置中添加邮箱，默认 `imap.163.com:993`（SSL），填写163客户端授权码并保存到 Keychain。
点击“测试已保存的连接”，在邮件页选择目录，再点击“只读同步”。真实授权码只在本机填写。
默认仅手动同步；可将当前账户的同步周期设为5–1440分钟，定期同步当前选中目录。
每批最多100封；有待同步邮件时可继续点击同步。停止操作会在当前网络请求结束后生效。
超过20 MiB的邮件仅保留 UID 与大小；附件只缓存名称、类型和大小，不下载到文件。

## 开发运行

需要 Python 3.12 与 uv；Ollama 非启动必需。首次安装开发依赖：

```bash
uv sync --locked --all-groups
uv run --locked researchmail-agent
```

以上是开发者运行方式；普通用户直接启动已构建的 `.app`。

## 验证

```bash
bash scripts/check.sh
uv run --locked python scripts/gui_smoke.py
uv build --wheel
bash scripts/build_dmg.sh
uv run --locked python scripts/verify_bundle.py --dmg dist/ResearchMailAgent-0.2.0-arm64-dev.dmg
```

所有测试使用合成数据和临时数据库。GUI 测试默认由检查脚本以 offscreen 平台执行，
smoke 脚本可在本机使用真实 Cocoa 平台，截图在 `artifacts/gui/`，不提交到 Git。
CI 包含检查、GUI、wheel、独立应用、DMG 构建与复制安装验证。远端结果与本地分别核验。
安装验证复制到临时 Applications 目录，不覆盖系统已有应用；系统 Applications 安装由用户拖拽完成。

## 本地数据

- 数据库：`~/Library/Application Support/ResearchMailAgent/researchmail.sqlite3`
- 备份：同目录下 `backups/`（未加密）
- 日志：`~/Library/Logs/ResearchMailAgent/events.log`

目录权限 0700，数据库与日志权限 0600。SQLite 启用 WAL、外键和参数化数据查询。
迁移在事务内执行并核对历史校验和；损坏、过新或历史异常的数据库会拒绝加载，原文件保留。
不会自动删除数据库或重置用户数据。M0 的日志接口只接受固定事件，不记录邮件、异常正文或凭据。
本地数据库与备份未加密，权限保护不能替代磁盘加密。凭据仅存储在 macOS Keychain，
数据库只有随机引用。Keychain 拒绝访问时停止操作，不回退到明文存储。
UIDVALIDITY 变化会保留旧缓存，当前邮件列表只显示新的目录代次。
已有缓存的账户暂不支持更换邮箱地址或 IMAP 服务器，避免跨邮箱混用 UID。

**公共仓库**不应包含授权码、API Key、真实邮件、附件、数据库、日志或签名证书。
凭据只通过本机设置写入 macOS Keychain。不要把凭据放入聊天、Issue 或源码。
`.gitignore` 与提交前扫描是辅助措施，提交内容仍须人工审查。

## 里程碑

| 阶段 | 范围 | 状态 |
| --- | --- | --- |
| M0 | 工程、基础 GUI、存储、测试、CI | 本地验收通过；远端状态见阶段交付记录 |
| M1 | 163 Keychain、只读增量同步、开发 DMG | 本地开发交付；真实163账户联调需本机配置 |
| M2 | 本地/云端模型、分类、Skills、任务与提醒 | 未开始 |
| M3 | 草稿审批、受控 SMTP、防重复发送 | 未开始 |
| M4 | Developer ID、公证、正式 DMG、Release | 未开始 |

参阅 [架构](docs/architecture.md)、[环境检测](docs/environment.md)、
[设计依据](docs/design.md)、[使用说明](docs/user-guide.md)、[M0 报告](docs/M0-report.md)
和 [M1 报告](docs/M1-report.md)。
