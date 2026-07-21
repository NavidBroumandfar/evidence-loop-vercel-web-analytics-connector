#!/usr/bin/env python3
"""Security scan: check for forbidden dependencies and network patterns."""

import os
import re
import sys
from pathlib import Path

try:
    import tomllib
except ImportError:  # pragma: no cover - Python 3.10 fallback
    tomllib = None

FORBIDDEN_IMPORTS = [
    r"^\s*import\s+requests\b",
    r"^\s*from\s+requests\b",
    r"^\s*import\s+httpx\b",
    r"^\s*from\s+httpx\b",
    r"^\s*import\s+aiohttp\b",
    r"^\s*from\s+aiohttp\b",
    r"^\s*import\s+urllib3\b",
    r"^\s*from\s+urllib3\b",
    r"^\s*import\s+vercel\b",
    r"^\s*from\s+vercel\b",
    r"^\s*import\s+socket\b",
]

FORBIDDEN_PATTERNS = [
    r"\.connect\(\)",
    r"\.send\(.*\)",
    r"socket\.socket",
    r"subprocess\.(run|call|Popen)\(",
    r"os\.system\(",
    r"eval\(",
    r"exec\(",
    r"__import__\(",
]

EXACT_EXCEPTIONS = {
    "scripts/artifact_smoke.py": [
        r"subprocess\.run\(",
    ],
}

IGNORE_DIRS = {
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".tox",
    "build",
    "dist",
    ".venv",
    "venv",
    "env",
    "node_modules",
}

IGNORE_SUFFIXES = {".pyc", ".pyo", ".pyd", ".so", ".dylib", ".dll"}


def scan_file(path: Path, rel_path_str: str = "", is_allowed: bool | None = None) -> list[str]:
    """Scan a file for forbidden patterns."""
    violations = []

    if path.is_symlink():
        return [f"{path}: Symlink detected"]

    if not path.is_file():
        return []

    try:
        if path.stat().st_mode & 0o444 == 0:
            return [f"{path}: Unreadable file"]
    except OSError:
        return [f"{path}: Unreadable file"]

    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except UnicodeDecodeError:
        return [f"{path}: Non-UTF8 file detected"]
    except Exception:
        return [f"{path}: Unreadable file"]

    # Exceptions are path-locked and match-locked.  ``is_allowed=False`` is a
    # compatibility knob for focused tests and explicitly disables exceptions.
    exact_exceptions = [] if is_allowed is False else EXACT_EXCEPTIONS.get(rel_path_str, [])

    for line_num, line in enumerate(lines, 1):
        for pattern in FORBIDDEN_IMPORTS:
            if re.search(pattern, line):
                violations.append(f"{path}:{line_num}: Forbidden import: {pattern}")

        for pattern in FORBIDDEN_PATTERNS:
            # Check each match individually
            for match in re.finditer(pattern, line):
                matched_text = match.group(0)
                is_excepted = False
                for exc_pattern in exact_exceptions:
                    if re.fullmatch(exc_pattern, matched_text):
                        is_excepted = True
                        break
                if not is_excepted:
                    violations.append(f"{path}:{line_num}: Forbidden pattern: {pattern}")

    return violations


def scan_pyproject(path: Path) -> list[str]:
    """Scan pyproject.toml for forbidden dependencies."""
    violations = []

    if path.is_symlink():
        return [f"{path}: Symlink detected"]

    if not path.exists() or not path.is_file():
        return [f"{path}: Unreadable pyproject"]

    try:
        if path.stat().st_mode & 0o444 == 0:
            return [f"{path}: Unreadable pyproject"]
    except OSError:
        return [f"{path}: Unreadable pyproject"]

    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
    except UnicodeDecodeError:
        return [f"{path}: Non-UTF8 pyproject"]
    except Exception:
        return [f"{path}: Unreadable pyproject"]

    forbidden_deps = ["requests", "httpx", "aiohttp", "urllib3", "socket"]

    if tomllib is not None:
        try:
            tomllib.loads(content)
        except Exception:
            violations.append(f"{path}: Invalid pyproject syntax")

    # Scan dependency arrays lexically so both quoted PEP 508 entries and
    # malformed/bare entries (for example ``dependencies = [requests]``) are
    # detected.  Scope the search to assignments rather than descriptions.
    deps_sections = re.findall(
        r"(?ims)^\s*(?:dependencies|[A-Za-z0-9_.-]+)\s*=\s*\[(.*?)\]",
        content,
    )
    for deps_section in deps_sections:
        for dep in forbidden_deps:
            if re.search(rf"(?<![A-Za-z0-9_.-]){re.escape(dep)}(?![A-Za-z0-9_.-])", deps_section, re.IGNORECASE):
                violations.append(f"{path}: Forbidden dependency: {dep}")

    # A pyproject with an unterminated dependency array is not safe to accept.
    # This also makes scanner behavior fail closed for malformed metadata.
    if "dependencies" in content and not deps_sections:
        violations.append(f"{path}: Invalid dependencies declaration")

    return violations


def main(root: Path | None = None) -> int:
    """Run security scan."""
    root = root or Path(__file__).parent.parent
    violations = []

    pyproject = root / "pyproject.toml"
    violations.extend(scan_pyproject(pyproject))

    for dirpath, dirnames, filenames in os.walk(root):
        # Check links before applying ignore-name filters.  Ignored symlink
        # directories/files must still fail, while real .git remains excluded
        # and is never traversed.
        for dirname in dirnames[:]:
            dir_full = Path(dirpath) / dirname
            if dir_full.is_symlink():
                violations.append(f"{dir_full}: Symlink directory detected")
                dirnames.remove(dirname)

        dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS and not d.endswith(".egg-info")]

        for filename in filenames:
            file_path = Path(dirpath) / filename

            if file_path.is_symlink():
                violations.extend(scan_file(file_path, str(file_path.relative_to(root))))
                continue

            if not filename.endswith(".py"):
                continue

            if file_path.suffix in IGNORE_SUFFIXES:
                continue

            rel_path = file_path.relative_to(root)
            rel_path_str = str(rel_path)

            violations.extend(scan_file(file_path, rel_path_str))

    if violations:
        print("Security scan FAILED:", file=sys.stderr)
        for violation in violations:
            print(f"  {violation}", file=sys.stderr)
        return 1

    print("Security scan PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
