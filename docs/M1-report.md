# M1 本地验收报告

版本：0.2.0。范围：只读邮箱开发版。远端提交、标签及 CI 结果由阶段交付记录单独核验。

## 已实现

- SSL IMAP 账户配置，163 默认地址可在初次同步前修改；SMTP 参数只保存，不连接。
- 强制 macOS Keychain 后端；随机引用入库，新授权码写入与数据库提交配合回滚。
- LIST 目录、modified UTF-7 解码、ID 扩展、只读 SELECT/EXAMINE、BODY.PEEK。
- UID 增量、组合唯一键去重、UIDVALIDITY 重建、每封邮件与游标原子提交。
- 网络最多3次尝试，认证失败不重试；每批最多100封，支持进度和停止。
- MIME 中英文标题、正文、HTML 安全纯文本、附件元数据、异常与超大邮件降级。
- 邮箱编辑、连接反馈、目录选择、邮件列表/详情、搜索、分页和可选定时同步。
- 迁移3、账户及同步审计、独立 .app、开发 DMG 与安装验证。

## 实测

- `bash scripts/check.sh`：56 passed，覆盖率87.63%（含分支）；Ruff、mypy、Bandit和秘密扫描通过。
- IMAP 适配器测试记录了 readonly=True 与 BODY.PEEK，确认无 STORE/APPEND/EXPUNGE/CLOSE 调用。
- Native macOS Keychain：合成随机条目的存入、读取、删除成功；没有访问已有条目。
- Cocoa 界面冒烟：合成邮件与账户、首次引导、本地迁移和备份。
- 独立应用：从构建目录、只读挂载 DMG、临时 Applications 安装副本成功启动。
  验证时 PATH 仅含系统目录、移除 Python/uv 变量，frozen=True，迁移版本3。
- DMG：hdiutil create/verify/attach/detach，应用与 Applications 快捷方式内容检查通过。
- codesign：本地 ad-hoc 签名完整性检查通过；不代表 Developer ID 或 Gatekeeper 验收。
- 构建报告与校验值：本机忽略目录 `artifacts/build-app.json`、`artifacts/build-dmg.json`
  和 `dist/*.dmg.sha256`。最终交付记录包含实际 SHA 与 Git 引用。

首次远端 CI 未分配到托管 ARM runner，在执行任何步骤前因容量限制取消；GitHub 的检查注解
明确返回 “The job was not acquired by Runner of type hosted even after multiple attempts”。
工作流改用官方支持的 `macos-15-intel` 标准 runner，最终结果由交付记录核验。
本机交付仍是 arm64，构建脚本根据实际架构生成相应名称的 DMG。
参考：[官方 runner 镜像表](https://github.com/actions/runner-images)。

## 主要文件

`mail/{models,imap,mime}.py`、`security/credentials.py`、`services/mail_service.py`、
`storage/mail_repository.py`、`003_readonly_mail.sql`、`gui/mail_controller.py`、
`gui/mail_widgets.py`、`diagnostics.py`、`scripts/build_{app,dmg}.sh`、
`scripts/verify_bundle.py` 和新增测试。

## 限制与未执行

- 真实163授权码未提供，真实账户认证、目录权限、网易服务策略、真实邮件联调未执行。
- Keychain 原生测试使用开发 Python；最终应用访问用户真实凭据的系统确认需由用户完成。
- SMTP、模型、Skills、草稿、任务提醒尚未实现；没有对外 MCP Server。
- 没有远端删除镜像、附件文件下载、全文搜索或无限批次后台导入。
- 自动同步只处理当前选中账户和目录；默认关闭。
- 已缓存邮件的账户不允许切换邮箱地址或收件服务器，防止 UID 身份混用。
- 数据库和备份未加密，UIDVALIDITY 历史会占用额外磁盘。
- 未执行系统 `/Applications` 覆盖安装、升级替换、另一CPU架构或其他macOS版本实机验收。
- Developer ID、公证、Gatekeeper、GitHub Release 未完成；不改动系统 Gatekeeper。

## 下一阶段

M2：本地/云端模型配置、隐私路由、分类摘要、科研 Skills、工具契约、任务和提醒。
M1 真实邮箱联调通过后再用于科研邮件。不要在聊天或公共仓库填写授权码。
