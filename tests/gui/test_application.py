import logging

from PySide6.QtCore import QTimer

from autotrader.app.application import prepare_runtime, run_gui
from autotrader.storage.database import SCHEMA_VERSION, read_schema_version


def log_text(paths) -> str:
    for handler in logging.getLogger().handlers:
        handler.flush()
    return paths.log_file.read_text(encoding="utf-8")


def test_prepare_runtime_creates_folders_log_and_database(isolated_app_home):
    paths = prepare_runtime()

    assert paths == isolated_app_home
    for folder in paths.directories():
        assert folder.is_dir()
    assert read_schema_version(paths.database_file) == SCHEMA_VERSION
    assert "| APP_START |" in log_text(paths)


def test_run_gui_shows_the_window_and_logs_start_and_stop(qapp, isolated_app_home):
    shown = []

    def quit_after_checking():
        shown.extend(w.windowTitle() for w in qapp.topLevelWidgets() if w.isVisible())
        qapp.quit()

    QTimer.singleShot(0, quit_after_checking)

    assert run_gui() == 0

    assert any(title.startswith("업비트 자동매매") for title in shown)
    text = log_text(isolated_app_home)
    assert "| APP_START |" in text
    assert "| APP_STOP |" in text
