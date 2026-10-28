# M2 本地验收报告

版本 0.3.0；范围为 AI 邮件管理开发版。最终 Git 引用、CI 链接和镜像 SHA256 记录在本机交付报告。

## 实现

- Ollama、本机/云端模型配置、统一 Provider 接口与 MockProvider；API Key 独立 Keychain 服务。
- 默认本地优先，云端逐封预览并一次性授权；授权绑定实际内容与模型配置、五分钟过期。
- 未授权请求在调用 Provider 前拒绝；没有本地失败到云端的自动回退。
- Ollama 使用数值回环地址，不使用代理或重定向；阻止云模型名和 /api/show 远程别名。
- 七类分类、摘要、优先级、保密等级、原文引用、置信度、待确认任务与期限。
- Pydantic 输出契约、逐字引用检查、明确完整日期与分类/期限类型匹配检查。
- 七个版本化科研 Skill、包资源加载、分析规则版本与完整指令 SHA256。
- 进程内工具注册表与 JSON Schema；模型无写权限，无发送工具或对外 HTTP Server。
- 任务确认、日期人工修正、完成/忽略、应用内截止提醒与确定性本地日报。
- 后台 Worker、原生浅色/深色界面、迁移4、wheel、独立应用与开发 DMG。

## 实测证据

- `bash scripts/check.sh`：129 passed，含分支覆盖率88.46%；Ruff、mypy、Bandit、秘密扫描通过。
- 7个 Skill 通过 Skill Creator quick_validate；wheel 包含7个 Skill 和全部4个迁移。
- 本机既有 qwen3:1.7b：固定合成连接与合成退修邮件分类、原文引用、2026-11-30 期限提取成功。
  首次小模型返回了译文引用，被严格拒绝；精简重复规则并明确保留原文后通过。
  校验未放宽，新增译文拒绝测试。此结果不代表对所有模型的分析质量评估。
- 真实163：授权码写入 macOS Keychain，SSL认证、10个目录读取通过，收件箱缓存164封。
  再次增量新增0封；一封未读样本读取前后 FLAGS 一致，仍未读。
  不记录真实主题、正文、地址或授权码于交付报告；真实邮件模型请求0次，SMTP请求0次。
- 联调发现服务器 RFC822.SIZE 与实际正文 literal 相差4字节；旧检查拒绝并保留已提交游标。
  新增合成回归测试，改为核对实际传输 framing 长度、正文大小上限和 UID，兼容 UID 在 literal 后。
  正文请求上限为20 MiB+1，接受长度不超过20 MiB，避免接受达到请求上限的截断正文。
- 真正 Cocoa 浅色/深色截图与合成数据 GUI 测试通过。
- 构建目录、只读挂载 DMG、临时 Applications 副本均独立启动，frozen=True、schema_version=4；
  验证时 PATH 仅系统目录，移除 Python/uv 环境变量，使用临时合成数据库。
- 迁移前本机数据库已一致性备份；M1升级测试验证邮件 UID、Keychain 引用和缓存保留。

IMAP 只读与 BODY.PEEK 依据：[RFC 9051](https://www.rfc-editor.org/rfc/rfc9051.html#section-6.4.5)。
大小差异属于此次163服务器的实测兼容情况，不作为 IMAP 标准保证。

## 隐私与限制

- 分类摘要是模型建议；逐字证据检查不能证明语义正确，任务必须人工确认。
- 原文缺少年份、相对日期或含多个日期时期限为空；当前不推断时区，不支持复杂日历语义。
- 近期分析列表最多100封、任务列表最多1000项；分析按单封手动发起，没有自动整库处理。
- 提醒仅在应用运行时显示；每任务/日期每天一次，不提供退出后的系统通知服务。
- 云端协议通过 MockTransport 测试；未使用真实云端 API Key 或向云端发送真实邮件。
- 本机回环服务是可信运行环境，应用无法证明其他进程实现的服务永远不转发数据。
- 仅提供所列 API 认证，不实现 OAuth；不读取其他应用登录令牌。
- 真实Keychain与邮箱联调使用开发Python；打包应用访问钥匙串时可能需要本机系统确认。
- SMTP、草稿编辑审批与审批失效测试留至 M3。内部草稿工具仅生成本地 DRAFT。
- 开发 DMG 为 ad-hoc 签名，无 Developer ID、公证或正式 Gatekeeper 验收。
- 复制安装验证在临时 Applications 目录完成；没有覆盖系统 Applications。

## API 依据

- [Ollama Chat](https://docs.ollama.com/api/chat)：非流式请求、schema format。
- [Ollama Show](https://docs.ollama.com/api-reference/show-model-details) 与
  [官方类型定义](https://github.com/ollama/ollama/blob/main/api/types.go)：远程模型元数据。
- [OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)：
  兼容接口使用 JSON mode，应用端再执行 Pydantic 和证据校验；JSON mode 不等于 schema 保证。
