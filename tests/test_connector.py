"""Tests for connector logic."""

import hashlib
import json
import os
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

from evidence_loop_vercel_web_analytics.connector import collect
from evidence_loop_vercel_web_analytics.errors import (
    PartialResponseError,
    ProviderUnavailableError,
    SecurityError,
    TransportError,
    ValidationError,
)
from evidence_loop_vercel_web_analytics.http import HTTPResponse, Transport, UrllibTransport


def _guard_urllib_get(self, url, headers, params):
    raise AssertionError("UrllibTransport.get called without mock - real network call prevented")


_original_urllib_get = UrllibTransport.get
_urllib_get_patcher = patch.object(UrllibTransport, "get", _guard_urllib_get)


def setUpModule():
    """Guard accidental network calls only while this module runs."""
    _urllib_get_patcher.start()


def tearDownModule():
    """Restore the real transport for subsequent test modules."""
    _urllib_get_patcher.stop()


class FakeTransport(Transport):
    """Fake transport for testing."""

    def __init__(self, response: HTTPResponse):
        self.response = response

    def get(self, url: str, headers: dict[str, str], params: dict[str, str]) -> HTTPResponse:
        return self.response


def make_response(data: dict, status: int = 200) -> HTTPResponse:
    """Create fake response."""
    body = json.dumps(data).encode("utf-8")
    return HTTPResponse(
        status=status,
        headers={"Content-Type": "application/json"},
        body=body,
    )


def make_valid_response(
    since: str = "2025-01-01T00:00:00Z",
    until: str = "2025-01-02T00:00:00Z",
    pageviews: int = 1234,
    visitors: int = 567,
) -> HTTPResponse:
    """Create valid response."""
    query = {
        "since": since,
        "until": until,
    }

    data = {
        "version": 1,
        "query": query,
        "data": {
            "pageviews": pageviews,
            "visitors": visitors,
        },
    }
    return make_response(data)


