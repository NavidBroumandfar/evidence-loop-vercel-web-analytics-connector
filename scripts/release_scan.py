#!/usr/bin/env python3
"""Release scan: check for credential and private path leakage."""

import os
import re
import sys
from pathlib import Path

FORBIDDEN_PATTERNS = [
    r"Bearer\s+[A-Za-z0-9\-._~+/]{32,}",
    r"token\s*=\s*['\"][A-Za-z0-9\-._~+/]{32,}['\"]",
    r"prj_[a-zA-Z0-9]{16,}",
    r"team_[a-zA-Z0-9]{16,}",
    r"VERCEL_TOKEN\s*=\s*['\"][^'\"]{8,}['\"]",
    r"VERCEL_PROJECT_ID\s*=\s*['\"]prj_[a-zA-Z0-9]{16,}['\"]",
    r"VERCEL_TEAM_ID\s*=\s*['\"]team_[a-zA-Z0-9]{16,}['\"]",
    r"secret[_-]?key\s*=\s*['\"][^'\"]{8,}['\"]",
    r"private[_-]?key\s*=\s*['\"][^'\"]{8,}['\"]",
]

SYNTHETIC_PATTERNS = [
    r"prj_example123",
    r"team_example123",
    r"test_token_123",
    r"prj_123",
    r"team_123",
    r"test_token_123",
    r"your-token",
    r"prj_\.\.\.",
    r"team_\.\.\.",
    r"mysecrettoken123",
    r"prj_abc123def456",
    r"VERCEL_TOKEN\s*=\s*['\"]your-token['\"]",
    r"VERCEL_PROJECT_ID\s*=\s*['\"]prj_\.\.\.['\"]",
    r"VERCEL_TEAM_ID\s*=\s*['\"]team_\.\.\.['\"]",
    r"/" + r"Users/example/[^\s\"']+",
    r"/" + r"home/example/[^\s\"']+",
    r"[A-Za-z]:[\\/]Users[\\/]example[\\/][^\s\"']+",
    r"\\\\server[\\/]Users[\\/]example[\\/][^\s\"']+",
]

PRIVATE_PATH_PATTERNS = [
    r"/" + r"Users/[^\s\"']+",
    r"/" + r"home/[^\s\"']+",
    r"[A-Za-z]:[\\/]Users[\\/][^\s\"']+",
    r"\\\\[^\\/\s]+[\\/]Users[\\/][^\s\"']+",
    r"\\\\Users[\\/][^\s\"']+",
]

FORBIDDEN_PATTERNS.extend(PRIVATE_PATH_PATTERNS)

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


def is_synthetic_match(matched_text: str) -> bool:
    """Check if the exact matched text is synthetic."""
    for synthetic_pattern in SYNTHETIC_PATTERNS:
        if re.fullmatch(synthetic_pattern, matched_text):
            return True
    return False


def scan_file(path: Path) -> list[str]:
    """Scan a file for forbidden patterns."""
    violations = []

    if path.is_symlink():
        return [f"{path}: Symlink detected"]

    if not path.exists() or not path.is_file():
        return [f"{path}: Unreadable file"]

    try:
        if path.stat().st_mode & 0o444 == 0:
            return [f"{path}: Unreadable file"]
    except Exception:
        return [f"{path}: Unreadable file"]

    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except UnicodeDecodeError:
        return [f"{path}: Non-UTF8 file detected"]
    except OSError:
        return [f"{path}: Unreadable file"]

    for line_num, line in enumerate(lines, 1):
        for pattern in FORBIDDEN_PATTERNS:
            # Iterate all matches on the line
            for match in re.finditer(pattern, line, re.IGNORECASE):
                matched_text = match.group(0)
                if not is_synthetic_match(matched_text):
                    violations.append(f"{path}:{line_num}: Found forbidden pattern: {pattern}")

    return violations


def main(root: Path | None = None) -> int:
    """Run release scan."""
    root = root or Path(__file__).parent.parent
    violations = []

    for dirpath, dirnames, filenames in os.walk(root):
        # Inspect links before ignore-name filtering.  A symlink named .venv,
        # build, or another ignored directory is still a release violation;
        # removing it afterward prevents os.walk from traversing it.
        for dirname in dirnames[:]:
            dir_full = Path(dirpath) / dirname
            if dir_full.is_symlink():
                violations.append(f"{dir_full}: Symlink directory detected")
                dirnames.remove(dirname)

        dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS and not d.endswith(".egg-info")]

        for filename in filenames:
            file_path = Path(dirpath) / filename

            if file_path.is_symlink():
                violations.extend(scan_file(file_path))
                continue

            if file_path.suffix in IGNORE_SUFFIXES:
                continue

            violations.extend(scan_file(file_path))

    if violations:
        print("Release scan FAILED:", file=sys.stderr)
        for violation in violations:
            print(f"  {violation}", file=sys.stderr)
        return 1

    print("Release scan PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
