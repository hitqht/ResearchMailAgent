from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWizard, QWizardPage


class OnboardingWizard(QWizard):
    def __init__(self) -> None:
        super().__init__()
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        self.setOption(QWizard.WizardOption.NoCancelButton, False)
        # Qt's default macOS background looks up KeyboardSetupAssistant's bundle.
        # On this Tahoe installation that lookup returns nil and aborts in Obj-C.
        # A non-null, transparent background prevents that fallback on every style.
        background = QPixmap(1, 1)
        background.fill(Qt.GlobalColor.transparent)
        self.setPixmap(QWizard.WizardPixmap.BackgroundPixmap, background)
        self.setWindowTitle("欢迎使用 ResearchMail Agent")
        self.setMinimumSize(560, 380)
        self.setButtonText(QWizard.WizardButton.NextButton, "下一步")
        self.setButtonText(QWizard.WizardButton.BackButton, "上一步")
        self.setButtonText(QWizard.WizardButton.CancelButton, "稍后设置")
        self.setButtonText(QWizard.WizardButton.FinishButton, "进入工作区")
        pages = (
            (
                "为科研邮件留出专注空间",
                "此版本先建立你的本地工作区。",
                (
                    "今日、邮件、审稿与投稿、待办和草稿使用统一导航。\n\n"
                    "M0 工程预览尚未连接邮箱，也不会向外部服务发送数据。"
                ),
            ),
            (
                "隐私从本地开始",
                "你的研究材料由你掌控。",
                (
                    "后续邮箱授权码和模型 API Key 将存入 macOS Keychain。\n\n"
                    "邮件保密级别未知时按敏感处理；云端处理需要明确授权。\n"
                    "本地模型故障不会自动切换到云端。"
                ),
            ),
            (
                "工作区已准备好",
                "无需提供账号或密钥。",
                (
                    "完成后仅保存本机的引导状态。\n\n"
                    "邮箱接入将在 M1 实现；模型与科研任务管理将在 M2 实现。\n"
                    "你可以在设置中备份数据库并查看当前版本。"
                ),
            ),
        )
        for title, subtitle, body in pages:
            page = QWizardPage()
            page.setTitle(title)
            page.setSubTitle(subtitle)
            layout = QVBoxLayout(page)
            label = QLabel(body)
            label.setWordWrap(True)
            layout.addWidget(label)
            layout.addStretch()
            self.addPage(page)
