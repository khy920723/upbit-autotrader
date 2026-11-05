"""진입점: `python -m autotrader [--self-test]`.

PyInstaller exe는 packaging/launcher.py를 거쳐 이 main()을 부른다.
여기서는 표준 라이브러리만 import한다. 무거운 모듈은 실행할 기능을 고른 뒤에 가져온다.
"""

import argparse
import contextlib
import sys
import traceback
from collections.abc import Sequence
from pathlib import Path

from autotrader import __version__

# autotrader/app/self_test.py의 REPORT_FILE_NAME과 같아야 한다(테스트가 확인한다).
# 그 모듈을 import하지 못한 경우에도 보고서를 남기려고 따로 둔다.
FALLBACK_REPORT_NAME = "self-test-report.txt"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="autotrader", description="업비트 KRW 마켓 개인용 자동매매 앱"
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="창 없이 실행 환경을 점검하고 현재 폴더에 self-test-report.txt를 쓴 뒤 끝낸다"
        "(성공 0, 실패 1)",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.self_test:
        return _self_test()

    from autotrader.app.application import run_gui

    return run_gui()


def _self_test() -> int:
    # 창 모드 exe에서 예외가 밖으로 나가면 오류 대화상자가 떠서 CI가 멈춘다.
    # 그래서 무엇이 나든 보고서를 남기고 실패(1)로 끝낸다.
    try:
        from autotrader.app.self_test import run_self_test

        return run_self_test()
    except BaseException:
        _write_fallback_report(traceback.format_exc())
        return 1


def _write_fallback_report(details: str) -> None:
    text = (
        "업비트 자동매매 자가 점검 (--self-test)\n"
        f"버전: {__version__}\n\n"
        "자가 점검을 끝까지 실행하지 못했습니다.\n"
        f"{details}\n"
        "결과: 실패\n"
    )
    with contextlib.suppress(OSError):
        (Path.cwd() / FALLBACK_REPORT_NAME).write_text(text, encoding="utf-8-sig")


if __name__ == "__main__":
    sys.exit(main())
