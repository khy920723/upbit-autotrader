from PySide6.QtWidgets import QLabel

import autotrader
from autotrader.ui.main_window import WINDOW_TITLE, MainWindow


def test_title_has_the_app_name_and_version(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)

    assert WINDOW_TITLE == "업비트 자동매매"
    assert window.windowTitle() == f"업비트 자동매매 {autotrader.__version__}"


def test_window_is_hidden_until_shown(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)

    assert not window.isVisible()


def test_window_says_it_is_an_empty_skeleton(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)

    label = window.findChild(QLabel, "placeholderLabel")

    assert label is not None
    assert "빈 창" in label.text()


def test_window_can_be_shown_offscreen(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)

    window.show()
    qtbot.waitExposed(window)

    assert window.isVisible()
