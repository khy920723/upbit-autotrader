"""의존성 라이선스 문서(docs/07-security-legal/dependency-licenses.md)가 uv.lock과 맞는지 본다."""

import importlib.util
import sys

import pytest

ALL = ("Windows", "Linux", "macOS")

FAKE_LOCK = {
    "package": [
        {
            "name": "app",
            "version": "0.0.1",
            "source": {"editable": "."},
            "dependencies": [
                {"name": "lib"},
                {"name": "winonly", "marker": "sys_platform == 'win32'"},
            ],
            "dev-dependencies": {"dev": [{"name": "tool"}]},
        },
        {
            "name": "lib",
            "version": "1.0",
            "source": {"registry": "x"},
            "dependencies": [{"name": "sub"}],
        },
        {"name": "sub", "version": "2.0", "source": {"registry": "x"}},
        {"name": "winonly", "version": "3.0", "source": {"registry": "x"}},
        {
            "name": "tool",
            "version": "4.0",
            "source": {"registry": "x"},
            "dependencies": [
                {"name": "lib"},
                {"name": "macdep", "marker": "sys_platform == 'darwin'"},
            ],
        },
        {"name": "macdep", "version": "5.0", "source": {"registry": "x"}},
    ]
}


@pytest.fixture(scope="module")
def inventory(request):
    root = request.config.rootpath
    spec = importlib.util.spec_from_file_location(
        "license_inventory", root / "scripts" / "license_inventory.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["license_inventory"] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop("license_inventory", None)


def doc(runtime_rows: str, dev_rows: str) -> str:
    header = "| 패키지 | 버전 | 라이선스 | 설치 플랫폼 | 비고 |\n|---|---|---|---|---|\n"
    return (
        "# 의존성 라이선스 목록\n\n"
        "<!-- license-inventory:runtime:start -->\n"
        f"{header}{runtime_rows}"
        "<!-- license-inventory:runtime:end -->\n\n"
        "<!-- license-inventory:dev:start -->\n"
        f"{header}{dev_rows}"
        "<!-- license-inventory:dev:end -->\n"
    )


GOOD_DOC = doc(
    "| lib | 1.0 | MIT | Windows, Linux, macOS | |\n"
    "| sub | 2.0 | BSD-3-Clause | Windows, Linux, macOS | |\n"
    "| winonly | 3.0 | Apache-2.0 | Windows | |\n",
    "| tool | 4.0 | GPL-2.0-or-later | Windows, Linux, macOS | 빌드 도구 |\n"
    "| macdep | 5.0 | MIT | macOS | |\n",
)


def no_metadata(name):
    return None


def test_the_real_document_matches_uv_lock(inventory):
    problems = inventory.check(
        inventory.DOC_PATH.read_text(encoding="utf-8"), inventory.load_lock(inventory.LOCK_PATH)
    )

    assert problems == [], "\n".join(problems) + "\n→ scripts/license_inventory.py --write 후 확인"


def test_runtime_closure_follows_markers_per_platform(inventory):
    assert inventory.inventory(FAKE_LOCK, "runtime") == {
        "lib": ("1.0", ALL),
        "sub": ("2.0", ALL),
        "winonly": ("3.0", ("Windows",)),
    }


def test_dev_closure_excludes_runtime_packages(inventory):
    assert inventory.inventory(FAKE_LOCK, "dev") == {
        "tool": ("4.0", ALL),
        "macdep": ("5.0", ("macOS",)),
    }


def test_good_document_has_no_problems(inventory):
    assert inventory.check(GOOD_DOC, FAKE_LOCK, installed_license=no_metadata) == []


def test_missing_extra_and_mismatched_rows_are_reported(inventory):
    bad = doc(
        "| lib | 1.1 | MIT | Windows, Linux, macOS | |\n"
        "| winonly | 3.0 | Apache-2.0 | Windows, Linux | |\n"
        "| ghost | 9.9 | MIT | Windows | |\n",
        "| tool | 4.0 | GPL-2.0-or-later | Windows, Linux, macOS | |\n"
        "| macdep | 5.0 | MIT | macOS | |\n",
    )

    problems = "\n".join(inventory.check(bad, FAKE_LOCK, installed_license=no_metadata))

    assert "runtime: lib 버전 1.1 ≠ uv.lock 1.0" in problems
    assert "runtime: sub 행이 없다" in problems
    assert "runtime: ghost는 uv.lock에 없다" in problems
    assert "runtime: winonly 플랫폼" in problems


@pytest.mark.parametrize(
    ("expression", "allowed"),
    [
        ("MIT", True),
        ("Apache-2.0 OR BSD-3-Clause", True),
        ("LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only", True),
        ("MIT AND BSD-3-Clause", True),
        ("(MIT OR GPL-3.0-only) AND Apache-2.0", True),
        ("GPL-3.0-only", False),
        ("MIT AND GPL-3.0-only", False),
        ("GPL-2.0-or-later WITH Bootloader-exception", False),
        ("확인 필요", False),
        ("", False),
    ],
)
def test_runtime_license_expressions(inventory, expression, allowed):
    assert inventory.is_allowed_for_distribution(expression) is allowed


def test_incompatible_runtime_license_is_reported(inventory):
    bad = GOOD_DOC.replace("| lib | 1.0 | MIT |", "| lib | 1.0 | GPL-3.0-only |")

    problems = inventory.check(bad, FAKE_LOCK, installed_license=no_metadata)

    assert problems == ["runtime: lib 라이선스 'GPL-3.0-only'는 배포에 쓸 수 없다(MIT 앱과 충돌)"]


def test_license_that_differs_from_package_metadata_is_reported(inventory):
    problems = inventory.check(
        GOOD_DOC, FAKE_LOCK, installed_license=lambda name: "Apache-2.0" if name == "lib" else None
    )

    assert problems == ["runtime: lib 라이선스 'MIT' ≠ 설치된 메타데이터 'Apache-2.0'"]


def test_write_keeps_human_columns_and_adds_new_rows(inventory):
    stale = doc(
        "| lib | 0.9 | MIT | Windows, Linux, macOS | 직접 의존 |\n",
        "| tool | 4.0 | GPL-2.0-or-later | Windows, Linux, macOS | 빌드 도구 |\n",
    )

    updated = inventory.rewrite(stale, FAKE_LOCK, installed_license=no_metadata)

    assert "| lib | 1.0 | MIT | Windows, Linux, macOS | 직접 의존 |" in updated
    assert "| winonly | 3.0 | 확인 필요 | Windows |  |" in updated
    assert "| macdep | 5.0 | 확인 필요 | macOS |  |" in updated
    assert inventory.check(updated, FAKE_LOCK, installed_license=no_metadata) != []
