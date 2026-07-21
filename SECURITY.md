# Security Policy

## Supported Versions

| Version | Status |
| ------- | ------ |
| 0.1.0   | Supported |

## Security Architecture

This connector implements strict security boundaries:

### Credential Isolation

- Credentials and private provider IDs (`VERCEL_TOKEN`, `VERCEL_PROJECT_ID`,
  `VERCEL_TEAM_ID`) are read from environment variables only at collection time
- The public process-only `VERCEL_SITE_URL` binding must match the requested
  canonical site before transport, preventing cross-site evidence labeling
- Credentials never appear in output, logs, error messages, or persisted artifacts
- All output is sanitized for credential patterns before emission

### Network Constraints

- Runtime uses only Python stdlib (no external dependencies)
- HTTP transport is pinned to exact scheme/host/path: `https://api.vercel.com/v1/query/web-analytics/visits/count`
- Redirects are disabled and all 3xx responses are rejected
- Authorization headers are never forwarded on redirects
- Response body is bounded at 1 MiB before parsing

### Input Validation

- Site URLs must be canonical HTTPS DNS origins (no userinfo, port, path, query, fragment, localhost, or IP)
- Timestamps must be UTC ISO-8601 Z format
- All public aliases are validated for length and character set
- No file path or symlink options exist (eliminating path traversal surfaces)

### Output Validation

- Response must be valid JSON with no duplicate keys
- Excessive nesting is rejected (>10 levels)
- Invalid UTF-8 is rejected
- Non-JSON content types are rejected
- Non-200 status codes are treated as provider unavailable
- Response version must be exactly 1
- Query echo must match request parameters exactly
- Metrics must be non-negative integers (booleans, floats, negatives rejected)
- Missing metrics result in partial-response failure with no envelope

### SHA-256 Lineage

- Raw response bytes are hashed with SHA-256 before any transformation
- Hash is included in envelope as `provider_response_sha256`
- Provides an exact-byte integrity and provenance fingerprint for the
  observed response; it is not proof of provider authenticity

### Fail-Closed Design

- All validation failures produce structured errors with no envelope
- No partial data is ever fabricated
- Security violations halt execution before any output

## Reporting a Vulnerability

Before the repository is public, report privately to the maintainer. After
release, use the repository's private GitHub Security Advisory flow. Never
include credentials, private provider identifiers, or live evidence in a
public issue, artifact, or diagnostic output.
