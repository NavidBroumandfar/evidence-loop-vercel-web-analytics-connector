# Releasing

This document describes the release process for the Evidence Loop Vercel Web Analytics Connector.

## Prerequisites

- Python 3.10 or later
- All tests passing
- All verification checks passing

## Release Checklist

### 1. Run All Verification Checks

```bash
# Run tests
python3 -m unittest discover -s tests -v

# Compile check
python3 -m compileall -q src tests scripts

# Security scans
python3 scripts/release_scan.py
python3 scripts/security_scan.py

# Build artifacts
python3 -m build --no-isolation

# Smoke test artifacts
python3 scripts/artifact_smoke.py dist

# Git checks
git diff --check
git status --short
```

All checks must pass with exit code 0.

### 2. Update Version Number

Update the version in:

- `pyproject.toml`
- `src/evidence_loop_vercel_web_analytics/__init__.py`
- `src/evidence_loop_vercel_web_analytics/http.py` (User-Agent)

### 3. Update CHANGELOG.md

Add a new section for the release:

```markdown
## [X.Y.Z] - YYYY-MM-DD

### Added
- New features

### Changed
- Changes to existing features

### Fixed
- Bug fixes

### Security
- Security improvements
```

### 4. Create Git Tag

```bash
git tag -a vX.Y.Z -m "Release vX.Y.Z"
git push origin vX.Y.Z
```

### 5. Build Distribution Artifacts

```bash
rm -rf dist/
python3 -m build
```

This creates:
- `dist/evidence_loop_vercel_web_analytics-X.Y.Z-py3-none-any.whl`
- `dist/evidence_loop_vercel_web_analytics-X.Y.Z.tar.gz`

### 6. Verify Artifacts

```bash
python3 scripts/artifact_smoke.py dist
```

Both wheel and sdist must pass the smoke test.

### 7. PyPI publication gate

The initial source release is a GitHub release with the verified wheel and
sdist attached. Do not upload with a long-lived token or `.pypirc`. PyPI
publication remains gated until an exact GitHub Trusted Publisher identity and
review-protected environment are configured and documented.

### 8. Create GitHub Release

1. Go to the GitHub repository
2. Click "Releases" → "Draft a new release"
3. Select the tag you created
4. Add release notes (copy from CHANGELOG.md)
5. Attach the wheel and sdist files
6. Publish the release

## Post-Release

1. Update version to next development version (e.g., `X.Y.Z+1.dev0`)
2. Commit the version bump
3. Push to main branch

## Security Scanners

Two scanners enforce security boundaries:

### release_scan.py

Checks for credential and private path leakage:
- Bearer tokens
- Vercel project IDs (`prj_...`)
- Vercel team IDs (`team_...`)
- Environment variable references with values
- Private keys and secrets

### security_scan.py

Checks for forbidden dependencies and patterns:
- External HTTP libraries (requests, httpx, aiohttp, urllib3)
- Provider SDKs (vercel)
- Socket operations
- Dangerous functions (eval, exec, subprocess, os.system)

Both scanners must pass with exit code 0.

## Artifact Smoke Test

The `artifact_smoke.py` script:

1. Installs wheel and sdist into isolated virtual environments
2. Tests that the package can be imported
3. Tests that the CLI help command works
4. Tests that the version is accessible

No real network calls or credential access during smoke test.

## Rollback

If a release has issues:

1. Yank the release from PyPI: `twine yank evidence-loop-vercel-web-analytics==X.Y.Z`
2. Create a hotfix branch
3. Fix the issue
4. Release a patch version (X.Y.Z+1)

## Support

Use the GitHub repository's issue tracker for non-sensitive release problems
and its private Security Advisory flow for vulnerabilities.
