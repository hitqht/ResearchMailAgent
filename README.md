# ResearchMail Agent

面向科研人员的 macOS 邮件助理，按里程碑开发。当前为 **M2 / 0.3.0 AI 邮件管理开发版**。

已实现只读邮箱同步、Keychain、模型配置、隐私路由、分类摘要、证据校验、任务确认与应用内提醒。
支持本机 Ollama 和 OpenAI 兼容的云端 API。服务器邮件始终只读，当前没有 SMTP 发送路径。

## 本机安装开发版

构建产物位于 `dist/ResearchMailAgent-0.3.0-arm64-dev.dmg`（本次交付 arm64）。
打开 DMG，将 ResearchMailAgent.app 拖到 Applications，然后打开应用，无需安装 Python、uv 或 Ollama。
这是 ad-hoc 签名、未公证的本地开发版，不能视为正式 Developer ID 分发版本。
本次已在 macOS 26.1 实机验证；其他系统和另一种 CPU 架构尚未实机验证。

在设置中添加邮箱，默认 `imap.163.com:993`（SSL），填写163客户端授权码并保存到 Keychain。
点击“测试已保存的连接”，在邮件页选择目录，再点击“只读同步”。真实授权码只在本机填写。
默认仅手动同步；可将当前账户的同步周期设为5–1440分钟，定期同步当前选中目录。
每批最多100封；有待同步邮件时可继续点击同步。停止操作会在当前网络请求结束后生效。
超过20 MiB的邮件仅保留 UID 与大小；附件只缓存名称、类型和大小，不下载到文件。

## 模型与科研任务

设置中新增模型，填写配置名称、实际模型名和 Base URL。Ollama 使用本机 IP，例如
`http://127.0.0.1:11434`；需自行运行 Ollama 并安装模型。应用不会自动下载模型。
云端使用 HTTPS，填写提供商的 OpenAI 兼容 Base URL（例如以 `/v1` 结尾）。
支持无认证、Bearer API Key 或 x-api-key，凭据只存 Keychain；未实现 OAuth 登录。
保存后选中模型，点击测试；测试仅发送固定合成提示，不发送邮件。

默认本地优先。默认模型与本地优先可分别配置；本地优先找不到本地模型时会停止。
“审稿与投稿”页可选择当前目录的缓存邮件与模型，点击分析。选择云端后须在弹窗核对
邮件全部发送字段、服务地址和模型，每次明确授权。邮件主题、发件人和附件名也受此限制，
保密等级未知仍按敏感处理。没有任何自动云端故障回退。Ollama 云模型名与远程别名会被阻止。
本机回环服务本身是可信边界，应用不控制其他进程如何实现该服务。

分析结果包含分类、优先级、保密等级、摘要、原文证据、置信度和任务建议。结果是模型建议，
即使引用通过核对，仍需人工判断摘要与分类。明确完整年月日才能形成期限；相对时间、
缺少年份或证据内多个日期保留空值。邀请回复、审稿报告、退修和校样分别标记。

在“待办”确认建议及日期，可人工改正日期，或完成/忽略任务。“今日”显示本地已确认任务日报。
可在设置开启提前 0–30 天的应用内截止提醒；只提醒已确认任务，逾期也会显示。
提醒只在应用运行期间显示，每个任务每日期限每天提示一次；退出后无后台通知服务。
列表当前显示最近100封已分析邮件及最多1000项任务，不支持整库自动批量分析。

项目 `skills/` 是七个版本化科研 Skill 的唯一源文件，通过 wheel 与应用资源打包。
内部工具注册表提供 JSON Schema；模型不能修改任务、草稿、设置、读取其他邮件或调用发送。
模型输出不会被当作工具调用执行。显式用户工具可创建本地 DRAFT，编辑审批界面将在 M3 提供。

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
uv run --locked python scripts/verify_bundle.py --dmg dist/ResearchMailAgent-0.3.0-arm64-dev.dmg
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
| M1 | 163 Keychain、只读增量同步、开发 DMG | 已交付；M2阶段已完成本机真实163只读联调 |
| M2 | 本地/云端模型、分类、Skills、任务与提醒 | 本地验收与构建；远端结果见交付记录 |
| M3 | 草稿审批、受控 SMTP、防重复发送 | 未开始 |
| M4 | Developer ID、公证、正式 DMG、Release | 未开始 |

参阅 [架构](docs/architecture.md)、[环境检测](docs/environment.md)、
[设计依据](docs/design.md)、[使用说明](docs/user-guide.md)、[M0 报告](docs/M0-report.md)、
[M1 报告](docs/M1-report.md) 和 [M2 报告](docs/M2-report.md)。
