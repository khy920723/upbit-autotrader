"""의존성 라이선스 목록을 uv.lock에서 계산하고 문서와 대조한다.

문서: docs/07-security-legal/dependency-licenses.md 의 두 표
(`<!-- license-inventory:runtime:start -->` ~ `:end -->`, dev도 같은 형식)

    uv run python scripts/license_inventory.py           # 문서가 uv.lock과 맞는지 검사(기본)
    uv run python scripts/license_inventory.py --write   # 패키지·버전·플랫폼 칸을 다시 쓴다

--write는 사람이 확인한 라이선스·비고 칸을 그대로 두고, 새 패키지에는 "확인 필요"를 넣는다
(설치된 메타데이터의 License-Expression은 비고에 참고로만 적는다).
"확인 필요"가 남아 있으면 검사(와 tests/unit/test_license_inventory.py)가 실패한다.
의존성을 바꾸면(uv lock) 이 스크립트로 표를 갱신하고 라이선스를 직접 확인해 채운다.
"""

import argparse
import importlib.metadata
import re
import sys
import tomllib
from collections.abc import Callable, Mapping
from pathlib import Path

from packaging.markers import Marker
from packaging.utils import canonicalize_name

ROOT = Path(__file__).resolve().parents[1]
LOCK_PATH = ROOT / "uv.lock"
DOC_PATH = ROOT / "docs" / "07-security-legal" / "dependency-licenses.md"

TABLES = ("runtime", "dev")
PENDING = "확인 필요"
HEADER = "| 패키지 | 버전 | 라이선스 | 설치 플랫폼 | 비고 |\n|---|---|---|---|---|\n"

# 마커 평가 환경. 표의 "설치 플랫폼" 칸은 아래 이름을 이 순서로 쉼표로 잇는다.
_COMMON_ENV = {
    "python_version": "3.13",
    "python_full_version": "3.13.0",
    "implementation_name": "cpython",
    "platform_python_implementation": "CPython",
    "platform_release": "",
    "platform_version": "",
    "extra": "",
}
PLATFORM_ENVS: dict[str, dict[str, str]] = {
    "Windows": _COMMON_ENV
    | {
        "sys_platform": "win32",
        "platform_system": "Windows",
        "os_name": "nt",
        "platform_machine": "AMD64",
    },
    "Linux": _COMMON_ENV
    | {
        "sys_platform": "linux",
        "platform_system": "Linux",
        "os_name": "posix",
        "platform_machine": "x86_64",
    },
    "macOS": _COMMON_ENV
    | {
        "sys_platform": "darwin",
        "platform_system": "Darwin",
        "os_name": "posix",
        "platform_machine": "arm64",
    },
}

# 배포 번들에 들어가도 MIT 앱과 충돌하지 않는 라이선스(SPDX).
# LGPL은 동적 링크·라이브러리 교체 가능·라이선스 원문 동봉을 지키는 조건으로 허용한다.
DISTRIBUTABLE_LICENSES = frozenset(
    {
        "0BSD",
        "Apache-2.0",
        "BSD-2-Clause",
        "BSD-3-Clause",
        "ISC",
        "LGPL-3.0-only",
        "LGPL-3.0-or-later",
        "MIT",
        "MIT-0",
        "MPL-2.0",
        "PSF-2.0",
        "Unlicense",
    }
)

Inventory = dict[str, tuple[str, tuple[str, ...]]]  # 정규화 이름 → (버전, 플랫폼들)
LicenseLookup = Callable[[str], str | None]


# --- uv.lock -----------------------------------------------------------------------


def load_lock(path: Path) -> dict:
    return tomllib.loads(path.read_text(encoding="utf-8"))


