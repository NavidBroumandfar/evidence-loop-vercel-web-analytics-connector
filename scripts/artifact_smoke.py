#!/usr/bin/env python3
"""Artifact smoke test: install and verify wheel/sdist."""

import os
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path

EXPECTED_NAME = "evidence-loop-vercel-web-analytics-connector"
EXPECTED_VERSION = "0.1.0"
PACKAGE_DIR = "evidence_loop_vercel_web_analytics"


def _metadata_value(metadata: str, field: str) -> str | None:
    """Return an exact single-line core-metadata field value."""
    prefix = f"{field}:"
    for line in metadata.splitlines():
        if line.startswith(prefix):
            return line[len(prefix):].strip()
    return None


def _check_metadata(metadata: str) -> bool:
    """Validate exact distribution name/version from artifact metadata."""
    name = _metadata_value(metadata, "Name")
    version = _metadata_value(metadata, "Version")
    if name != EXPECTED_NAME:
        print(f"    FAILED: Metadata Name must be {EXPECTED_NAME!r}", file=sys.stderr)
        return False
    if version != EXPECTED_VERSION:
        print(f"    FAILED: Metadata Version must be {EXPECTED_VERSION!r}", file=sys.stderr)
        return False
    return True


def sanitize_env() -> dict:
    """Create sanitized environment for child processes."""
    env = os.environ.copy()
    for key in [
        "VERCEL_TOKEN",
        "VERCEL_PROJECT_ID",
        "VERCEL_TEAM_ID",
        "VERCEL_SITE_URL",
        "PYTHONPATH",
        "PIP_INDEX_URL",
        "PIP_EXTRA_INDEX_URL",
        "PIP_CONFIG_FILE",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
    ]:
        env.pop(key, None)
    return env


def test_wheel_contents(wheel_path: Path) -> bool:
    """Verify wheel contains expected files."""
    print(f"  Checking wheel contents...")
    try:
        with zipfile.ZipFile(wheel_path, 'r') as zf:
            names = set(zf.namelist())
            required = {
                f'{PACKAGE_DIR}/__init__.py',
                f'{PACKAGE_DIR}/__main__.py',
                f'{PACKAGE_DIR}/cli.py',
                f'{PACKAGE_DIR}/connector.py',
                f'{PACKAGE_DIR}/errors.py',
                f'{PACKAGE_DIR}/http.py',
                f'{PACKAGE_DIR}/safety.py',
            }
            missing = sorted(required - names)
            if missing:
                print(f"    FAILED: Missing exact wheel members: {', '.join(missing)}", file=sys.stderr)
                return False

            metadata_members = sorted(
                name for name in names if name.endswith('.dist-info/METADATA')
            )
            if len(metadata_members) != 1:
                print("    FAILED: Expected exactly one wheel METADATA member", file=sys.stderr)
                return False
            metadata = zf.read(metadata_members[0]).decode('utf-8')
            if not _check_metadata(metadata):
                return False
            print(f"    PASSED: All required files present")
            return True
    except (UnicodeDecodeError, OSError, zipfile.BadZipFile) as e:
        print(f"    FAILED: Could not read wheel: {e}", file=sys.stderr)
        return False


def test_sdist_contents(sdist_path: Path) -> bool:
    """Verify sdist contains expected files."""
    print(f"  Checking sdist contents...")
    try:
        with tarfile.open(sdist_path, 'r:gz') as tf:
            names = tf.getnames()
            roots = {name.split('/', 1)[0] for name in names if '/' in name}
            if len(roots) != 1:
                print("    FAILED: Expected one sdist root", file=sys.stderr)
                return False
            root = next(iter(roots))
            required = [
                'README.md',
                'LICENSE',
                'CHANGELOG.md',
                'SECURITY.md',
                'AGENTS.md',
                'pyproject.toml',
                'MANIFEST.in',
            ]
            for req in required:
                if f'{root}/{req}' not in names:
                    print(f"    FAILED: Missing exact sdist member {req}", file=sys.stderr)
                    return False

            required_dirs = ['docs', 'examples', 'scripts', 'tests']
            for req_dir in required_dirs:
                if f'{root}/{req_dir}' not in names and not any(name.startswith(f'{root}/{req_dir}/') for name in names):
                    print(f"    FAILED: Missing {req_dir}/", file=sys.stderr)
                    return False

            canonical_metadata = f'{root}/PKG-INFO'
            if names.count(canonical_metadata) != 1:
                print("    FAILED: Expected exactly one canonical root PKG-INFO member", file=sys.stderr)
                return False
            metadata_file = tf.extractfile(canonical_metadata)
            if metadata_file is None:
                print("    FAILED: Could not read sdist PKG-INFO", file=sys.stderr)
                return False
            metadata = metadata_file.read().decode('utf-8')
            if not _check_metadata(metadata):
                return False

            print(f"    PASSED: All required files present")
            return True
    except (UnicodeDecodeError, OSError, tarfile.TarError) as e:
        print(f"    FAILED: Could not read sdist: {e}", file=sys.stderr)
        return False


