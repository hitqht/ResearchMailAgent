# M0 阶段报告

本报告记录本地静态验收结果。远端提交、标签和 CI 的实时结果在阶段交付回复中单独报告。

- 里程碑：M0 工程初始化。
- 当前版本：0.1.0。
- 已完成功能：基础 GUI、六项导航、首次引导、后台数据库初始化、版本化迁移、
  引导状态持久化、数据库一致性备份、受限事件日志、测试框架和 CI 定义。
- 主要修改文件：`pyproject.toml`、`uv.lock`、`src/researchmail/app.py`、
  `gui/{window,onboarding,worker}.py`、`services/workspace.py`、`storage/database.py`、
  `storage/migrations/*.sql`、`tests/`、`scripts/`、`.github/workflows/ci.yml` 和工程文档。
- 测试命令：`bash scripts/check.sh`。
- 测试结果：**27 passed**；Ruff、格式检查、mypy（14 个源码文件）、Bandit 和秘密扫描通过。
- 测试覆盖率：**93.01%**（包含 branch coverage，467 条语句、62 个分支）。
- 安全检查结果：未发现候选秘密；无受禁止的数据文件进入扫描文件集。未运行任何真实邮箱测试。
- GUI：`uv run --locked python scripts/gui_smoke.py`；Cocoa 浅色和应用内深色覆盖均成功，
  已检查今日、首次引导和设置截图。未修改系统外观。
- 包装验证：`uv build --wheel --offline` 成功；在隔离虚拟环境安装 wheel，确认两个 SQL
  迁移资源可用、全新数据库可初始化。wheel 仅供工程验证，不是独立桌面安装包。
- 本地运行方式：`uv run --locked researchmail-agent`（开发者预览）。
- 构建产物路径：`dist/researchmail_agent-0.1.0-py3-none-any.whl`。
- wheel SHA-256：`a84ba4a31345ca08942753ac9e1bf88afd225a4fb283cf8432a445eba26c9f4d`。
- 截图与本地检查输出：`artifacts/gui/`、`artifacts/gui-dark/`、`artifacts/check.txt`，均不提交。
- GitHub 目标：用户指定的公共仓库 https://github.com/hitqht/ResearchMailAgent。
- GitHub 分支：`feature/m0-foundation` → `main`。
- Git 基点：用户初始提交 `c8f04fbab6fa2a8ed863c5b9f2057fca93259166`，仅含标题 README。
- Git Commit SHA / Tag / 推送状态：静态报告不嵌入自引用哈希；交付时实际核验远端引用，
  结果写入阶段交付回复和本机 `artifacts/M0-delivery.json`。未核验前不视作远端发布成功。

## 修复与复测

首次完整 GUI 测试因 Qt QWizard 默认背景检索系统 KeyboardSetupAssistant 资源返回空 URL
而原生崩溃。最小复现不含应用业务代码，仍可复现。仅改变 WizardStyle 无效，显式透明
BackgroundPixmap 后原复现与完整 GUI 测试均通过。最终代码固定背景回退，显式显示取消按钮。

沙箱内 Cocoa 冒烟测试无法连接 WindowServer；在允许的主机权限下重新执行成功。
首次 wheel 构建因网络沙箱 DNS 失败；使用已缓存构建依赖离线构建成功。
Qt 组件调整与原始环境信息见 [environment.md](environment.md)。

## 未完成与下一阶段

M1–M4 未开始。`.app`、`.dmg`、Applications 安装、升级、独立首次运行、Developer ID 签名、
Apple 公证、Gatekeeper 和 GitHub Release **未完成 / 未执行**，不属于本次 M0 验收。
无有效签名身份；notarytool 存在但未验证公证凭据。当前数据库与备份未加密。

下一阶段按 M1 实现 163 只读连接、Keychain、UID/UIDVALIDITY 增量同步、MIME、安全纯文本、
邮件列表与详情、网络失败处理及开发版 DMG。真实账户参数必须在本机配置。