class TestCollect(unittest.TestCase):
    """Test collection logic."""

    def setUp(self):
        """Set up test environment."""
        self.env_patcher = patch.dict(
            os.environ,
            {
                "VERCEL_TOKEN": "test_token",
                "VERCEL_PROJECT_ID": "prj_abc123",
                "VERCEL_SITE_URL": "https://example.com",
            },
            clear=False,
        )
        self.env_patcher.start()

    def tearDown(self):
        """Clean up test environment."""
        self.env_patcher.stop()

    def test_collect_valid_fresh(self):
        """Collect valid fresh data."""
        until = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        since = (datetime.now(timezone.utc) - timedelta(hours=25)).strftime("%Y-%m-%dT%H:%M:%SZ")

        transport = FakeTransport(
            make_valid_response(
                since=since,
                until=until,
            )
        )

        envelope = collect(
            site_url="https://example.com",
            site_id="site-123",
            scope_ref="scope-456",
            since=since,
            until=until,
            transport=transport,
        )

        self.assertEqual(envelope["schema_version"], "1")
        self.assertEqual(envelope["source"], "evidence-loop-vercel-web-analytics")
        self.assertEqual(envelope["provider"], "vercel-web-analytics")
        self.assertEqual(envelope["site_url"], "https://example.com")
        self.assertEqual(envelope["site_id"], "site-123")
        self.assertEqual(envelope["scope_ref"], "scope-456")
        self.assertEqual(envelope["grain"], "site-level")
        self.assertEqual(envelope["completeness"], "complete")
        self.assertEqual(envelope["freshness"], "fresh")
        self.assertEqual(envelope["uncertainty"], "low")
        self.assertEqual(envelope["measures"]["pageviews"]["value"], 1234)
        self.assertEqual(envelope["measures"]["pageviews"]["unit"], "count")
        self.assertEqual(envelope["measures"]["visitors"]["value"], 567)
        self.assertEqual(envelope["measures"]["visitors"]["unit"], "count")
        self.assertIn("provider_response_sha256", envelope)
        self.assertIn("collected_at", envelope)
        self.assertIn("limitations", envelope)
        self.assertIn("lineage", envelope)

    def test_collect_valid_stale(self):
        """Collect valid stale data."""
        until = (datetime.now(timezone.utc) - timedelta(hours=48)).strftime("%Y-%m-%dT%H:%M:%SZ")
        since = (datetime.now(timezone.utc) - timedelta(hours=72)).strftime("%Y-%m-%dT%H:%M:%SZ")

        transport = FakeTransport(
            make_valid_response(
                since=since,
                until=until,
            )
        )

        envelope = collect(
            site_url="https://example.com",
            site_id="site-123",
            scope_ref="scope-456",
            since=since,
            until=until,
            stale_threshold_hours=24,
            transport=transport,
        )

        self.assertEqual(envelope["freshness"], "stale")

    def test_collect_with_team_id(self):
        """Collect with team ID."""
        with patch.dict(os.environ, {"VERCEL_TEAM_ID": "team_abc456"}):
            until = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
            since = (datetime.now(timezone.utc) - timedelta(hours=25)).strftime("%Y-%m-%dT%H:%M:%SZ")

            transport = FakeTransport(
                make_valid_response(
                    since=since,
                    until=until,
                )
            )

            envelope = collect(
                site_url="https://example.com",
                site_id="site-123",
                scope_ref="scope-456",
                since=since,
                until=until,
                transport=transport,
            )

            self.assertEqual(envelope["schema_version"], "1")

    def test_missing_project_id(self):
        """Fail when project ID missing."""
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ValidationError) as ctx:
                collect(
                    site_url="https://example.com",
                    site_id="site-123",
                    scope_ref="scope-456",
                    since="2025-01-01T00:00:00Z",
                    until="2025-01-02T00:00:00Z",
                    transport=FakeTransport(make_valid_response()),
                )
            self.assertEqual(ctx.exception.code, "MISSING_PROJECT_ID")

    def test_missing_token(self):
        """Fail when token missing."""
        with patch.dict(os.environ, {"VERCEL_PROJECT_ID": "prj_abc123"}, clear=True):
            with self.assertRaises(ValidationError) as ctx:
                collect(
                    site_url="https://example.com",
                    site_id="site-123",
                    scope_ref="scope-456",
                    since="2025-01-01T00:00:00Z",
                    until="2025-01-02T00:00:00Z",
                    transport=FakeTransport(make_valid_response()),
                )
            self.assertEqual(ctx.exception.code, "MISSING_TOKEN")

    def test_missing_site_binding(self):
        """Fail before transport when the process site binding is absent."""
        with patch.dict(
            os.environ,
            {"VERCEL_PROJECT_ID": "prj_abc123", "VERCEL_TOKEN": "test_token"},
            clear=True,
        ):
            with self.assertRaises(ValidationError) as ctx:
                collect(
                    site_url="https://example.com",
                    site_id="site-123",
                    scope_ref="scope-456",
                    since="2025-01-01T00:00:00Z",
                    until="2025-01-02T00:00:00Z",
                    transport=FakeTransport(make_valid_response()),
                )
            self.assertEqual(ctx.exception.code, "MISSING_SITE_BINDING")

    def test_site_binding_mismatch_fails_before_transport(self):
        """Never label one configured project's evidence as another site."""

        class ForbiddenTransport(Transport):
            def get(self, url, headers, params):
                raise AssertionError("transport must not run for a binding mismatch")

        with patch.dict(os.environ, {"VERCEL_SITE_URL": "https://other.example"}):
            with self.assertRaises(ValidationError) as ctx:
                collect(
                    site_url="https://example.com",
                    site_id="site-123",
                    scope_ref="scope-456",
                    since="2025-01-01T00:00:00Z",
                    until="2025-01-02T00:00:00Z",
                    transport=ForbiddenTransport(),
                )
            self.assertEqual(ctx.exception.code, "SITE_BINDING_MISMATCH")

    def test_invalid_site_url(self):
        """Fail on invalid site URL."""
        with self.assertRaises(ValidationError) as ctx:
            collect(
                site_url="http://example.com",
                site_id="site-123",
                scope_ref="scope-456",
                since="2025-01-01T00:00:00Z",
                until="2025-01-02T00:00:00Z",
                transport=FakeTransport(make_valid_response()),
            )
        self.assertEqual(ctx.exception.code, "INVALID_SITE_URL")

    def test_invalid_window(self):
        """Fail on invalid window."""
        with self.assertRaises(ValidationError) as ctx:
            collect(
                site_url="https://example.com",
                site_id="site-123",
                scope_ref="scope-456",
                since="2025-01-02T00:00:00Z",
                until="2025-01-01T00:00:00Z",
                transport=FakeTransport(make_valid_response()),
            )
        self.assertEqual(ctx.exception.code, "INVALID_WINDOW")

    def test_non_bytes_response_body_fails_structured(self):
        """Collect delegates body type validation before any size check."""
        response = HTTPResponse(
            status=200,
            headers={"Content-Type": "application/json"},
            body="not-bytes",
        )
        with self.assertRaises(TransportError) as ctx:
            collect(
                site_url="https://example.com",
                site_id="site-123",
                scope_ref="scope-456",
                since="2025-01-01T00:00:00Z",
                until="2025-01-02T00:00:00Z",
                transport=FakeTransport(response),
            )
        self.assertEqual(ctx.exception.code, "INVALID_BODY")

    def test_oversize_response_body_fails_structured(self):
        """Collect rejects an oversized fake body without an envelope."""
        response = HTTPResponse(
            status=200,
            headers={"Content-Type": "application/json"},
            body=b"x" * (1024 * 1024 + 1),
        )
        with self.assertRaises(ProviderUnavailableError) as ctx:
            collect(
                site_url="https://example.com",
                site_id="site-123",
                scope_ref="scope-456",
                since="2025-01-01T00:00:00Z",
                until="2025-01-02T00:00:00Z",
                transport=FakeTransport(response),
            )
        self.assertEqual(ctx.exception.code, "RESPONSE_TOO_LARGE")


