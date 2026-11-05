"""일반 실행: 폴더·로그·DB를 준비하고 메인 창을 띄운다."""

import logging
import sys
from collections.abc import Sequence

from autotrader import __version__
from autotrader.app.logging_setup import configure_logging
from autotrader.config.paths import APP_DIR_NAME, AppPaths, display_path, resolve_app_paths
from autotrader.storage.database import initialize_database

log = logging.getLogger(__name__)


def prepare_runtime() -> AppPaths:
    """앱 폴더를 만들고 로그와 DB를 준비한다. Qt는 쓰지 않는다."""
    paths = resolve_app_paths()
    paths.ensure()
    configure_logging(paths.log_file)
    log.info(
        "앱 시작: 버전 %s, 폴더 %s",
        __version__,
        display_path(paths.root),
        extra={"event": "APP_START"},
    )
    try:
        version = initialize_database(paths.database_file)
    except Exception:
        log.exception("DB를 준비하지 못했습니다")
        raise
    log.info("DB 준비: 스키마 버전 %s", version)
    return paths


def run_gui(argv: Sequence[str] | None = None) -> int:
    """메인 창을 띄우고 이벤트 루프를 돈다. 창을 닫으면 끝난다(트레이는 6단계)."""
    prepare_runtime()

    from PySide6.QtWidgets import QApplication

    from autotrader.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication(list(argv) if argv is not None else sys.argv[:1])
    app.setApplicationName(APP_DIR_NAME)
    app.setApplicationVersion(__version__)
    window = MainWindow()
    window.show()
    code = app.exec()
    log.info("앱 종료: 코드 %s", code, extra={"event": "APP_STOP"})
    return code
