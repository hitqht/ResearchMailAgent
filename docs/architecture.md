# ResearchMail 分层架构

## M2 增量

`gui/ai_widgets.py` → `gui/ai_controller.py` → `services/ai_service.py` →
`llm/{models,providers,evidence}.py` / `storage/ai_repository.py` / `research_skills`。
UI 仅在线程池外显示快照和授权预览；模型网络、存储与 Keychain 均在 Worker 执行。
`model_configs` 仅保存受校验配置和 Keychain 随机引用；模型服务名独立于邮箱服务名。
新凭据先写 Keychain，数据库失败清理新条目，提交成功后清理旧条目。
迁移4为 M1 数据库追加模型、偏好与分析来源字段，不修改已应用的迁移。

AIService 是唯一邮件模型路由入口。本地优先不允许无本地配置时默认选择云端；显式选择
云端仍须取得逐封授权。授权绑定消息ID、实际发送字段 SHA256、模型ID及配置，五分钟失效，
单次消费；修改模型配置清空授权。模型标签及返回的保密等级不能授予云端权限。
Ollama 只接受数值回环地址，不使用系统代理、不跟随重定向；调用 /api/show 后检查远程元数据，
不允许把云端别名作为本地模型。回环服务与主机仍属于用户可信运行环境。
云端 API 仅用 HTTPS；应用不访问网页或抽取其他应用 Token。测试模型发送固定合成内容。

所有模型结果通过 Pydantic extra=forbid；引用需与主题/发件人/正文的连续原文匹配。
日期仅从引用中明确完整年月日生成，且引用中只有一个日期；期限类型与分类一致。
摘要语义、任务合理性不能被字符串检查证明，GUI 始终要求人工确认任务。
分析与建议任务同事务落库；同邮件/类型/标题/日期去重，保留已确认任务状态。
原始模型回复及异常响应不记入日志；审计仅记录固定操作名、实体ID与结果码。

七个根目录 Skill 是包资源的唯一来源。加载时验证名称/语义版本，分析记录规则版本与
完整系统指令 SHA256，支持追溯。daily-digest 使用确定性本地代码，不调用模型。
`tools/registry.py` 是进程内 JSON Schema 注册表，没有 HTTP 监听器。受信任调用方提供 origin
与消息范围；模型最多读取已授予的同封邮件，任何模型写操作、读其他邮件、Shell 或发送均拒绝。
模型分析链不执行工具调用；显式用户工具只创建本地任务或 DRAFT。SMTP 留至 M3。

## 保留的 M0/M1 基线


## M1 增量架构

`gui/mail_widgets.py` → `gui/mail_controller.py` → `services/mail_service.py` →
`mail/imap.py` / `storage/mail_repository.py` / `security/credentials.py`。
控制器将所有存储、Keychain 与网络操作放入 Worker，UI 只接收快照、进度和固定错误码。
服务层串行化账户和同步操作，连接失败按固定次数重试，每封邮件连同游标在一个事务内提交。
只读适配器仅暴露 LIST、SELECT(readonly)、UID SEARCH/FETCH 与 LOGOUT，没有服务器写入接口。
MIME 与 IMAP literal 均有大小限制，HTML 只转文本，QPlainTextEdit 不执行脚本、打开链接或请求远程图片。

账户连接身份在有缓存后不可更换；UIDVALIDITY 变化保留旧消息，列表按当前游标代次过滤。
Keychain 是唯一凭据后端；数据库仅存随机 credential_ref。授权码更新创建新引用，数据库提交
失败时清理新条目；成功后尽力清理旧条目。拒绝清理可能留下孤立的 Keychain 条目，不会回退明文。

下文保留 M0 基线说明；当前增量以 M1 报告为准。

```text
gui/ (Qt widgets, signals, worker)
  → services/workspace.py (应用用例)
    → storage/database.py (连接、事务、迁移、备份)
      → storage/migrations/*.sql (打包资源)
config.py (本机路径) / eventlog.py (固定事件日志)
app.py (组合与启动)
```

单体应用，无外部服务、Shell 工具、MCP HTTP Server、SMTP 或自动云端调用。
后续在服务层后增加策略引擎、工具注册表、邮件适配器和 LLM Router，按 M1–M3 实现。
M0 不提供其空接口或虚假成功响应。

## 数据实体

`accounts`、`sync_cursors`、`messages`、`analyses`、`tasks`、`drafts`、`audit_events`
和 `schema_migrations` 对应需求实体；`app_settings` 只允许引导完成标记，不接受任意键值。
没有密码或 API Key 字段。邮件唯一键为 `(account_id, folder, uidvalidity, uid)`。
草稿状态列为 M3 预留；仅有状态列不代表审批或发送功能已经实现。
任务期限类型区分 invitation_response / review_report / revision / proof。
时间默认以 UTC ISO 格式存储，后续邮件时间和提醒由业务层明确转换。

## 存储操作

每个操作创建并关闭专属连接，避免跨线程共享连接。所有数据值绑定参数；DDL 仅来自打包的
可信 SQL 文件。迁移历史创建和所有待运行迁移共用一个 IMMEDIATE 事务，失败则回滚。
已应用 SQL 文件不可修改，新变更追加新迁移。打开时检查 quick_check、历史连续性和 SHA-256。
未知新版本拒绝打开，避免旧应用破坏新数据库。

一致性备份使用 SQLite backup API，拒绝覆盖文件。备份失败移除本次新建的不完整目标，
保留原数据库。恢复暂不提供自动按钮：退出应用、保留原文件及 WAL/SHM，再由维护人员验证
备份并恢复；M1 处理真实数据前需扩展恢复流程。不要在应用运行时直接替换数据库。

## UI 与失败处理

初始化、引导持久化和备份放入 QThreadPool；Qt signals 传回成功数据或无敏感内容的失败信号。
数据操作未完成时暂缓退出。错误界面只给出用户可操作的说明，不显示 Python Traceback。
遵循系统 Qt/macOS 样式和调色板，未强制浅色。

## 安全边界

M0 没有邮件输入、工具调用或网络处理路径，因此不把未来的 Prompt Injection / 云端授权 /
审批安全验收声明为已通过。M1/M2/M3 必须分别补充真实边界测试。
日志只接受 Event 枚举，不接收异常信息；审计表目前只记录本地引导完成。
SQLite 的存在与 UI 隐私文案不替代后续确定性策略引擎。