class TestResponseValidation(unittest.TestCase):
    """Test response structure validation."""

    def setUp(self):
        """Set up test environment."""
        self.env_patcher = patch.dict(
            os.environ,
            {
                "VERCEL_TOKEN": "test_token",
                "VERCEL_PROJECT_ID": "prj_abc123",
                "VERCEL_SITE_URL": "https://example.com",
            },
            clear=False,
        )
        self.env_patcher.start()

    def tearDown(self):
        """Clean up test environment."""
        self.env_patcher.stop()

    def test_reject_wrong_version(self):
        """Reject response version != 1."""
        data = {
            "version": 2,
            "query": {"since": "2025-01-01T00:00:00Z", "until": "2025-01-02T00:00:00Z"},
            "data": {"pageviews": 100, "visitors": 50},
        }
        transport = FakeTransport(make_response(data))

        with self.assertRaises(ProviderUnavailableError) as ctx:
            collect(
                site_url="https://example.com",
                site_id="site-123",
                scope_ref="scope-456",
                since="2025-01-01T00:00:00Z",
                until="2025-01-02T00:00:00Z",
                transport=transport,
            )
        self.assertEqual(ctx.exception.code, "INVALID_VERSION")

    def test_reject_bool_version(self):
        """Reject boolean version."""
        data = {
            "version": True,
            "query": {"since": "2025-01-01T00:00:00Z", "until": "2025-01-02T00:00:00Z"},
            "data": {"pageviews": 100, "visitors": 50},
        }
        transport = FakeTransport(make_response(data))

        with self.assertRaises(ProviderUnavailableError) as ctx:
            collect(
                site_url="https://example.com",
                site_id="site-123",
                scope_ref="scope-456",
                since="2025-01-01T00:00:00Z",
                until="2025-01-02T00:00:00Z",
                transport=transport,
            )
        self.assertEqual(ctx.exception.code, "INVALID_VERSION")

    def test_reject_missing_metric(self):
        """Reject response missing metric."""
        data = {
            "version": 1,
            "query": {"since": "2025-01-01T00:00:00Z", "until": "2025-01-02T00:00:00Z"},
            "data": {"pageviews": 100},
        }
        transport = FakeTransport(make_response(data))

        with self.assertRaises(PartialResponseError) as ctx:
            collect(
                site_url="https://example.com",
                site_id="site-123",
                scope_ref="scope-456",
                since="2025-01-01T00:00:00Z",
                until="2025-01-02T00:00:00Z",
                transport=transport,
            )
        self.assertEqual(ctx.exception.code, "MISSING_METRICS")

    def test_reject_extra_data_keys(self):
        """Reject extra keys in data."""
        data = {
            "version": 1,
            "query": {"since": "2025-01-01T00:00:00Z", "until": "2025-01-02T00:00:00Z"},
            "data": {"pageviews": 100, "visitors": 50, "extra": "metric"},
        }
        transport = FakeTransport(make_response(data))

        with self.assertRaises(ProviderUnavailableError) as ctx:
            collect(
                site_url="https://example.com",
                site_id="site-123",
                scope_ref="scope-456",
                since="2025-01-01T00:00:00Z",
                until="2025-01-02T00:00:00Z",
                transport=transport,
            )
        self.assertEqual(ctx.exception.code, "INVALID_DATA")

    def test_reject_extra_query_keys(self):
        """Reject extra keys in query."""
        data = {
            "version": 1,
            "query": {"since": "2025-01-01T00:00:00Z", "until": "2025-01-02T00:00:00Z", "extra": "key"},
            "data": {"pageviews": 100, "visitors": 50},
        }
        transport = FakeTransport(make_response(data))

        with self.assertRaises(ProviderUnavailableError) as ctx:
            collect(
                site_url="https://example.com",
                site_id="site-123",
                scope_ref="scope-456",
                since="2025-01-01T00:00:00Z",
                until="2025-01-02T00:00:00Z",
                transport=transport,
            )
        self.assertEqual(ctx.exception.code, "INVALID_QUERY")

    def test_reject_project_id_in_query(self):
        """Reject projectId in query (request-only)."""
        data = {
            "version": 1,
            "query": {"since": "2025-01-01T00:00:00Z", "until": "2025-01-02T00:00:00Z", "projectId": "prj_abc123"},
            "data": {"pageviews": 100, "visitors": 50},
        }
        transport = FakeTransport(make_response(data))

        with self.assertRaises(ProviderUnavailableError) as ctx:
            collect(
                site_url="https://example.com",
                site_id="site-123",
                scope_ref="scope-456",
                since="2025-01-01T00:00:00Z",
                until="2025-01-02T00:00:00Z",
                transport=transport,
            )
        self.assertEqual(ctx.exception.code, "INVALID_QUERY")

    def test_reject_negative_pageviews(self):
        """Reject negative pageviews."""
        data = {
            "version": 1,
            "query": {"since": "2025-01-01T00:00:00Z", "until": "2025-01-02T00:00:00Z"},
            "data": {"pageviews": -1, "visitors": 50},
        }
        transport = FakeTransport(make_response(data))

        with self.assertRaises(ProviderUnavailableError) as ctx:
            collect(
                site_url="https://example.com",
                site_id="site-123",
                scope_ref="scope-456",
                since="2025-01-01T00:00:00Z",
                until="2025-01-02T00:00:00Z",
                transport=transport,
            )
        self.assertEqual(ctx.exception.code, "INVALID_METRIC_VALUE")

    def test_reject_boolean_metric(self):
        """Reject boolean metric."""
        data = {
            "version": 1,
            "query": {"since": "2025-01-01T00:00:00Z", "until": "2025-01-02T00:00:00Z"},
            "data": {"pageviews": True, "visitors": 50},
        }
        transport = FakeTransport(make_response(data))

        with self.assertRaises(ProviderUnavailableError) as ctx:
            collect(
                site_url="https://example.com",
                site_id="site-123",
                scope_ref="scope-456",
                since="2025-01-01T00:00:00Z",
                until="2025-01-02T00:00:00Z",
                transport=transport,
            )
        self.assertEqual(ctx.exception.code, "INVALID_METRIC_TYPE")

    def test_reject_float_metric(self):
        """Reject float metric."""
        data = {
            "version": 1,
            "query": {"since": "2025-01-01T00:00:00Z", "until": "2025-01-02T00:00:00Z"},
            "data": {"pageviews": 100.5, "visitors": 50},
        }
        transport = FakeTransport(make_response(data))

        with self.assertRaises(ProviderUnavailableError) as ctx:
            collect(
                site_url="https://example.com",
                site_id="site-123",
                scope_ref="scope-456",
                since="2025-01-01T00:00:00Z",
                until="2025-01-02T00:00:00Z",
                transport=transport,
            )
        self.assertEqual(ctx.exception.code, "INVALID_METRIC_TYPE")

    def test_reject_overlarge_metric(self):
        """Reject metric exceeding safe integer."""
        data = {
            "version": 1,
            "query": {"since": "2025-01-01T00:00:00Z", "until": "2025-01-02T00:00:00Z"},
            "data": {"pageviews": 9007199254740992, "visitors": 50},
        }
        transport = FakeTransport(make_response(data))

        with self.assertRaises(ProviderUnavailableError) as ctx:
            collect(
                site_url="https://example.com",
                site_id="site-123",
                scope_ref="scope-456",
                since="2025-01-01T00:00:00Z",
                until="2025-01-02T00:00:00Z",
                transport=transport,
            )
        self.assertEqual(ctx.exception.code, "INVALID_METRIC_VALUE")

    def test_reject_query_mismatch(self):
        """Reject query echo mismatch."""
        data = {
            "version": 1,
            "query": {"since": "2025-01-01T00:00:00Z", "until": "2025-01-03T00:00:00Z"},
            "data": {"pageviews": 100, "visitors": 50},
        }
        transport = FakeTransport(make_response(data))

        with self.assertRaises(ProviderUnavailableError) as ctx:
            collect(
                site_url="https://example.com",
                site_id="site-123",
                scope_ref="scope-456",
                since="2025-01-01T00:00:00Z",
                until="2025-01-02T00:00:00Z",
                transport=transport,
            )
        self.assertEqual(ctx.exception.code, "QUERY_MISMATCH")

    def test_accept_provider_millisecond_timestamp_echoes(self):
        """Accept Vercel's canonical .000Z echo for whole-second UTC input."""
        since = "2025-01-01T00:00:00Z"
        until = "2025-01-02T00:00:00Z"
        response = make_valid_response(
            since="2025-01-01T00:00:00.000Z",
            until="2025-01-02T00:00:00.000Z",
        )

        envelope = collect(
            site_url="https://example.com",
            site_id="site-123",
            scope_ref="scope-456",
            since=since,
            until=until,
            transport=FakeTransport(response),
            now=datetime(2025, 1, 3, tzinfo=timezone.utc),
        )

        self.assertEqual(envelope["observation_window"], {"start": since, "end": until})

    def test_reject_noncanonical_or_drifted_provider_timestamp_echoes(self):
        """Do not weaken exact echo binding beyond Vercel's zero-millisecond form."""
        cases = (
            ("2025-01-01T00:00:00.001Z", "2025-01-02T00:00:00.000Z"),
            ("2025-01-01T00:00:00+00:00", "2025-01-02T00:00:00.000Z"),
            (1735689600000, "2025-01-02T00:00:00.000Z"),
            ("2025-01-01T00:00:01.000Z", "2025-01-02T00:00:00.000Z"),
        )
        for echoed_since, echoed_until in cases:
            with self.subTest(echoed_since=echoed_since):
                response = make_valid_response(since=echoed_since, until=echoed_until)
                with self.assertRaises(ProviderUnavailableError) as ctx:
                    collect(
                        site_url="https://example.com",
                        site_id="site-123",
                        scope_ref="scope-456",
                        since="2025-01-01T00:00:00Z",
                        until="2025-01-02T00:00:00Z",
                        transport=FakeTransport(response),
                        now=datetime(2025, 1, 3, tzinfo=timezone.utc),
                    )
                self.assertEqual(ctx.exception.code, "QUERY_MISMATCH")


