import logging
from datetime import datetime, timedelta

from autotrader.app.logging_setup import (
    LOG_BACKUP_COUNT,
    LOG_MAX_BYTES,
    KstFormatter,
    configure_logging,
    remove_app_log_handlers,
)


def read_lines(path):
    for handler in logging.getLogger().handlers:
        handler.flush()
    return path.read_text(encoding="utf-8").splitlines()


def make_record(created: float, event: str | None = "APP_START") -> logging.LogRecord:
    record = logging.LogRecord("autotrader.test", logging.INFO, __file__, 1, "시작", None, None)
    record.created = created
    if event is not None:
        record.event = event
    return record


def test_formatter_writes_kst_time_level_module_event_and_message():
    line = KstFormatter().format(make_record(created=0.0))

    assert line == "1970-01-01T09:00:00.000+09:00 | INFO | autotrader.test | APP_START | 시작"


def test_formatter_uses_dash_when_event_code_is_missing():
    line = KstFormatter().format(make_record(created=0.0, event=None))

    assert line.split(" | ")[3] == "-"


def test_configure_logging_writes_utf8_lines_to_the_log_file(tmp_path):
    log_file = tmp_path / "logs" / "app.log"

    configure_logging(log_file)
    logging.getLogger("autotrader.test").info("앱 시작", extra={"event": "APP_START"})

    [line] = read_lines(log_file)
    time_text, level, module, event, message = line.split(" | ")
    assert datetime.fromisoformat(time_text).utcoffset() == timedelta(hours=9)
    assert (level, module, event, message) == ("INFO", "autotrader.test", "APP_START", "앱 시작")


def test_default_level_is_info(tmp_path):
    log_file = tmp_path / "app.log"

    configure_logging(log_file)
    logging.getLogger("autotrader.test").debug("숨김")
    logging.getLogger("autotrader.test").info("보임")

    assert [line.rsplit(" | ", 1)[1] for line in read_lines(log_file)] == ["보임"]


def test_configure_logging_twice_does_not_duplicate_lines(tmp_path):
    log_file = tmp_path / "app.log"

    configure_logging(log_file)
    configure_logging(log_file)
    logging.getLogger("autotrader.test").info("한 번")

    assert len(read_lines(log_file)) == 1


def test_file_handler_rotates_by_size(tmp_path):
    handler = configure_logging(tmp_path / "app.log")

    assert handler.maxBytes == LOG_MAX_BYTES == 10 * 1024 * 1024
    assert handler.backupCount == LOG_BACKUP_COUNT == 10


def test_remove_app_log_handlers_detaches_and_closes(tmp_path):
    handler = configure_logging(tmp_path / "app.log")

    remove_app_log_handlers()

    assert handler not in logging.getLogger().handlers
    assert handler.stream is None
