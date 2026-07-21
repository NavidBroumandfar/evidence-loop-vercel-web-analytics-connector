# Connector Contract

## Connector Exchange Envelope v1

This connector emits Connector Exchange Envelope v1 JSON, compatible with the public evidence-loop contract.

## Envelope Schema

```json
{
  "schema_version": "1",
  "source": "evidence-loop-vercel-web-analytics",
  "provider": "vercel-web-analytics",
  "site_url": "https://example.com",
  "site_id": "my-site",
  "scope_ref": "production",
  "observation_window": {
    "start": "2025-01-01T00:00:00Z",
    "end": "2025-01-02T00:00:00Z"
  },
  "collected_at": "2025-01-02T12:00:00Z",
  "grain": "site-level",
  "completeness": "complete",
  "freshness": "fresh",
  "uncertainty": "low",
  "limitations": "Vercel Web Analytics visits/count endpoint...",
  "lineage": [
    {
      "stage": "provider-response",
      "reference": "provider_response_sha256",
      "method": "sha256"
    }
  ],
  "measures": {
    "pageviews": {
      "unit": "count",
      "value": 1234
    },
    "visitors": {
      "unit": "count",
      "value": 567
    }
  },
  "provider_response_sha256": "abc123def456..."
}
```

## Field Definitions

### Required Fields

| Field | Type | Description |
|-------|------|-------------|
| `schema_version` | string | Envelope schema version (always `"1"`) |
| `source` | string | Connector source identifier (always `evidence-loop-vercel-web-analytics`) |
| `provider` | string | Analytics provider identifier (always `vercel-web-analytics`) |
| `site_url` | string | Canonical HTTPS origin of the site (lowercase, no trailing slash) |
| `site_id` | string | Public site identifier (lowercase alphanumeric + hyphen, max 63) |
| `scope_ref` | string | Public scope reference (bounded safe identifier) |
| `observation_window` | object | Time window with `start` and `end` (UTC ISO-8601 Z) |
| `collected_at` | string | Collection timestamp (UTC ISO-8601 Z, whole seconds) |
| `grain` | string | Data granularity (always `site-level`) |
| `completeness` | string | Data completeness (always `complete`) |
| `freshness` | string | Data freshness (`fresh` or `stale`) |
| `uncertainty` | string | Data uncertainty (always `low`) |
| `limitations` | string | Human-readable description of data limitations |
| `lineage` | array | Nonempty list of lineage objects |
| `measures` | object | Collected metrics with `unit` and `value` |
| `provider_response_sha256` | string | SHA-256 hash of raw provider response |

### Lineage

The `lineage` field is a nonempty list of objects. Each object describes a processing stage:

```json
{
  "stage": "provider-response",
  "reference": "provider_response_sha256",
  "method": "sha256"
}
```

- `stage`: Processing stage identifier (e.g., `"provider-response"`)
- `reference`: Field name containing the referenced value (e.g., `"provider_response_sha256"`)
- `method`: Method used (e.g., `"sha256"`)

The `reference` field contains the literal field name, not the digest value itself.

### Measures

The `measures` object contains exactly two metrics:

- `pageviews`: Total page views (unit: `count`, value: non-negative integer)
- `visitors`: Unique visitors (unit: `count`, value: non-negative integer)

Both metrics are required. Missing either metric results in a partial-response failure with no envelope. Extra keys result in an invalid provider response failure.

## Freshness Determination

Freshness is determined by comparing the `end` timestamp to the collection time:

- `fresh`: `end` is within the stale threshold (default: 24 hours)
- `stale`: `end` is beyond the stale threshold

A valid old window is explicitly marked as `stale` but still produces a complete envelope.

The connector bounds each observation window to a maximum duration of 31 days;
exactly 31 days is accepted. Longer windows fail with `INVALID_WINDOW` before
provider collection.

## Timestamp Handling

All timestamps are canonical UTC ISO-8601 Z format: `YYYY-MM-DDTHH:MM:SSZ`

Microseconds are truncated (rounded down to whole seconds) for deterministic output. The `collected_at` field always uses whole-second precision.

## Error Format

When collection fails, the connector emits a structured error to stderr:

```json
{"error":{"code":"INVALID_SITE_URL","message":"Must be HTTPS"}}
```

### Error Codes