class TestEnvelopeShape(unittest.TestCase):
    """Test envelope structure."""

    def setUp(self):
        """Set up test environment."""
        self.env_patcher = patch.dict(
            os.environ,
            {
                "VERCEL_TOKEN": "test_token",
                "VERCEL_PROJECT_ID": "prj_abc123",
                "VERCEL_SITE_URL": "https://example.com",
            },
            clear=False,
        )
        self.env_patcher.start()

    def tearDown(self):
        """Clean up test environment."""
        self.env_patcher.stop()

    def test_envelope_has_all_fields(self):
        """Envelope has all required fields."""
        until = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        since = (datetime.now(timezone.utc) - timedelta(hours=25)).strftime("%Y-%m-%dT%H:%M:%SZ")

        transport = FakeTransport(
            make_valid_response(
                since=since,
                until=until,
            )
        )

        envelope = collect(
            site_url="https://example.com",
            site_id="site-123",
            scope_ref="scope-456",
            since=since,
            until=until,
            transport=transport,
        )

        required_fields = {
            "schema_version",
            "source",
            "provider",
            "site_url",
            "site_id",
            "scope_ref",
            "observation_window",
            "collected_at",
            "grain",
            "completeness",
            "freshness",
            "uncertainty",
            "limitations",
            "lineage",
            "measures",
            "provider_response_sha256",
        }

        for field in required_fields:
            self.assertIn(field, envelope)

    def test_schema_version_is_string(self):
        """schema_version must be string '1'."""
        until = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        since = (datetime.now(timezone.utc) - timedelta(hours=25)).strftime("%Y-%m-%dT%H:%M:%SZ")

        transport = FakeTransport(
            make_valid_response(
                since=since,
                until=until,
            )
        )

        envelope = collect(
            site_url="https://example.com",
            site_id="site-123",
            scope_ref="scope-456",
            since=since,
            until=until,
            transport=transport,
        )

        self.assertEqual(envelope["schema_version"], "1")
        self.assertIsInstance(envelope["schema_version"], str)

    def test_observation_window_has_start_end(self):
        """observation_window must have start and end keys."""
        until = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        since = (datetime.now(timezone.utc) - timedelta(hours=25)).strftime("%Y-%m-%dT%H:%M:%SZ")

        transport = FakeTransport(
            make_valid_response(
                since=since,
                until=until,
            )
        )

        envelope = collect(
            site_url="https://example.com",
            site_id="site-123",
            scope_ref="scope-456",
            since=since,
            until=until,
            transport=transport,
        )

        self.assertIn("start", envelope["observation_window"])
        self.assertIn("end", envelope["observation_window"])
        self.assertNotIn("since", envelope["observation_window"])
        self.assertNotIn("until", envelope["observation_window"])

    def test_lineage_is_list(self):
        """lineage must be a nonempty list."""
        until = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        since = (datetime.now(timezone.utc) - timedelta(hours=25)).strftime("%Y-%m-%dT%H:%M:%SZ")

        transport = FakeTransport(
            make_valid_response(
                since=since,
                until=until,
            )
        )

        envelope = collect(
            site_url="https://example.com",
            site_id="site-123",
            scope_ref="scope-456",
            since=since,
            until=until,
            transport=transport,
        )

        self.assertIsInstance(envelope["lineage"], list)
        self.assertGreater(len(envelope["lineage"]), 0)

    def test_lineage_has_correct_structure(self):
        """lineage entry has stage, reference, method."""
        until = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        since = (datetime.now(timezone.utc) - timedelta(hours=25)).strftime("%Y-%m-%dT%H:%M:%SZ")

        transport = FakeTransport(
            make_valid_response(
                since=since,
                until=until,
            )
        )

        envelope = collect(
            site_url="https://example.com",
            site_id="site-123",
            scope_ref="scope-456",
            since=since,
            until=until,
            transport=transport,
        )

        lineage_entry = envelope["lineage"][0]
        self.assertEqual(lineage_entry["stage"], "provider-response")
        self.assertEqual(lineage_entry["reference"], "provider_response_sha256")
        self.assertEqual(lineage_entry["method"], "sha256")