def inventory(lock: Mapping, table: str) -> Inventory:
    """표 하나에 들어갈 패키지. runtime은 앱 의존성, dev는 dev 그룹 중 runtime이 아닌 것."""
    packages = {package["name"]: package for package in lock["package"]}
    root = next(p for p in lock["package"] if p["source"].get("editable") == ".")
    starts = {
        "runtime": root.get("dependencies", []),
        "dev": [d for group in root.get("dev-dependencies", {}).values() for d in group],
    }
    found: dict[str, set[str]] = {"runtime": set(), "dev": set()}
    by_platform: dict[str, dict[str, set[str]]] = {"runtime": {}, "dev": {}}
    for kind, start in starts.items():
        for platform, env in PLATFORM_ENVS.items():
            for name in _closure(packages, start, env):
                by_platform[kind].setdefault(name, set()).add(platform)
                found[kind].add(name)
    names = found["runtime"] if table == "runtime" else found["dev"] - found["runtime"]
    order = tuple(PLATFORM_ENVS)
    return {
        name: (
            packages[name]["version"],
            tuple(p for p in order if p in by_platform[table][name]),
        )
        for name in sorted(names)
    }


def _closure(packages: Mapping, start: list, env: Mapping[str, str]) -> set[str]:
    seen: set[str] = set()
    stack = list(start)
    while stack:
        dependency = stack.pop()
        marker = dependency.get("marker")
        if marker and not Marker(marker).evaluate(dict(env)):
            continue
        name = dependency["name"]
        package = packages[name]
        extras = dependency.get("extra", [])
        stack.extend(
            d for extra in extras for d in package.get("optional-dependencies", {}).get(extra, [])
        )
        if name in seen:
            continue
        seen.add(name)
        stack.extend(package.get("dependencies", []))
    return seen


# --- 문서 표 -----------------------------------------------------------------------


def parse_table(doc_text: str, table: str) -> dict[str, list[str]]:
    """정규화 이름 → [표시 이름, 버전, 라이선스, 플랫폼, 비고]."""
    body = _table_block(doc_text, table)
    rows: dict[str, list[str]] = {}
    for line in body.splitlines()[2:]:
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        cells += [""] * (5 - len(cells))
        rows[canonicalize_name(cells[0])] = cells[:5]
    return rows


def _markers(table: str) -> tuple[str, str]:
    return (
        f"<!-- license-inventory:{table}:start -->\n",
        f"<!-- license-inventory:{table}:end -->",
    )


def _table_block(doc_text: str, table: str) -> str:
    start, end = _markers(table)
    try:
        begin = doc_text.index(start) + len(start)
        return doc_text[begin : doc_text.index(end, begin)]
    except ValueError as exc:
        raise ValueError(f"문서에 {table} 표 표시가 없다: {start.strip()} … {end}") from exc


# --- 검사 --------------------------------------------------------------------------


def installed_license_expression(name: str) -> str | None:
    """설치된 패키지 메타데이터의 License-Expression(PEP 639). 없거나 설치 안 됐으면 None."""
    try:
        return importlib.metadata.metadata(name).get("License-Expression")
    except importlib.metadata.PackageNotFoundError:
        return None


def is_allowed_for_distribution(expression: str) -> bool:
    """SPDX 식이 배포 가능한 라이선스로만 이루어지는지(OR는 하나만, AND는 모두)."""
    tokens = re.findall(r"\(|\)|[^\s()]+", expression)
    if not tokens:
        return False
    position = 0

    def parse_or() -> bool:
        nonlocal position
        value = parse_and()
        while position < len(tokens) and tokens[position] == "OR":
            position += 1
            value = parse_and() or value
        return value

    def parse_and() -> bool:
        nonlocal position
        value = parse_atom()
        while position < len(tokens) and tokens[position] == "AND":
            position += 1
            value = parse_atom() and value
        return value

    def parse_atom() -> bool:
        nonlocal position
        if position >= len(tokens):
            raise ValueError("식이 끝났다")
        token = tokens[position]
        position += 1
        if token == "(":
            value = parse_or()
            if position >= len(tokens) or tokens[position] != ")":
                raise ValueError("괄호가 닫히지 않았다")
            position += 1
            return value
        if position < len(tokens) and tokens[position] == "WITH":
            position += 2  # 예외 조항은 권리를 더할 뿐이라 판단에서 뺀다. 기본 라이선스로 본다.
        return token in DISTRIBUTABLE_LICENSES

    try:
        allowed = parse_or()
    except ValueError:
        return False
    return allowed and position == len(tokens)


