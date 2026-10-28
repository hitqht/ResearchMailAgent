# 实机环境检查

## M3 复验

2026-10-28：真实163 SMTP SSL登录成功，仅认证，未提交MAIL/RCPT/DATA。
既有qwen3:1.7b对合成邮件生成本地DRAFT成功；未读取真实邮件用于草稿生成。
Cocoa浅色/深色草稿编辑与审批界面已验证，开发包仍为ad-hoc签名。


## M2 复验

2026-10-28：本机 Ollama 服务运行，既有 qwen3:1.7b 通过合成邮件的真实连接、分类与期限提取。
163 SSL 认证、10个目录、164封收件箱只读缓存、重复增量及未读样本 FLAGS 保持已实测。
真实邮件未交给模型；授权码仅存本机 Keychain，仓库未包含账户或邮件数据。
开发 DMG 继续使用 ad-hoc 签名；正式签名与公证留至 M4。

## M1 复验

2026-10-27：macOS 26.1（25B78）、arm64、hdiutil可用、有效签名身份仍为0。
本机 .tools/gh 为官方2.103.3，原CLI认证无效，Git远端继续使用已有SSH认证。
Qt/Python/uv 技术栈不变；M1 已完成原生Keychain合成条目的读写删除验证，以及
PyInstaller独立应用、DMG挂载、临时安装副本的实际启动验证。
没有使用真实邮箱授权码、Developer ID证书或Apple公证凭据。

下文为 M0 的原始环境检查记录。

检查日期：2026-10-27（Asia/Shanghai）。当前工作目录最初为空，无已有 Git 仓库或用户代码。

| 检查 | 实际结果 |
| --- | --- |
| `sw_vers` | macOS 26.1，Build 25B78，与目标版本一致 |
| `uname -m` | arm64 |
| `xcode-select -p` | /Applications/Xcode.app/Contents/Developer |
| `xcrun clang --version` | Apple clang 14.0.3；工具链可调用 |
| `python3 --version` | Python 3.12.13 |
| `python3.12` | 可用（pyenv shim） |
| `git --version` | 2.41.0 |
| Git identity | 已配置；不将本机配置详情放入报告 |
| `uv --version` | 0.11.12 |
| `gh --version` / `gh auth status` | 未安装，不能声明 CLI 已认证 |
| GitHub 连接器 | 已认证 hitqht，可读仓库元数据 |
| Ollama | 客户端已安装，报告版本 0.40.8；localhost:11434 未运行 |
| `security find-identity -v -p codesigning` | 0 valid identities found |
| `xcrun --find notarytool` | 可用 |

未读取或输出 GitHub Token、Apple 凭据、邮箱授权码或 API Key。
notarytool 可用不等于已配置公证账户；本阶段未访问 Apple 凭据或使用证书。
系统版本匹配仅满足环境前提，不代表已完成 M4 的安装、升级、签名和公证兼容性验收。

## 依赖策略

使用 Python 3.12 系列，`pyproject.toml` 描述兼容范围，`uv.lock` 固定完整传递依赖及哈希。
项目独立 `.venv`，不修改系统 Python。运行和 CI 使用 `--locked`。
M0 声明完整技术栈所需基础库，但仅导入当前阶段实际使用的模块。
Qt 仍使用 PySide6 API，依赖选用官方 `PySide6-Essentials` 分发包，包含当前所需
QtCore/QtGui/QtWidgets/QtTest，避免完整元包额外拉取 M0 未使用的 WebEngine/PDF/Addons。
原因：降低首次下载、运行依赖与后续打包维护负担；并非替换 GUI 技术栈。
依据：[Qt 官方 Essentials 包说明](https://pypi.org/project/PySide6-Essentials/)。
最终解析版本以锁文件为准。
