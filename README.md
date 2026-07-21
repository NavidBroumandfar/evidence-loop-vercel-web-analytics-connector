# Evidence Loop Vercel Web Analytics Connector

A `0.1.0` release candidate for the Vercel Web Analytics visits/count endpoint
that emits Connector Exchange Envelope v1 JSON compatible with the public
evidence-loop contract. PyPI publication remains separately gated. A bounded
read-only live validation on 2026-07-22 confirmed the current
provider response shape and the sanitized envelope-to-core round trip. No live
response body, metric value, credential, project ID, or team ID is committed.

## Features

- **Stdlib-only runtime**: Zero external dependencies
- **Strict security boundaries**: Credentials never appear in output, logs, or persisted artifacts
- **Fakeable transport**: Inject test transports for comprehensive testing
- **Comprehensive validation**: Strict input/output validation with fixed error codes
- **Deterministic output**: Compact sorted JSON with SHA-256 lineage tracking
- **No path surface**: CLI has no file path options, eliminating traversal attacks

## Local installation

This repository is the source of truth for the `0.1.0` candidate. Run it
from a checkout without contacting a package index:

```bash
PYTHONPATH=src python3 -m evidence_loop_vercel_web_analytics --help
```

If an authorized local wheel already exists, install that artifact offline:

```bash
python3 -m pip install --no-index --no-deps dist/evidence_loop_vercel_web_analytics_connector-0.1.0-py3-none-any.whl
```

## Usage

### Library API

```python
from evidence_loop_vercel_web_analytics import collect

envelope = collect(
    site_url="https://example.com",
    site_id="my-site",
    scope_ref="production",
    since="2025-01-01T00:00:00Z",
    until="2025-01-02T00:00:00Z",
)
```

### CLI

```bash
export VERCEL_TOKEN="your-token"
export VERCEL_PROJECT_ID="prj_..."
export VERCEL_TEAM_ID="team_..."  # optional
export VERCEL_SITE_URL="https://example.com"

PYTHONPATH=src python3 -m evidence_loop_vercel_web_analytics \
  --site-url https://example.com \
  --site-id my-site \
  --scope-ref production \
  --since 2025-01-01T00:00:00Z \
  --until 2025-01-02T00:00:00Z
```

The same source invocation can be written as:

```bash
PYTHONPATH=src python3 -m evidence_loop_vercel_web_analytics \
  --site-url https://example.com \
  --site-id my-site \
  --scope-ref production \
  --since 2025-01-01T00:00:00Z \
  --until 2025-01-02T00:00:00Z
```

Observation windows are UTC ISO-8601 intervals bounded to 31 days inclusive;
longer windows fail with `INVALID_WINDOW`.

## Environment Variables

The connector reads these environment variables at collection time only:

- `VERCEL_TOKEN` (required): Vercel API token
- `VERCEL_PROJECT_ID` (required): Vercel project ID (e.g., `prj_...`)
- `VERCEL_TEAM_ID` (optional): Vercel team ID (e.g., `team_...`)
- `VERCEL_SITE_URL` (required): canonical public origin explicitly bound by
  the operator to that project/team configuration; it must exactly match
  `--site-url` after canonicalization or collection fails before transport

**Security**: Credentials and private provider IDs are never written to output,
logs, or error messages. `VERCEL_SITE_URL` is the public, process-only binding
that prevents one project's evidence from being labeled as another site.

## Envelope Format

The connector emits Connector Exchange Envelope v1 JSON:

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
    "pageviews": {"unit": "count", "value": 1234},
    "visitors": {"unit": "count", "value": 567}
  },
  "provider_response_sha256": "abc123..."
}
```

See `examples/envelope.json` for a complete example.

## Error Handling

The connector uses structured errors with fixed codes:

- **ValidationError** (exit 1): Input validation failed
- **PartialResponseError** (exit 2): Provider response missing required metrics
- **ProviderUnavailableError** (exit 3): Provider service unavailable
- **SecurityError** (exit 4): Security boundary violation
- **TransportError** (exit 5): HTTP transport failure

All errors are emitted as JSON to stderr with no credentials.

## Security

See [SECURITY.md](SECURITY.md) for security policy and [docs/architecture.md](docs/architecture.md) for security architecture.

## Relationship to the public core

Install this package only when collecting Vercel Web Analytics. It emits a
sanitized JSON envelope; the separately installed
`evidence-loop-visibility-engine` validates, normalizes, and processes that
file. The public core's GitHub Action is part of the core repository, not a
third package.

## Testing

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

All tests use fake transports with synthetic data. No real network calls.

## License

MIT License. See [LICENSE](LICENSE).
