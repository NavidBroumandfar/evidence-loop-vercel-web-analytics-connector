# Agent Instructions

Instructions for AI agents working on this codebase.

## Project Overview

Evidence Loop Vercel Web Analytics Connector - a stdlib-only Python package that collects visits/count data from Vercel Web Analytics and emits Connector Exchange Envelope v1 JSON.

## Critical Constraints

1. **Stdlib only**: No external runtime dependencies. No requests, httpx, aiohttp, urllib3, or provider SDKs.
2. **No network calls in tests**: All tests must use fake transports with synthetic data.
3. **Credential isolation**: Credentials (VERCEL_TOKEN, VERCEL_PROJECT_ID, VERCEL_TEAM_ID) must never appear in output, logs, errors, or persisted artifacts.
4. **Pinned endpoint**: HTTP transport is pinned to `https://api.vercel.com/v1/query/web-analytics/visits/count`. Do not make the origin configurable.
5. **No file path options**: CLI exposes no output/input path options to eliminate path traversal and symlink surfaces.
6. **Fail closed**: All validation failures produce structured errors with no envelope. Never fabricate partial data.
7. **Explicit site binding**: `VERCEL_SITE_URL` is required and must
   canonicalize to the exact public `site_url` before transport. Project and
   team identifiers remain request-only and never cross into the envelope.

## Testing

Run all tests:
```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

All tests must pass without network access. Use `FakeTransport` from `tests/test_http.py` as a reference.

## Verification

Before committing, run the offline verification checks:
```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
python3 -m compileall -q src tests scripts
python3 scripts/release_scan.py
python3 scripts/security_scan.py
git diff --check
git status --short
```

Artifact smoke tests are intentionally not part of the offline test run; run
them only when an explicitly authorized artifact has already been produced.

## Code Style

- Use type hints throughout
- Prefer dataclasses for immutable structures
- Use fixed error codes and messages (see `errors.py`)
- Keep functions small and focused
- Document security-critical code with comments

## Security Scanning

Two scanners enforce security boundaries:

1. **release_scan.py**: Checks for credential and private path leakage
2. **security_scan.py**: Checks for forbidden dependencies and network patterns

Both must pass before release.

## Architecture

See `docs/architecture.md` for detailed architecture documentation.

## Durable Gotchas

### Test Transport Guard (Critical)

Every call to `collect()` in tests MUST include `transport=FakeTransport(...)`.
The only exception is the keyword-only TypeError test, which passes a fake
transport as a positional argument to verify that the TypeError is raised
before transport is used.  The CLI and connector test modules install a
temporary `UrllibTransport.get` guard for their own module suite and restore
the original method during teardown so HTTP tests remain isolated.

### Process Incidents Log

1. **Unauthorized build-tool install**: A temporary `build` environment
   installed `setuptools` and `wheel` contrary to the stdlib/offline contract.
   It was not used for the current verification run.
2. **Unauthorized test path**: `tests/test_adversarial.py` was created outside
   the authorized allowlist and subsequently removed.
3. **Accidental GET 403**: One test reached the pinned Vercel endpoint and
   received HTTP 403 before the transport guard and fake-transport audit were
   tightened.
4. **Unauthorized audit path**: `scripts/ast_audit.py` was created outside
   the authorized file set and has been removed; the pre-test audit is now an
   inline AST check.

**Lesson**: Always verify test isolation before execution. Use module-level
guards and an inline AST audit to prevent accidental network calls.

## Questions?

If you're unsure about a security boundary or constraint, err on the side of caution and ask for clarification.
