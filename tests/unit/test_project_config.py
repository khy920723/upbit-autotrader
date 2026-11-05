"""CLAUDE.md "고정 기술 기준"을 pyproject.toml, .python-version, uv.lock에서 확인한다."""

import tomllib

import pytest
from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.utils import canonicalize_name
from packaging.version import Version

import autotrader

PYSIDE_RANGE = SpecifierSet(">=6.12,<6.13")


@pytest.fixture
def pyproject(repo_root):
    return tomllib.loads((repo_root / "pyproject.toml").read_text(encoding="utf-8"))


@pytest.fixture
def lock_versions(repo_root):
    lock = tomllib.loads((repo_root / "uv.lock").read_text(encoding="utf-8"))
    return {package["name"]: package["version"] for package in lock["package"]}


def runtime_requirements(pyproject) -> dict[str, Requirement]:
    reqs = (Requirement(text) for text in pyproject["project"]["dependencies"])
    return {canonicalize_name(req.name): req for req in reqs}


def test_python_is_313_only(pyproject, repo_root):
    assert pyproject["project"]["requires-python"] == ">=3.13,<3.14"
    assert (repo_root / ".python-version").read_text(encoding="utf-8").strip() == "3.13"


def test_runtime_dependencies_are_only_pyside6_and_keyring(pyproject):
    assert set(runtime_requirements(pyproject)) == {"pyside6", "keyring"}


def test_runtime_dependencies_are_pinned_exactly(pyproject):
    for name, req in runtime_requirements(pyproject).items():
        specs = list(req.specifier)
        assert len(specs) == 1, name
        assert specs[0].operator == "==", name
        assert "*" not in specs[0].version, name


def test_pyside6_stays_below_613(pyproject, lock_versions):
    [spec] = runtime_requirements(pyproject)["pyside6"].specifier

    assert Version(spec.version) in PYSIDE_RANGE
    for name in ("pyside6", "pyside6-essentials", "pyside6-addons", "shiboken6"):
        assert Version(lock_versions[name]) in PYSIDE_RANGE, name


def test_lock_matches_the_exact_runtime_pins(pyproject, lock_versions):
    for name, req in runtime_requirements(pyproject).items():
        [spec] = req.specifier
        assert lock_versions[name] == spec.version, name


def test_dev_group_has_the_required_tools(pyproject):
    names = {
        canonicalize_name(Requirement(text).name) for text in pyproject["dependency-groups"]["dev"]
    }

    assert {"pytest", "pytest-qt", "pytest-cov", "ruff", "pyinstaller"} <= names


def test_pyupbit_is_not_used(lock_versions):
    # 2024-06 이후 유지보수 중단(CLAUDE.md).
    assert "pyupbit" not in lock_versions


def test_package_version_matches_pyproject(pyproject):
    assert autotrader.__version__ == pyproject["project"]["version"]
