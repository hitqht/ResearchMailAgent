# M3 本地验收报告

版本：0.4.0。范围：草稿生成、编辑、人工审批与受控发送开发版。最终Git引用、CI与镜像SHA见本机阶段交付记录。

## 已实现

- 新建本地草稿、按意图创建回复、Ollama本机模型生成主题与正文；模型无收件人/发送权限。
- 本地编辑、保存、撤销未保存修改；未保存时阻止切换、发送和窗口退出。
- 完整预览、人工REVIEWED、APPROVED及单次确认发送，默认取消。
- 审批SHA256绑定正文、收件人、主题、草稿版本、稳定Message-ID/Date与发件配置。
- 数据库迁移5：内容/发件账户修改清空审批，发送中/已发送/待核实内容锁定。
- SMTP_SSL证书校验、Keychain认证、全部RCPT接受才DATA；任一地址拒绝则取消整封提交。
- 单次内存发送令牌、五分钟过期、跨进程flock、事务内原子claim，防重复点击和并发发送。
- 持久化发送尝试、阶段标记、摘要、历史信封快照与固定事件审计。
- 提交前失败可重新审核；DATA阶段不确定异常、进程中断或接受后数据库失败保守待核实，禁止自动重发。
- 明确250接受后QUIT失败不撤销SENT；SENT在界面标为“服务器已接受”。
- mail.send_approved内部工具受Origin、单次确认令牌、审批摘要与状态共同保护；模型调用始终拒绝。
- SMTP认证测试只登录，不提交MAIL/RCPT/DATA；所有长操作在Worker中执行。

## 实际验证

- `bash scripts/check.sh`：174项测试通过，含分支覆盖率87.64%；Ruff、严格mypy、Bandit、秘密扫描通过。
- 单元/集成测试使用临时SQLite、Mock SMTP与Mock LLM，覆盖非法头部/收件人、未批准发送、修改后审批失效、
  双实例竞争、令牌过期/复用、部分地址拒绝、DATA超时、明确拒绝、QUIT失败、数据库失败与中断恢复。
- GUI测试覆盖完整审核/批准/取消/模拟发送、修改后重审、待核实只读、未保存退出保护、模型草稿与SMTP反馈。
- 真实163 SMTP SSL认证成功：仅连接/登录/退出，未提交MAIL、RCPT或DATA，没有实际发信。
- 本机既有qwen3:1.7b对固定合成邮件生成DRAFT成功，没有读取真实邮件用于生成，也没有调用SMTP。
  该次模型输出为英文，模型语言与语义质量不能由格式校验保证，必须人工核对。
- Cocoa浅色/深色合成草稿界面实测；默认1100×740窗口的正文、保存、审核、批准与发送操作可见。
- wheel、独立.app、开发DMG及挂载/临时Applications副本独立启动由阶段交付记录核验。
- M2→M3迁移测试保留旧草稿内容、账户及Keychain引用；旧草稿首次准备时补齐稳定邮件头并撤销旧审批。
- 增加已观测hdiutil Resource busy有限重试（最多3次）回归测试；其他错误立即失败。
  CI延长uv下载/连接超时，不更换依赖来源、不关闭TLS校验。

## 文件与命令

主要文件：`drafts/models.py`、`services/draft_service.py`、`storage/draft_repository.py`、
`005_draft_delivery.sql`、`mail/smtp.py`、`gui/draft_controller.py`、`gui/draft_widgets.py`、
`services/ai_service.py`、`tools/registry.py`、`gui/window.py`、`scripts/{draft_smoke,create_dmg}.*`
及`tests/test_{drafts,draft_gui,smtp,packaging}.py`。

本地命令：`bash scripts/check.sh`、`python scripts/gui_smoke.py --appearance light/dark`、
`python scripts/draft_smoke.py --model qwen3:1.7b`、`uv build --wheel --offline`、
`bash scripts/build_dmg.sh`、`python scripts/verify_bundle.py --dmg dist/ResearchMailAgent-0.4.0-arm64-dev.dmg`。
普通用户直接打开.app；无需Python/uv。Ollama仅在选择本地模型功能时需要。

## 限制与未执行

- 没有向真实收件人实际发信；最终服务商投递及真实收件验收未执行，须在应用中明确批准并确认。
- 本地模型建议不保证正确或中文输出；本阶段不支持云端生成草稿。
- 仅纯文本与ASCII裸邮箱地址；不支持附件、抄送、SMTPUTF8地址、Reply-To或线程引用头。
- 不自动创建IMAP“已发送”副本，不保证最终送达；网页已发送为空不能证明服务器未接受。
- UNCERTAIN不可编辑、重发或在应用内解除；需要外部核实并另行处理。不同草稿或服务商投递不保证exactly-once。
- 草稿列表显示最近200项，无删除/归档/自动批量生成；事件日志不包含邮件内容，发送快照仅在本机数据库。
- 打包应用访问Keychain可能需要本机系统确认；真实认证使用开发Python。
- 复制安装验证在临时Applications完成，未覆盖系统Applications。
- 仍是ad-hoc签名开发版；Developer ID、Apple公证、Gatekeeper正式验收与GitHub正式Release未完成。

## 协议依据

- [Python smtplib](https://docs.python.org/3.12/library/smtplib.html)：SMTP_SSL、底层MAIL/RCPT/DATA接口与异常。
- [RFC 5321](https://www.rfc-editor.org/rfc/rfc5321.html)：SMTP事务及确认回复；网络中断下不能从本地超时证明未送达。
- [uv环境变量](https://docs.astral.sh/uv/reference/environment/)：HTTP连接与读取超时设置。

下一阶段M4：正式签名、公证、装订票据、安装验收与Release；需有效Developer ID Application身份及官方公证配置。
