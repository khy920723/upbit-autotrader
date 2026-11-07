"""--self-test를 새 프로세스로 실행한다.

Windows 러너의 exe 점검(build-exe.yml)과 같은 흐름을 Linux에서 먼저 확인한다.
"""

import importlib.metadata
import os
import subprocess
import sys
from pathlib import Path

import certifi
import pytest

REPORT = "self-test-report.txt"


@pytest.fixture
def clean_env(tmp_path: Path) -> dict[str, str]:
    home = tmp_path / "home"
    home.mkdir()
    env = dict(os.environ)
    # QT_QPA_PLATFORM이 없어도 self-test가 스스로 offscreen을 써야 한다.
    env.pop("QT_QPA_PLATFORM", None)
    env.update(
        HOME=str(home),
        USERPROFILE=str(home),
        LOCALAPPDATA=str(home / "AppData" / "Local"),
        XDG_DATA_HOME=str(home / ".local" / "share"),
    )
    return env


def run(args: list[str], cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def report_text(cwd: Path) -> str:
    return (cwd / REPORT).read_text(encoding="utf-8-sig")


def describe(result: subprocess.CompletedProcess[str], cwd: Path) -> str:
    """실패 메시지. 프로세스가 보고서를 쓰기 전에 죽어도 종료 코드와 stderr를 보여 준다."""
    path = cwd / REPORT
    report = path.read_text(encoding="utf-8-sig") if path.exists() else "<보고서 없음>"
    return (
        f"returncode={result.returncode}\n--- report ---\n{report}"
        f"\n--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
    )


def test_module_entry_point_passes(tmp_path, clean_env):
    """TS-137: 모듈 진입점의 --self-test가 통과하면 0으로 끝난다."""
    result = run(["-m", "autotrader", "--self-test"], tmp_path, clean_env)

    assert result.returncode == 0, describe(result, tmp_path)
    assert "결과: 통과 (6/6)" in report_text(tmp_path)


def test_pyinstaller_launcher_script_passes(tmp_path, clean_env, repo_root):
    """TS-137: PyInstaller 시작 스크립트의 --self-test도 통과한다."""
    launcher = repo_root / "packaging" / "launcher.py"

    result = run([str(launcher), "--self-test"], tmp_path, clean_env)

    assert result.returncode == 0, describe(result, tmp_path)
    assert "결과: 통과 (6/6)" in report_text(tmp_path)


def test_failing_check_gives_exit_code_1(tmp_path, clean_env):
    """TS-137: 점검이 실패하면 프로세스가 1로 끝난다."""
    blocker = tmp_path / "not-a-folder"
    blocker.write_text("x", encoding="utf-8")
    clean_env["XDG_DATA_HOME"] = str(blocker)
    clean_env["LOCALAPPDATA"] = str(blocker)

    result = run(["-m", "autotrader", "--self-test"], tmp_path, clean_env)

    assert result.returncode == 1, describe(result, tmp_path)
    report = report_text(tmp_path)
    assert "[실패] 설정 경로" in report
    assert "결과: 실패 (5/6)" in report


def test_tls_line_reports_the_certifi_bundle_whatever_the_ssl_environment(tmp_path, clean_env):
    # D-093: REST·웹소켓·자가 점검은 certifi 묶음만 쓴다. SSL_CERT_FILE·SSL_CERT_DIR가 엉뚱한 곳을
    # 가리켜도 TLS 점검은 통과하고 certifi 묶음의 CA 수를 보고한다. 연결은 하지 않는다.
    clean_env["SSL_CERT_FILE"] = str(tmp_path / "missing.pem")
    clean_env["SSL_CERT_DIR"] = str(tmp_path / "missing-dir")
    bundle = Path(certifi.where())
    ca_count = bundle.read_text(encoding="utf-8").count("-----BEGIN CERTIFICATE-----")

    result = run(["-m", "autotrader", "--self-test"], tmp_path, clean_env)

    assert result.returncode == 0, describe(result, tmp_path)
    report = report_text(tmp_path)
    tls_lines = [line for line in report.splitlines() if line.startswith("[통과] TLS 인증서: ")]
    assert len(tls_lines) == 1, report
    assert f"certifi {importlib.metadata.version('certifi')}" in tls_lines[0]
    assert f"CA 인증서 {ca_count}개" in tls_lines[0]
    assert "최소 TLSv1_2" in tls_lines[0]
    assert str(bundle) not in report
