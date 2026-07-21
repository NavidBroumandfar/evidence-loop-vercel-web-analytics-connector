# Architecture

## Overview

The Evidence Loop Vercel Web Analytics Connector is a stdlib-only Python package that collects visits/count data from Vercel Web Analytics and emits Connector Exchange Envelope v1 JSON.

## Design Principles

1. **Stdlib only**: Zero external runtime dependencies
2. **Fail closed**: Validation failures produce errors, never partial data
3. **Credential isolation**: Secrets never enter output or artifacts
4. **Fakeable transport**: All network I/O is injectable for testing
5. **Deterministic output**: Compact sorted JSON with SHA-256 lineage
6. **No path surface**: CLI has no file path options, eliminating traversal attacks

## Module Structure

```
src/evidence_loop_vercel_web_analytics/
├── __init__.py       # Public API exports
├── __main__.py       # CLI entry point for python -m
├── cli.py            # CLI argument parsing and execution
├── connector.py      # Core collection logic
├── errors.py         # Custom exceptions with fixed codes
├── http.py           # HTTP transport abstraction and implementation
└── safety.py         # Validation and sanitization
```

### errors.py

Defines custom exceptions with fixed error codes:

- `ConnectorError`: Base exception
- `ValidationError`: Input validation failed
- `ProviderUnavailableError`: Provider service unavailable
- `PartialResponseError`: Provider response missing metrics
- `SecurityError`: Security boundary violation
- `TransportError`: HTTP transport failure

All exceptions carry a `code` and `message` for structured error reporting. Error messages never contain credentials, URLs, parameter values, or private identifiers.

### safety.py

Implements validation and sanitization:

- `validate_site_url()`: Canonical HTTPS DNS origin validation using ipaddress module for IP literal rejection, DNS length bounds, and label validation
- `validate_site_id()`: Lowercase alphanumeric + hyphen, max 63 characters
- `validate_scope_ref()`: Bounded safe public identifier validation
- `validate_timestamp()`: Canonical UTC ISO-8601 Z format (YYYY-MM-DDTHH:MM:SSZ)
- `validate_now()`: Timezone-aware UTC datetime validation with microsecond truncation
- `validate_window()`: Bounded window validation with future check
- `validate_token()`: Bounded non-whitespace opaque text validation
- `validate_project_id()`: Strict prj_ prefix validation
- `validate_team_id()`: Strict team_ prefix validation
- `validate_stale_threshold()`: Nonnegative integer validation (rejects bool)
- `check_credential_leakage()`: Detect credential patterns and sensitive value overlap
- `serialize_envelope()`: Compact sorted UTF-8 JSON serialization with sanitization

### http.py

Implements HTTP transport with strict security:

- `HTTPResponse`: Immutable response dataclass (status, headers, body only)
- `Transport`: Abstract transport interface
- `UrllibTransport`: Real urllib implementation with no-redirect opener
- `NoRedirectHandler`: Custom handler that refuses to follow redirects
- `parse_response()`: JSON parsing with strict validation including size enforcement
- `check_nesting_depth()`: Reject excessive nesting

Key constraints:
- Pinned to `https://api.vercel.com/v1/query/web-analytics/visits/count`
- GET method only
- Redirects disabled via custom opener (3xx rejected before following)
- Only Authorization, Accept, User-Agent headers allowed
- Response body bounded at 1 MiB (enforced in both transport and parse_response)
- Query parameters encoded with urllib.parse.urlencode
- SHA-256 computed in connector, not in transport
- Content-Type checked case-insensitively with optional parameters
- Error messages never reflect sensitive data

### connector.py

Core collection logic:

- `collect()`: Main entry point with keyword-only `now` parameter for deterministic testing
- Validates public inputs (site_url, site_id, scope_ref, window, stale_threshold)
- Validates and normalizes `now` parameter if provided
- Reads and validates environment variables (credentials)
- Requires the process-only `VERCEL_SITE_URL` operator binding to match the
  canonical public `site_url` before transport
- Constructs query parameters with urllib.parse.urlencode
- Executes request via transport
- Validates response body size before parsing
- Validates response structure (version, query, data)
- Computes SHA-256 from response.body
- Builds envelope with lineage and provider_response_sha256
- Calls serialize_envelope with sensitive values to enforce credential isolation
- Returns envelope dict

Response validation:
- Top-level keys must be exactly: version, query, data
- version must be integer 1 (bool rejected)
- query must contain exactly: since, until (echo validation)
- projectId and teamId are request-only, not in response query
- data must contain exactly: pageviews, visitors
- Missing metrics: PartialResponseError
- Extra keys in data: ProviderUnavailableError
- Metrics must be non-negative integers (bool, float, negative rejected)
- Metrics must not exceed JSON safe integer (9007199254740991)

### cli.py

CLI interface:

- Custom `_SafeArgumentParser` that raises private `_ParseError` instead of printing usage
- Non-reflective error messages (fixed text, no argument echoing)
- Uses json.dumps for all structured error output
- Validates inputs before reading environment
- Reads environment variables after validation
- Uses serialize_envelope helper for output
- Emits JSON to stdout (envelope) or stderr (error)
- Exit codes: 0 (success), 1 (validation), 2 (partial/arguments), 3 (unavailable), 4 (security), 5 (transport)

## Data Flow

