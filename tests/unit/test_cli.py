import sys

import pytest

import autotrader
from autotrader import __main__ as entry
from autotrader.app import application, self_test


def test_self_test_flag_runs_the_self_test_and_returns_its_exit_code(monkeypatch):
    calls = []
    monkeypatch.setattr(self_test, "run_self_test", lambda: calls.append("run") or 1)

    assert entry.main(["--self-test"]) == 1
    assert calls == ["run"]


def test_no_arguments_start_the_gui(monkeypatch):
    monkeypatch.setattr(application, "run_gui", lambda: 7)

    assert entry.main([]) == 7


def test_version_flag_prints_the_version(capsys):
    with pytest.raises(SystemExit) as exc:
        entry.main(["--version"])

    assert exc.value.code == 0
    assert autotrader.__version__ in capsys.readouterr().out


def test_unknown_argument_is_a_usage_error():
    with pytest.raises(SystemExit) as exc:
        entry.main(["--self-tset"])

    assert exc.value.code == 2


def test_fallback_report_name_matches_the_self_test():
    assert entry.FALLBACK_REPORT_NAME == self_test.REPORT_FILE_NAME


def test_self_test_that_cannot_be_imported_still_fails_cleanly(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setitem(sys.modules, "autotrader.app.self_test", None)

    assert entry.main(["--self-test"]) == 1

    report = (tmp_path / entry.FALLBACK_REPORT_NAME).read_text(encoding="utf-8-sig")
    assert "결과: 실패" in report
    assert "ImportError" in report or "ModuleNotFoundError" in report


def test_self_test_that_raises_still_fails_cleanly(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    def broken():
        raise RuntimeError("뜻밖의 오류")

    monkeypatch.setattr(self_test, "run_self_test", broken)

    assert entry.main(["--self-test"]) == 1
    report = (tmp_path / entry.FALLBACK_REPORT_NAME).read_text(encoding="utf-8-sig")
    assert "RuntimeError: 뜻밖의 오류" in report