class TestSHA256Computation(unittest.TestCase):
    """Test SHA-256 computation."""

    def setUp(self):
        self.env_patcher = patch.dict(
            os.environ,
            {
                "VERCEL_TOKEN": "test_token",
                "VERCEL_PROJECT_ID": "prj_abc123",
                "VERCEL_SITE_URL": "https://example.com",
            },
            clear=False,
        )
        self.env_patcher.start()

    def tearDown(self):
        self.env_patcher.stop()

    def test_sha256_computed_from_body(self):
        """SHA-256 must be computed from response.body."""
        until = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        since = (datetime.now(timezone.utc) - timedelta(hours=25)).strftime("%Y-%m-%dT%H:%M:%SZ")

        data = {
            "version": 1,
            "query": {"since": since, "until": until},
            "data": {"pageviews": 100, "visitors": 50},
        }
        body = json.dumps(data).encode("utf-8")
        expected_sha256 = hashlib.sha256(body).hexdigest()

        transport = FakeTransport(HTTPResponse(
            status=200,
            headers={"Content-Type": "application/json"},
            body=body,
        ))

        envelope = collect(
            site_url="https://example.com",
            site_id="site-123",
            scope_ref="scope-456",
            since=since,
            until=until,
            transport=transport,
        )

        self.assertEqual(envelope["provider_response_sha256"], expected_sha256)