def test_artifact(artifact_path: Path, env: dict) -> bool:
    """Test a single artifact."""
    print(f"Testing {artifact_path.name}...")

    if artifact_path.suffix == '.whl':
        if not test_wheel_contents(artifact_path):
            return False
    elif artifact_path.suffix == '.gz':
        if not test_sdist_contents(artifact_path):
            return False

    with tempfile.TemporaryDirectory() as tmpdir:
        # Keep each artifact in its own isolated target while using the
        # explicitly selected current Python toolchain.  A nested venv's
        # ``--system-site-packages`` cannot see controller-venv build tools.
        target_dir = Path(tmpdir) / f"target-{artifact_path.stem}"

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--target",
                str(target_dir),
                "--no-index",
                "--no-deps",
                "--no-build-isolation",
                str(artifact_path),
            ],
            capture_output=True,
            text=True,
            env=env,
        )
        if result.returncode != 0:
            print(f"  FAILED: Could not install artifact: {result.stderr}", file=sys.stderr)
            return False

        isolated_env = dict(env)
        isolated_env["PYTHONPATH"] = str(target_dir)

        result = subprocess.run(
            [sys.executable, "-c", "import evidence_loop_vercel_web_analytics; print(evidence_loop_vercel_web_analytics.__version__)"],
            capture_output=True,
            text=True,
            env=isolated_env,
        )
        if result.returncode != 0:
            print(f"  FAILED: Could not import: {result.stderr}", file=sys.stderr)
            return False

        version = result.stdout.strip()
        if version != EXPECTED_VERSION:
            print(f"  FAILED: Installed version must be {EXPECTED_VERSION!r}", file=sys.stderr)
            return False
        print(f"  PASSED: Version {version}")

        result = subprocess.run(
            [sys.executable, "-m", "evidence_loop_vercel_web_analytics", "--help"],
            capture_output=True,
            text=True,
            env=isolated_env,
        )
        if result.returncode != 0:
            print(f"  FAILED: Help command failed: {result.stderr}", file=sys.stderr)
            return False

        print(f"  PASSED: Help command works")

    return True


def main() -> int:
    """Run artifact smoke tests."""
    if len(sys.argv) < 2:
        print("Usage: artifact_smoke.py <dist_dir>", file=sys.stderr)
        return 1

    dist_dir = Path(sys.argv[1])
    if not dist_dir.exists():
        print(f"Dist directory not found: {dist_dir}", file=sys.stderr)
        return 1

    wheels = list(dist_dir.glob("*.whl"))
    sdists = list(dist_dir.glob("*.tar.gz"))

    if len(wheels) != 1:
        print(f"Expected exactly 1 wheel, found {len(wheels)}", file=sys.stderr)
        return 1

    if len(sdists) != 1:
        print(f"Expected exactly 1 sdist, found {len(sdists)}", file=sys.stderr)
        return 1

    artifacts = wheels + sdists
    print(f"Found {len(artifacts)} artifacts")

    env = sanitize_env()

    all_passed = True
    for artifact in artifacts:
        if not test_artifact(artifact, env):
            all_passed = False

    if not all_passed:
        print("Artifact smoke test FAILED", file=sys.stderr)
        return 1

    print("Artifact smoke test PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
