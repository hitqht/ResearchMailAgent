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
                    "你可在设置中配置邮箱并发起 SSL 只读连接。云端分析需要逐封授权。"
                ),
            ),
            (
                "隐私从本地开始",
                "你的研究材料由你掌控。",
                (
                    "邮箱客户端授权码仅存入 macOS Keychain。\n\n"
                    "邮件保密级别未知时按敏感处理；云端处理需要明确授权。\n"
                    "本地模型故障不会自动切换到云端。"
                ),
            ),
            (
                "工作区已准备好",
                "无需提供账号或密钥。",
                (
                    "完成后仅保存本机的引导状态。\n\n"
                    "进入设置配置163邮箱与模型；分析后可确认科研任务与截止日期。\n"
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