| Code | Description | Exit Code |
|------|-------------|-----------|
| `INVALID_ARGUMENTS` | CLI argument parsing failed | 2 |
| `INVALID_SITE_URL` | Site URL validation failed | 1 |
| `INVALID_SITE_ID` | Site ID validation failed | 1 |
| `INVALID_SCOPE_REF` | Scope reference validation failed | 1 |
| `INVALID_SINCE` | Since timestamp validation failed | 1 |
| `INVALID_UNTIL` | Until timestamp validation failed | 1 |
| `INVALID_WINDOW` | Window validation failed | 1 |
| `INVALID_STALE_THRESHOLD` | Stale threshold validation failed | 1 |
| `INVALID_TOKEN` | Token validation failed | 1 |
| `INVALID_PROJECT_ID` | Project ID validation failed | 1 |
| `INVALID_TEAM_ID` | Team ID validation failed | 1 |
| `INVALID_NOW` | Now parameter validation failed | 1 |
| `MISSING_PROJECT_ID` | VERCEL_PROJECT_ID not set | 1 |
| `MISSING_TOKEN` | VERCEL_TOKEN not set | 1 |
| `MISSING_SITE_BINDING` | VERCEL_SITE_URL not set | 1 |
| `SITE_BINDING_MISMATCH` | Configured site binding does not match `site_url` | 1 |
| `MISSING_METRICS` | Response missing required metrics | 2 |
| `NON_200_STATUS` | Provider returned non-200 status | 3 |
| `INVALID_RESPONSE` | Response structure invalid | 3 |
| `INVALID_RESPONSE_KEYS` | Response has unexpected keys | 3 |
| `INVALID_VERSION` | Response version != 1 | 3 |
| `INVALID_QUERY` | Query structure invalid | 3 |
| `QUERY_MISMATCH` | Query echo mismatch | 3 |
| `INVALID_DATA` | Data structure invalid | 3 |
| `INVALID_METRIC_TYPE` | Metric is not integer | 3 |
| `INVALID_METRIC_VALUE` | Metric is negative or overlarge | 3 |
| `REDIRECT_REFUSED` | Provider returned redirect | 3 |
| `HTTP_ERROR` | HTTP error | 3 |
| `NETWORK_ERROR` | Network error | 3 |
| `RESPONSE_TOO_LARGE` | Response exceeds 1 MiB | 3 |
| `CREDENTIAL_LEAK` | Credential pattern in output | 4 |
| `OUTPUT_TOO_LARGE` | Output exceeds 1 MiB | 4 |
| `WRONG_URL` | Transport URL mismatch | 5 |
| `INVALID_HEADER` | Disallowed request header | 5 |
| `INVALID_CONTENT_TYPE` | Response not JSON | 5 |
| `INVALID_UTF8` | Response not valid UTF-8 | 5 |
| `INVALID_JSON` | Response not valid JSON | 5 |
| `INVALID_BODY` | Response body type invalid | 5 |
| `INVALID_HEADERS` | Response headers type invalid | 5 |
| `EXCESSIVE_NESTING` | JSON nesting too deep | 5 |

## Guarantees

### Successful Collection

On successful collection, the connector guarantees:

1. Envelope is emitted to stdout only
2. Output is compact sorted JSON with newline
3. SHA-256 hash is computed on exact raw response bytes
4. All metrics are non-negative integers not exceeding safe integer limit
5. Response version is exactly integer 1
6. Query echo matches request parameters exactly (since and until only)
7. The process-only configured site binding exactly matches canonical `site_url`
8. No credentials or private provider IDs appear in output
9. Output is bounded to 1 MiB
10. Lineage is a nonempty list with correct structure

### Failed Collection

On failed collection, the connector guarantees:

1. No envelope is emitted to stdout (stdout remains empty)
2. Structured error is emitted to stderr as JSON
3. Error contains fixed code and message
4. No credentials appear in error
5. No partial data is fabricated
6. Exit code indicates error category
7. CLI parse errors are non-reflective (no argument echoing)

## Security Boundaries

### Path/Symlink Surface

The CLI has no input or output path options. The path and symlink surface is absent by construction:
- No `--output`, `--file`, or `--path` arguments
- Output goes to stdout only
- No file reading or writing operations
- No path traversal or symlink following possible

### Credential Isolation

Credentials are read from environment variables only at collection time and are never written to:
- Standard output (envelope)
- Standard error (error messages)
- Logs
- Exception messages
- Persisted artifacts

All output is sanitized for credential patterns and sensitive value overlap before emission. If any public field contains an actual credential value, the envelope is rejected and no output is produced.

## Compatibility

This envelope format is compatible with the public evidence-loop contract and can be consumed by any evidence-loop-compatible system.