class TestDeterministicOutput(unittest.TestCase):
    """Test deterministic output with fixed clock."""

    def setUp(self):
        self.env_patcher = patch.dict(
            os.environ,
            {
                "VERCEL_TOKEN": "test_token",
                "VERCEL_PROJECT_ID": "prj_abc123",
                "VERCEL_SITE_URL": "https://example.com",
            },
            clear=False,
        )
        self.env_patcher.start()

    def tearDown(self):
        self.env_patcher.stop()

    def test_deterministic_with_fixed_now(self):
        """Envelope must be deterministic with fixed now parameter."""
        fixed_time = datetime(2025, 1, 2, 12, 0, 0, tzinfo=timezone.utc)
        since = "2025-01-01T00:00:00Z"
        until = "2025-01-02T00:00:00Z"

        data = {
            "version": 1,
            "query": {"since": since, "until": until},
            "data": {"pageviews": 100, "visitors": 50},
        }
        transport = FakeTransport(make_response(data))

        envelope1 = collect(
            site_url="https://example.com",
            site_id="site-123",
            scope_ref="scope-456",
            since=since,
            until=until,
            transport=transport,
            now=fixed_time,
        )

        envelope2 = collect(
            site_url="https://example.com",
            site_id="site-123",
            scope_ref="scope-456",
            since=since,
            until=until,
            transport=transport,
            now=fixed_time,
        )

        json1 = json.dumps(envelope1, sort_keys=True, separators=(",", ":"))
        json2 = json.dumps(envelope2, sort_keys=True, separators=(",", ":"))

        self.assertEqual(json1, json2)

    def test_now_keyword_only(self):
        """now must be keyword-only."""
        fixed_time = datetime(2025, 1, 2, 12, 0, 0, tzinfo=timezone.utc)
        since = "2025-01-01T00:00:00Z"
        until = "2025-01-02T00:00:00Z"

        data = {
            "version": 1,
            "query": {"since": since, "until": until},
            "data": {"pageviews": 100, "visitors": 50},
        }
        transport = FakeTransport(make_response(data))

        with self.assertRaises(TypeError):
            collect(
                "https://example.com",
                "site-123",
                "scope-456",
                since,
                until,
                24,
                transport,
                fixed_time,
            )

    def test_collection_time_is_utc_whole_second(self):
        """The one collection clock is truncated and rendered as UTC Z."""
        fixed_time = datetime(2025, 1, 2, 12, 0, 0, 987654, tzinfo=timezone.utc)
        since = "2025-01-01T00:00:00Z"
        until = "2025-01-02T00:00:00Z"
        envelope = collect(
            site_url="https://example.com",
            site_id="site-123",
            scope_ref="scope-456",
            since=since,
            until=until,
            transport=FakeTransport(make_valid_response(since=since, until=until)),
            now=fixed_time,
        )
        self.assertEqual(envelope["collected_at"], "2025-01-02T12:00:00Z")
        self.assertEqual(envelope["freshness"], "fresh")


