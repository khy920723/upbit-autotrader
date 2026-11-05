"""메인 창. 지금은 빈 창이고, 대시보드(SCR-02)는 6단계에서 만든다."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QMainWindow, QWidget

from autotrader import __version__

WINDOW_TITLE = "업비트 자동매매"
PLACEHOLDER_TEXT = "아직 매매 기능이 없는 빈 창입니다.\n화면은 이후 단계에서 추가됩니다."


class MainWindow(QMainWindow):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"{WINDOW_TITLE} {__version__}")
        placeholder = QLabel(PLACEHOLDER_TEXT, self)
        placeholder.setObjectName("placeholderLabel")
        placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setCentralWidget(placeholder)
        self.resize(960, 640)