```
┌─────────────┐
│   CLI Args  │
└──────┬──────┘
       │
       ▼
┌─────────────┐
│  Validate   │──► ValidationError
│  Public     │
└──────┬──────┘
       │
       ▼
┌─────────────┐
│  Validate & │
│  Normalize  │──► ValidationError
│  now        │
└──────┬──────┘
       │
       ▼
┌─────────────┐
│  Read &     │
│  Validate   │──► ValidationError
│  Env Vars   │
└──────┬──────┘
       │
       ▼
┌─────────────┐
│  Construct  │
│  Query      │
└──────┬──────┘
       │
       ▼
┌─────────────┐
│  Transport  │──► ProviderUnavailableError
│  GET        │
└──────┬──────┘
       │
       ▼
┌─────────────┐
│  Check Size │──► ProviderUnavailableError
└──────┬──────┘
       │
       ▼
┌─────────────┐
│  Parse &    │──► TransportError
│  Validate   │
└──────┬──────┘
       │
       ▼
┌─────────────┐
│  Validate   │──► PartialResponseError / ProviderUnavailableError
│  Metrics    │
└──────┬──────┘
       │
       ▼
┌─────────────┐
│  Compute    │
│  SHA-256    │
└──────┬──────┘
       │
       ▼
┌─────────────┐
│  Build      │
│  Envelope   │
└──────┬──────┘
       │
       ▼
┌─────────────┐
│  Serialize  │──► SecurityError
│  & Validate │
│  Secrets    │
└──────┬──────┘
       │
       ▼
┌─────────────┐
│  Return     │
│  Envelope   │
└─────────────┘
```

## Security Architecture

### Credential Isolation

Credentials are read from environment variables only at collection time and are never written to:
- Standard output (envelope)
- Standard error (error messages)
- Logs
- Exception messages
- Persisted artifacts

All output is scanned for credential patterns and sensitive value overlap before emission. If any public field (site_id, scope_ref, etc.) contains an actual credential value, the envelope is rejected and no output is produced.

### Network Constraints

- Stdlib only (no external HTTP libraries)
- Pinned endpoint (no configurable origin)
- Redirects disabled via custom opener (not just rejected after following)
- Authorization headers not forwarded on redirects
- Response size bounded before parsing
- Query parameters properly encoded

### Validation Strategy

All inputs are validated before use:
- Public inputs: site_url, site_id, scope_ref, window, stale_threshold
- Process-only inputs: token, projectId, optional teamId, and the public
  `VERCEL_SITE_URL` binding
- now parameter: timezone-aware UTC, normalized to whole seconds
- Response: version, query, data structure and values
- Output: credential patterns, sensitive values, size

### Path/Symlink Surface

The CLI has no input or output path options. The path and symlink surface is absent by construction:
- No file reading or writing
- No path arguments
- Output to stdout only
- No traversal or symlink following possible

### Fail-Closed Design

Any validation failure halts execution and produces a structured error:
- No partial envelopes
- No fabricated data
- No silent degradation
- Stdout remains empty on all failures

## Timestamp Handling

### Microseconds Truncation

Microseconds are truncated (rounded down to whole seconds) for deterministic output. This decision ensures:

1. **Deterministic testing**: Two calls with the same `now` parameter produce identical JSON
2. **Canonical format**: All timestamps use `YYYY-MM-DDTHH:MM:SSZ` without subsecond ambiguity
3. **Consistent freshness**: Freshness calculations use whole-second precision

The truncation is documented and tested. The `collected_at` field always uses whole-second precision via `strftime("%Y-%m-%dT%H:%M:%SZ")`.

### now Parameter

The `now` parameter is keyword-only and must be a timezone-aware UTC datetime:

```python
from datetime import datetime, timezone

fixed_time = datetime(2025, 1, 2, 12, 0, 0, tzinfo=timezone.utc)
envelope = collect(..., now=fixed_time)
```

When `now` is provided:
- It is validated as timezone-aware and UTC
- Microseconds are truncated
- It is used for window validation (future check)
- It is used for `collected_at` timestamp
- It is used for freshness calculation

When `now` is not provided:
- Current UTC time is used
- Microseconds are truncated
- Same validation and usage as above

## Lineage Format

The `lineage` field is a nonempty list of objects describing processing stages:

```json
"lineage": [
  {
    "stage": "provider-response",
    "reference": "provider_response_sha256",
    "method": "sha256"
  }
]
```

- `stage`: Processing stage identifier
- `reference`: Field name containing the referenced value (literal string, not the value itself)
- `method`: Method used to produce the referenced value

The `reference` field contains the literal string `"provider_response_sha256"`, which is the name of the field that contains the actual SHA-256 digest. This allows consumers to programmatically locate the referenced value.

## Testing Strategy

All tests use fake transports:
- `FakeTransport` class implements `Transport` interface
- Synthetic response data in `tests/fixtures/`
- No real network calls
- Comprehensive coverage of success and failure paths
- Deterministic testing via `now` parameter injection
- Security-boundary tests for all validation and scanner paths
- Scanner tests using temporary isolated trees

## Extensibility

### Custom Transports

Inject custom transports for testing or alternative implementations:

```python
from evidence_loop_vercel_web_analytics import collect, Transport

class MyTransport(Transport):
    def get(self, url, headers, params):
        # Custom implementation
        pass

envelope = collect(..., transport=MyTransport())
```

### Deterministic Testing

Use the `now` parameter for deterministic testing:

```python
from datetime import datetime, timezone

fixed_time = datetime(2025, 1, 2, 12, 0, 0, tzinfo=timezone.utc)
envelope = collect(..., now=fixed_time)
```

### Future Connectors

This architecture can be replicated for other providers:
- Same envelope format
- Same validation strategy
- Same security boundaries
- Different endpoint and response parsing