class TestSensitiveValueEnforcement(unittest.TestCase):
    """Test that sensitive values are enforced in output."""

    def test_reject_site_id_equals_token(self):
        """Reject when site_id equals actual token value."""
        with patch.dict(
            os.environ,
            {
                "VERCEL_TOKEN": "mysecrettoken123",
                "VERCEL_PROJECT_ID": "prj_abc123",
                "VERCEL_SITE_URL": "https://example.com",
            },
        ):
            until = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
            since = (datetime.now(timezone.utc) - timedelta(hours=25)).strftime("%Y-%m-%dT%H:%M:%SZ")

            transport = FakeTransport(
                make_valid_response(
                    since=since,
                    until=until,
                )
            )

            with self.assertRaises(SecurityError):
                collect(
                    site_url="https://example.com",
                    site_id="mysecrettoken123",
                    scope_ref="scope-456",
                    since=since,
                    until=until,
                    transport=transport,
                )

    def test_reject_scope_ref_equals_project_id(self):
        """Reject when scope_ref equals actual project ID value."""
        with patch.dict(
            os.environ,
            {
                "VERCEL_TOKEN": "test_token",
                "VERCEL_PROJECT_ID": "prj_abc123def456",
                "VERCEL_SITE_URL": "https://example.com",
            },
        ):
            until = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
            since = (datetime.now(timezone.utc) - timedelta(hours=25)).strftime("%Y-%m-%dT%H:%M:%SZ")

            transport = FakeTransport(
                make_valid_response(
                    since=since,
                    until=until,
                )
            )

            with self.assertRaises(SecurityError):
                collect(
                    site_url="https://example.com",
                    site_id="site-123",
                    scope_ref="prj_abc123def456",
                    since=since,
                    until=until,
                    transport=transport,
                )

    def test_reject_each_credential_overlap(self):
        """Reject overlap for token, project, and optional team values."""
        since = "2025-01-01T00:00:00Z"
        until = "2025-01-02T00:00:00Z"
        response = FakeTransport(make_valid_response(since=since, until=until))

        with patch.dict(
            os.environ,
            {
                "VERCEL_TOKEN": "secret-token",
                "VERCEL_PROJECT_ID": "prj_abc123",
                "VERCEL_SITE_URL": "https://example.com",
            },
            clear=True,
        ):
            with self.assertRaises(SecurityError):
                collect(
                    site_url="https://example.com",
                    site_id="secret-token",
                    scope_ref="scope-456",
                    since=since,
                    until=until,
                    transport=response,
                )

        with patch.dict(
            os.environ,
            {
                "VERCEL_TOKEN": "safe-token",
                "VERCEL_PROJECT_ID": "prj_abc123",
                "VERCEL_SITE_URL": "https://example.com",
            },
            clear=True,
        ):
            with self.assertRaises(SecurityError):
                collect(
                    site_url="https://example.com",
                    site_id="site-123",
                    scope_ref="prj_abc123",
                    since=since,
                    until=until,
                    transport=response,
                )

        with patch.dict(
            os.environ,
            {
                "VERCEL_TOKEN": "safe-token",
                "VERCEL_PROJECT_ID": "prj_abc123",
                "VERCEL_TEAM_ID": "team_abc123",
                "VERCEL_SITE_URL": "https://example.com",
            },
            clear=True,
        ):
            with self.assertRaises(SecurityError):
                collect(
                    site_url="https://example.com",
                    site_id="site-123",
                    scope_ref="team_abc123",
                    since=since,
                    until=until,
                    transport=response,
                )


if __name__ == "__main__":
    unittest.main()
