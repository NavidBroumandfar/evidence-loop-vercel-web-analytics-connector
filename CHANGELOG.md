# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## 0.1.0 - 2026-07-22

Published as a GitHub source release with verified wheel and sdist artifacts.
PyPI publication remains separately gated.

### Added

- Initial public release
- Vercel Web Analytics visits/count connector
- Library API with `collect()` function
- CLI with `python -m` and console script entry points
- Fakeable transport interface for testing
- Strict security boundaries (no credentials in output)
- SHA-256 lineage tracking of provider responses
- Connector Exchange Envelope v1 format
- Comprehensive validation and error handling
- Release and security scanning scripts
- Artifact smoke tests for wheel and sdist
- Complete documentation and examples
- Explicit process-only `VERCEL_SITE_URL` project/site binding with
  fail-closed missing and mismatch handling before transport
- Commit-pinned, least-privilege GitHub CI for Python 3.10-3.13, artifact
  smoke tests, release/security scans, and secret scanning

### Fixed

- Accept Vercel's canonical zero-millisecond `.000Z` timestamp echoes while
  continuing to reject nonzero fractional values, alternate offsets, numeric
  timestamps, and semantic drift

### Validation

- One initial bounded live request exposed the canonical timestamp-echo
  difference, one structure-only diagnostic request confirmed the current
  response contract, and one repaired bounded request produced a sanitized
  envelope accepted by the public core with `external_calls=0`. None was
  retried internally, and no live data or provider identifier entered Git.