def check(
    doc_text: str, lock: Mapping, installed_license: LicenseLookup = installed_license_expression
) -> list[str]:
    """문서 표와 uv.lock이 다른 점. 없으면 빈 목록."""
    problems: list[str] = []
    for table in TABLES:
        expected = inventory(lock, table)
        rows = parse_table(doc_text, table)
        for name, (version, platforms) in expected.items():
            row = rows.get(name)
            if row is None:
                problems.append(f"{table}: {name} 행이 없다(uv.lock {version})")
                continue
            _, doc_version, license_text, doc_platforms, _ = row
            if doc_version != version:
                problems.append(f"{table}: {name} 버전 {doc_version} ≠ uv.lock {version}")
            if doc_platforms != ", ".join(platforms):
                problems.append(
                    f"{table}: {name} 플랫폼 '{doc_platforms}' ≠ uv.lock '{', '.join(platforms)}'"
                )
            problems += _license_problems(table, name, license_text, installed_license)
        problems += [f"{table}: {name}는 uv.lock에 없다" for name in rows if name not in expected]
    return problems


def _license_problems(table: str, name: str, text: str, installed: LicenseLookup) -> list[str]:
    if not text or PENDING in text:
        return [f"{table}: {name} 라이선스를 확인해 적어야 한다"]
    problems = []
    if table == "runtime" and not is_allowed_for_distribution(text):
        problems.append(f"{table}: {name} 라이선스 '{text}'는 배포에 쓸 수 없다(MIT 앱과 충돌)")
    metadata = installed(name)
    if metadata and " ".join(metadata.split()) != text:
        problems.append(f"{table}: {name} 라이선스 '{text}' ≠ 설치된 메타데이터 '{metadata}'")
    return problems


# --- 다시 쓰기 ----------------------------------------------------------------------


def rewrite(
    doc_text: str, lock: Mapping, installed_license: LicenseLookup = installed_license_expression
) -> str:
    """표의 패키지·버전·플랫폼을 uv.lock 기준으로 다시 쓴다. 라이선스·비고 칸은 유지한다."""
    for table in TABLES:
        rows = parse_table(doc_text, table)
        lines = []
        for name, (version, platforms) in inventory(lock, table).items():
            old = rows.get(name)
            display = old[0] if old else _display_name(name)
            if old:
                license_text, note = old[2], old[4]
            else:
                # 메타데이터는 참고로만 비고에 적는다. 라이선스 칸은 사람이 확인해 채운다.
                hint = installed_license(name)
                license_text, note = PENDING, f"메타데이터: {hint}" if hint else ""
            lines.append(
                f"| {display} | {version} | {license_text} | {', '.join(platforms)} | {note} |\n"
            )
        start, end = _markers(table)
        begin = doc_text.index(start)
        finish = doc_text.index(end, begin)
        doc_text = doc_text[:begin] + start + HEADER + "".join(lines) + doc_text[finish:]
    return doc_text


def _display_name(name: str) -> str:
    try:
        return importlib.metadata.metadata(name)["Name"]
    except importlib.metadata.PackageNotFoundError:
        return name


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--write", action="store_true", help="문서의 표를 uv.lock 기준으로 다시 쓴다"
    )
    args = parser.parse_args(argv)
    lock = load_lock(LOCK_PATH)
    doc_text = DOC_PATH.read_text(encoding="utf-8")
    if args.write:
        doc_text = rewrite(doc_text, lock)
        DOC_PATH.write_text(doc_text, encoding="utf-8")
        print(f"{DOC_PATH.relative_to(ROOT)}를 다시 썼다.")
    problems = check(doc_text, lock)
    for problem in problems:
        print(problem)
    if not problems:
        print("의존성 라이선스 목록이 uv.lock과 맞다.")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
