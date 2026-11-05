"""로그 설정.

형식: `시각(KST) | 수준 | 모듈 | 이벤트 코드 | 내용` (docs/04-data/logging-audit.md).
이벤트 코드는 `logger.info("...", extra={"event": "APP_START"})`처럼 넘긴다. 없으면 `-`.
비밀 가리기 필터와 90일 보관 정리는 이후 단계에서 붙인다.
"""

import logging
from datetime import datetime, timedelta, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path

KST = timezone(timedelta(hours=9), "KST")
LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(event)s | %(message)s"
LOG_MAX_BYTES = 10 * 1024 * 1024
LOG_BACKUP_COUNT = 10
NO_EVENT = "-"


class KstFormatter(logging.Formatter):
    """PC 시간대와 상관없이 KST로 시각을 쓴다."""

    def __init__(self) -> None:
        super().__init__(LOG_FORMAT)

    def format(self, record: logging.LogRecord) -> str:
        if not hasattr(record, "event"):
            record.event = NO_EVENT
        return super().format(record)

    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        return datetime.fromtimestamp(record.created, KST).isoformat(timespec="milliseconds")


class AppLogHandler(RotatingFileHandler):
    """앱이 붙인 로그 파일 핸들러. 다시 설정할 때 찾아서 떼어 내려고 따로 둔다."""


def configure_logging(log_file: Path, level: int = logging.INFO) -> AppLogHandler:
    """루트 로거에 앱 로그 파일을 붙인다. 다시 부르면 이전 핸들러를 바꾼다."""
    remove_app_log_handlers()
    log_file.parent.mkdir(parents=True, exist_ok=True)
    handler = AppLogHandler(
        log_file, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUP_COUNT, encoding="utf-8"
    )
    handler.setFormatter(KstFormatter())
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(level)
    return handler


def remove_app_log_handlers() -> None:
    """configure_logging이 붙인 핸들러를 떼고 파일을 닫는다."""
    root = logging.getLogger()
    for handler in [h for h in root.handlers if isinstance(h, AppLogHandler)]:
        root.removeHandler(handler)
        handler.close()
