"""Tests for safety validation."""

import importlib.util
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from evidence_loop_vercel_web_analytics.errors import SecurityError, ValidationError
from evidence_loop_vercel_web_analytics.safety import (
    MAX_WINDOW_DAYS,
    check_credential_leakage,
    serialize_envelope,
    validate_now,
    validate_project_id,
    validate_scope_ref,
    validate_site_id,
    validate_site_url,
    validate_stale_threshold,
    validate_team_id,
    validate_timestamp,
    validate_token,
    validate_window,
)


def _load_script(name: str):
    """Load a script module from scripts/ directory."""
    script_path = Path(__file__).parent.parent / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, str(script_path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestSiteURLValidation(unittest.TestCase):
    """Test site_url validation."""

    def test_valid_https_origin(self):
        """Accept valid HTTPS origin."""
        result = validate_site_url("https://example.com")
        self.assertEqual(result, "https://example.com")

    def test_valid_https_with_subdomain(self):
        """Accept valid HTTPS with subdomain."""
        result = validate_site_url("https://sub.example.com")
        self.assertEqual(result, "https://sub.example.com")

    def test_canonical_lowercase(self):
        """Canonicalize to lowercase."""
        result = validate_site_url("https://EXAMPLE.COM")
        self.assertEqual(result, "https://example.com")

    def test_canonical_no_trailing_slash(self):
        """Remove trailing slash."""
        result = validate_site_url("https://example.com/")
        self.assertEqual(result, "https://example.com")

    def test_reject_http(self):
        """Reject non-HTTPS."""
        with self.assertRaises(ValidationError) as ctx:
            validate_site_url("http://example.com")
        self.assertEqual(ctx.exception.code, "INVALID_SITE_URL")

    def test_reject_userinfo(self):
        """Reject userinfo in URL."""
        with self.assertRaises(ValidationError) as ctx:
            validate_site_url("https://user:pass@example.com")
        self.assertEqual(ctx.exception.code, "INVALID_SITE_URL")

    def test_reject_explicit_port(self):
        """Reject explicit port."""
        with self.assertRaises(ValidationError) as ctx:
            validate_site_url("https://example.com:443")
        self.assertEqual(ctx.exception.code, "INVALID_SITE_URL")

    def test_reject_invalid_port(self):
        """Reject invalid port."""
        with self.assertRaises(ValidationError) as ctx:
            validate_site_url("https://example.com:abc")
        self.assertEqual(ctx.exception.code, "INVALID_SITE_URL")

    def test_reject_path(self):
        """Reject non-root path."""
        with self.assertRaises(ValidationError) as ctx:
            validate_site_url("https://example.com/path")
        self.assertEqual(ctx.exception.code, "INVALID_SITE_URL")

    def test_reject_double_slash(self):
        """Reject double slash in path."""
        with self.assertRaises(ValidationError) as ctx:
            validate_site_url("https://example.com//")
        self.assertEqual(ctx.exception.code, "INVALID_SITE_URL")

    def test_reject_any_whitespace_or_control(self):
        """Whitespace and Unicode controls cannot reach URL parsing."""
        for value in (
            " https://example.com",
            "https://example.com ",
            "https://example.com/\t",
            "https://example.com/\u0085",
            "https://example.com/\u200b",
        ):
            with self.subTest(value=repr(value)):
                with self.assertRaises(ValidationError) as ctx:
                    validate_site_url(value)
                self.assertEqual(ctx.exception.code, "INVALID_SITE_URL")

    def test_reject_backslash(self):
        """Backslashes cannot be normalized into a different URL."""
        with self.assertRaises(ValidationError) as ctx:
            validate_site_url("https://example.com\\path")
        self.assertEqual(ctx.exception.code, "INVALID_SITE_URL")

    def test_reject_query(self):
        """Reject query string."""
        with self.assertRaises(ValidationError) as ctx:
            validate_site_url("https://example.com?foo=bar")
        self.assertEqual(ctx.exception.code, "INVALID_SITE_URL")

    def test_reject_fragment(self):
        """Reject fragment."""
        with self.assertRaises(ValidationError) as ctx:
            validate_site_url("https://example.com#section")
        self.assertEqual(ctx.exception.code, "INVALID_SITE_URL")

    def test_reject_localhost(self):
        """Reject localhost."""
        with self.assertRaises(ValidationError) as ctx:
            validate_site_url("https://localhost")
        self.assertEqual(ctx.exception.code, "INVALID_SITE_URL")

    def test_reject_localhost_suffix(self):
        """Reject localhost suffix."""
        with self.assertRaises(ValidationError) as ctx:
            validate_site_url("https://app.localhost")
        self.assertEqual(ctx.exception.code, "INVALID_SITE_URL")

    def test_reject_127_0_0_1(self):
        """Reject 127.0.0.1."""
        with self.assertRaises(ValidationError) as ctx:
            validate_site_url("https://127.0.0.1")
        self.assertEqual(ctx.exception.code, "INVALID_SITE_URL")

    def test_reject_ipv4(self):
        """Reject IPv4 address."""
        with self.assertRaises(ValidationError) as ctx:
            validate_site_url("https://192.168.1.1")
        self.assertEqual(ctx.exception.code, "INVALID_SITE_URL")

    def test_reject_ipv6(self):
        """Reject IPv6 address."""
        with self.assertRaises(ValidationError) as ctx:
            validate_site_url("https://[::1]")
        self.assertEqual(ctx.exception.code, "INVALID_SITE_URL")

    def test_reject_long_hostname(self):
        """Reject hostname exceeding 253 characters."""
        long_host = "a" * 63 + "." + "b" * 63 + "." + "c" * 63 + "." + "d" * 63 + ".com"
        with self.assertRaises(ValidationError) as ctx:
            validate_site_url(f"https://{long_host}")
        self.assertEqual(ctx.exception.code, "INVALID_SITE_URL")

    def test_reject_long_label(self):
        """Reject label exceeding 63 characters."""
        long_label = "a" * 64 + ".com"
        with self.assertRaises(ValidationError) as ctx:
            validate_site_url(f"https://{long_label}")
        self.assertEqual(ctx.exception.code, "INVALID_SITE_URL")

    def test_reject_single_label(self):
        """Reject single-label hostname."""
        with self.assertRaises(ValidationError) as ctx:
            validate_site_url("https://localhost")
        self.assertEqual(ctx.exception.code, "INVALID_SITE_URL")


class TestSiteIDValidation(unittest.TestCase):
    """Test site_id validation."""

    def test_valid_site_id(self):
        """Accept valid site_id."""
        result = validate_site_id("site-123")
        self.assertEqual(result, "site-123")

    def test_reject_empty(self):
        """Reject empty site_id."""
        with self.assertRaises(ValidationError) as ctx:
            validate_site_id("")
        self.assertEqual(ctx.exception.code, "INVALID_SITE_ID")

    def test_reject_non_string(self):
        """Non-string site IDs fail with a structured validation error."""
        with self.assertRaises(ValidationError) as ctx:
            validate_site_id(123)
        self.assertEqual(ctx.exception.code, "INVALID_SITE_ID")

    def test_reject_too_long(self):
        """Reject overly long site_id."""
        with self.assertRaises(ValidationError) as ctx:
            validate_site_id("x" * 64)
        self.assertEqual(ctx.exception.code, "INVALID_SITE_ID")

    def test_reject_uppercase(self):
        """Reject uppercase."""
        with self.assertRaises(ValidationError) as ctx:
            validate_site_id("Site-123")
        self.assertEqual(ctx.exception.code, "INVALID_SITE_ID")

    def test_reject_ending_hyphen(self):
        """Reject ending with hyphen."""
        with self.assertRaises(ValidationError) as ctx:
            validate_site_id("site-123-")
        self.assertEqual(ctx.exception.code, "INVALID_SITE_ID")


class TestScopeRefValidation(unittest.TestCase):
    """Test scope_ref validation."""

    def test_valid_scope_ref(self):
        """Accept valid scope_ref."""
        result = validate_scope_ref("production")
        self.assertEqual(result, "production")

    def test_reject_empty(self):
        """Reject empty scope_ref."""
        with self.assertRaises(ValidationError) as ctx:
            validate_scope_ref("")
        self.assertEqual(ctx.exception.code, "INVALID_SCOPE_REF")

    def test_accept_public_aliases(self):
        """Normal public aliases remain valid."""
        self.assertEqual(validate_scope_ref("scope-456"), "scope-456")
        self.assertEqual(validate_scope_ref("public_site"), "public_site")
        self.assertEqual(validate_scope_ref("scope.v1"), "scope.v1")

    def test_reject_non_string_and_path_shapes(self):
        """Scope references cannot become paths or traversal inputs."""
        invalid = (123, "/absolute", "../parent", "..", ".hidden", "foo/bar", "foo\\bar", "foo..bar")
        for value in invalid:
            with self.subTest(value=repr(value)):
                with self.assertRaises(ValidationError) as ctx:
                    validate_scope_ref(value)
                self.assertEqual(ctx.exception.code, "INVALID_SCOPE_REF")

    def test_reject_too_long(self):
        """Reject overly long scope_ref."""
        with self.assertRaises(ValidationError) as ctx:
            validate_scope_ref("x" * 129)
        self.assertEqual(ctx.exception.code, "INVALID_SCOPE_REF")


class TestTimestampValidation(unittest.TestCase):
    """Test timestamp validation."""

    def test_valid_timestamp(self):
        """Accept valid UTC ISO-8601 Z timestamp."""
        result = validate_timestamp("2025-01-01T00:00:00Z", "since")
        self.assertEqual(result.year, 2025)

    def test_reject_missing_z(self):
        """Reject timestamp without Z."""
        with self.assertRaises(ValidationError) as ctx:
            validate_timestamp("2025-01-01T00:00:00", "since")
        self.assertEqual(ctx.exception.code, "INVALID_SINCE")

    def test_reject_non_string(self):
        """Non-string timestamps fail without a regex type error."""
        with self.assertRaises(ValidationError) as ctx:
            validate_timestamp(123, "since")
        self.assertEqual(ctx.exception.code, "INVALID_SINCE")

    def test_reject_invalid_format(self):
        """Reject invalid format."""
        with self.assertRaises(ValidationError) as ctx:
            validate_timestamp("not-a-date", "since")
        self.assertEqual(ctx.exception.code, "INVALID_SINCE")

    def test_reject_milliseconds(self):
        """Reject milliseconds."""
        with self.assertRaises(ValidationError) as ctx:
            validate_timestamp("2025-01-01T00:00:00.123Z", "since")
        self.assertEqual(ctx.exception.code, "INVALID_SINCE")


class TestNowValidation(unittest.TestCase):
    """Test now parameter validation."""

    def test_valid_now(self):
        """Accept valid UTC datetime."""
        now = datetime(2025, 1, 2, 12, 0, 0, tzinfo=timezone.utc)
        result = validate_now(now)
        self.assertEqual(result.microsecond, 0)

    def test_reject_naive(self):
        """Reject naive datetime."""
        now = datetime(2025, 1, 2, 12, 0, 0)
        with self.assertRaises(ValidationError) as ctx:
            validate_now(now)
        self.assertEqual(ctx.exception.code, "INVALID_NOW")

    def test_reject_non_utc(self):
        """Reject non-UTC datetime."""
        from datetime import timedelta
        now = datetime(2025, 1, 2, 12, 0, 0, tzinfo=timezone(timedelta(hours=5)))
        with self.assertRaises(ValidationError) as ctx:
            validate_now(now)
        self.assertEqual(ctx.exception.code, "INVALID_NOW")

    def test_truncate_microseconds(self):
        """Truncate microseconds to whole seconds."""
        now = datetime(2025, 1, 2, 12, 0, 0, 123456, tzinfo=timezone.utc)
        result = validate_now(now)
        self.assertEqual(result.microsecond, 0)
        self.assertEqual(result.second, 0)


class TestWindowValidation(unittest.TestCase):
    """Test window validation."""

    def test_valid_window(self):
        """Accept valid window."""
        since_dt, until_dt = validate_window("2025-01-01T00:00:00Z", "2025-01-02T00:00:00Z")
        self.assertEqual(since_dt.day, 1)
        self.assertEqual(until_dt.day, 2)

    def test_exactly_31_days_is_allowed(self):
        """The connector-owned maximum is inclusive."""
        since_dt, until_dt = validate_window(
            "2025-01-01T00:00:00Z",
            "2025-02-01T00:00:00Z",
        )
        self.assertEqual((until_dt - since_dt).days, MAX_WINDOW_DAYS)

    def test_window_longer_than_31_days_is_rejected(self):
        """Longer provider windows fail closed."""
        with self.assertRaises(ValidationError) as ctx:
            validate_window("2025-01-01T00:00:00Z", "2025-02-01T00:00:01Z")
        self.assertEqual(ctx.exception.code, "INVALID_WINDOW")

    def test_reject_equal_times(self):
        """Reject equal since and until."""
        with self.assertRaises(ValidationError) as ctx:
            validate_window("2025-01-01T00:00:00Z", "2025-01-01T00:00:00Z")
        self.assertEqual(ctx.exception.code, "INVALID_WINDOW")

    def test_reject_reversed_window(self):
        """Reject reversed window."""
        with self.assertRaises(ValidationError) as ctx:
            validate_window("2025-01-02T00:00:00Z", "2025-01-01T00:00:00Z")
        self.assertEqual(ctx.exception.code, "INVALID_WINDOW")

    def test_reject_future_until(self):
        """Reject future until timestamp."""
        future = "2030-01-01T00:00:00Z"
        past = "2025-01-01T00:00:00Z"
        with self.assertRaises(ValidationError) as ctx:
            validate_window(past, future)
        self.assertEqual(ctx.exception.code, "INVALID_WINDOW")


class TestPrivateInputValidation(unittest.TestCase):
    """Test private input validation."""

    def test_valid_token(self):
        """Accept valid token."""
        validate_token("abc123xyz")

    def test_reject_empty_token(self):
        """Reject empty token."""
        with self.assertRaises(ValidationError) as ctx:
            validate_token("")
        self.assertEqual(ctx.exception.code, "INVALID_TOKEN")

    def test_reject_non_string_token(self):
        """Non-string credentials fail with a structured error."""
        with self.assertRaises(ValidationError) as ctx:
            validate_token(123)
        self.assertEqual(ctx.exception.code, "INVALID_TOKEN")

    def test_reject_whitespace_token(self):
        """Reject token with whitespace."""
        with self.assertRaises(ValidationError) as ctx:
            validate_token("abc 123")
        self.assertEqual(ctx.exception.code, "INVALID_TOKEN")

    def test_valid_project_id(self):
        """Accept valid project ID."""
        validate_project_id("prj_abc123")

    def test_reject_invalid_project_id(self):
        """Reject invalid project ID."""
        with self.assertRaises(ValidationError) as ctx:
            validate_project_id("invalid")
        self.assertEqual(ctx.exception.code, "INVALID_PROJECT_ID")

    def test_reject_non_string_project_id(self):
        with self.assertRaises(ValidationError) as ctx:
            validate_project_id(123)
        self.assertEqual(ctx.exception.code, "INVALID_PROJECT_ID")

    def test_valid_team_id(self):
        """Accept valid team ID."""
        validate_team_id("team_abc123")

    def test_reject_invalid_team_id(self):
        """Reject invalid team ID."""
        with self.assertRaises(ValidationError) as ctx:
            validate_team_id("invalid")
        self.assertEqual(ctx.exception.code, "INVALID_TEAM_ID")

    def test_reject_non_string_team_id(self):
        with self.assertRaises(ValidationError) as ctx:
            validate_team_id(123)
        self.assertEqual(ctx.exception.code, "INVALID_TEAM_ID")


class TestStaleThresholdValidation(unittest.TestCase):
    """Test stale threshold validation."""

    def test_valid_threshold(self):
        """Accept valid threshold."""
        validate_stale_threshold(24)

    def test_reject_negative(self):
        """Reject negative threshold."""
        with self.assertRaises(ValidationError) as ctx:
            validate_stale_threshold(-1)
        self.assertEqual(ctx.exception.code, "INVALID_STALE_THRESHOLD")

    def test_reject_bool(self):
        """Reject boolean threshold."""
        with self.assertRaises(ValidationError) as ctx:
            validate_stale_threshold(True)
        self.assertEqual(ctx.exception.code, "INVALID_STALE_THRESHOLD")


class TestCredentialDetection(unittest.TestCase):
    """Test credential leakage detection."""

    def test_detect_bearer_token(self):
        """Detect Bearer token."""
        with self.assertRaises(SecurityError) as ctx:
            check_credential_leakage("Authorization: Bearer " + "a" * 32)
        self.assertEqual(ctx.exception.code, "CREDENTIAL_LEAK")

    def test_detect_project_id(self):
        """Detect Vercel project ID."""
        with self.assertRaises(SecurityError) as ctx:
            check_credential_leakage("projectId: prj_" + "a" * 24)
        self.assertEqual(ctx.exception.code, "CREDENTIAL_LEAK")

    def test_detect_team_id(self):
        """Detect Vercel team ID."""
        with self.assertRaises(SecurityError) as ctx:
            check_credential_leakage("teamId: team_" + "a" * 24)
        self.assertEqual(ctx.exception.code, "CREDENTIAL_LEAK")

    def test_detect_sensitive_value_overlap(self):
        """Detect sensitive value overlap."""
        with self.assertRaises(SecurityError) as ctx:
            check_credential_leakage("Token: mysecrettoken123", ["mysecrettoken123"])
        self.assertEqual(ctx.exception.code, "CREDENTIAL_LEAK")

    def test_allow_safe_text(self):
        """Allow safe text."""
        result = check_credential_leakage("Safe public text")
        self.assertIsNone(result)


class TestSerialization(unittest.TestCase):
    """Test envelope serialization."""

    def test_serialize_envelope(self):
        """Serialize envelope with newline."""
        envelope = {"key": "value"}
        result = serialize_envelope(envelope)
        self.assertTrue(result.endswith("\n"))
        self.assertIn('"key":"value"', result)

    def test_serialize_sorted(self):
        """Serialize with sorted keys."""
        envelope = {"b": 2, "a": 1}
        result = serialize_envelope(envelope)
        self.assertIn('"a":1,"b":2', result)

    def test_serialize_compact(self):
        """Serialize with compact separators."""
        envelope = {"key": "value"}
        result = serialize_envelope(envelope)
        self.assertNotIn(" ", result)

    def test_serialize_rejects_credentials(self):
        """Reject credentials in output."""
        envelope = {"token": "secret12345678"}
        with self.assertRaises(SecurityError):
            serialize_envelope(envelope, ["secret12345678"])


class TestReleaseScan(unittest.TestCase):
    """Test release scanner."""

    def test_detect_symlink_file(self):
        """Detect symlink files."""
        release_scan = _load_script("release_scan")
        with tempfile.TemporaryDirectory() as tmpdir:
            real_file = Path(tmpdir) / "real.txt"
            real_file.write_text("safe content")
            link_file = Path(tmpdir) / "link.txt"
            link_file.symlink_to(real_file)
            violations = release_scan.scan_file(link_file)
            self.assertTrue(any("Symlink" in v for v in violations))

    def test_detect_symlink_directory(self):
        """Detect symlink directories."""
        release_scan = _load_script("release_scan")
        with tempfile.TemporaryDirectory() as tmpdir:
            real_dir = Path(tmpdir) / "real_dir"
            real_dir.mkdir()
            link_dir = Path(tmpdir) / "link_dir"
            link_dir.symlink_to(real_dir)
            violations = release_scan.scan_file(link_dir)
            self.assertTrue(any("Symlink" in v for v in violations))

    def test_synthetic_exemption_exact(self):
        """Synthetic exemption only for exact matched text."""
        release_scan = _load_script("release_scan")
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.py"
            test_file.write_text('token = "prj_example123"')
            violations = release_scan.scan_file(test_file)
            self.assertEqual(len(violations), 0)

    def test_real_credential_detected(self):
        """Real credentials are detected even with synthetic-like patterns."""
        release_scan = _load_script("release_scan")
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.py"
            test_file.write_text('token = "prj_' + "a" * 24 + '"')
            violations = release_scan.scan_file(test_file)
            self.assertTrue(len(violations) > 0)

    def test_non_utf8_and_unreadable_fail_closed(self):
        """Unreadable and non-UTF8 files are release violations."""
        release_scan = _load_script("release_scan")
        with tempfile.TemporaryDirectory() as tmpdir:
            bad_file = Path(tmpdir) / "bad.bin"
            bad_file.write_bytes(b"\xff\xfe")
            self.assertTrue(any("Non-UTF8" in v for v in release_scan.scan_file(bad_file)))
            missing = Path(tmpdir) / "missing.txt"
            self.assertTrue(any("Unreadable" in v for v in release_scan.scan_file(missing)))

    def test_each_release_match_scanned_independently(self):
        """A synthetic match cannot exempt a separate real match."""
        release_scan = _load_script("release_scan")
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.py"
            test_file.write_text('prj_example123 prj_' + 'a' * 24)
            violations = release_scan.scan_file(test_file)
            self.assertTrue(any("Found forbidden pattern" in v for v in violations))

    def test_private_paths_and_provider_ids_scan_each_match(self):
        """Synthetic placeholders do not exempt later real private values."""
        release_scan = _load_script("release_scan")
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "private.txt"
            synthetic_path = "/" + "Users/example/project"
            real_path = "/" + "Users/navidbr/Projects/private"
            real_project = "prj_" + "a" * 16
            test_file.write_text(f"{synthetic_path} {real_path} prj_example123 {real_project}")
            violations = release_scan.scan_file(test_file)
            self.assertGreaterEqual(len(violations), 2)

    def test_release_symlinks_fail_before_ignored_names(self):
        """Ignored directory/suffix names cannot hide symlink entries."""
        release_scan = _load_script("release_scan")
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            real_dir = root / "real-dir"
            real_dir.mkdir()
            (root / ".venv").symlink_to(real_dir, target_is_directory=True)
            real_file = root / "real.txt"
            real_file.write_text("safe")
            (root / "ignored.pyc").symlink_to(real_file)
            stderr = StringIO()
            with redirect_stderr(stderr), redirect_stdout(StringIO()):
                result = release_scan.main(root)
            self.assertEqual(result, 1)
            self.assertIn("Symlink", stderr.getvalue())


class TestSecurityScan(unittest.TestCase):
    """Test security scanner."""

    def test_detect_symlink_directory(self):
        """Detect symlink directories."""
        security_scan = _load_script("security_scan")
        with tempfile.TemporaryDirectory() as tmpdir:
            real_dir = Path(tmpdir) / "real_dir"
            real_dir.mkdir()
            link_dir = Path(tmpdir) / "link_dir"
            link_dir.symlink_to(real_dir)
            violations = security_scan.scan_file(link_dir)
            self.assertTrue(any("Symlink" in v for v in violations))

    def test_detect_forbidden_dependency(self):
        """Detect forbidden dependencies."""
        security_scan = _load_script("security_scan")
        with tempfile.TemporaryDirectory() as tmpdir:
            pyproject = Path(tmpdir) / "pyproject.toml"
            pyproject.write_text('dependencies = ["requests>=2.0"]')
            violations = security_scan.scan_pyproject(pyproject)
            self.assertTrue(any("requests" in v for v in violations))

    def test_detect_bare_forbidden_dependency(self):
        """Bare dependency names are rejected instead of being ignored."""
        security_scan = _load_script("security_scan")
        with tempfile.TemporaryDirectory() as tmpdir:
            pyproject = Path(tmpdir) / "pyproject.toml"
            pyproject.write_text("dependencies = [requests]")
            violations = security_scan.scan_pyproject(pyproject)
            self.assertTrue(any("requests" in v for v in violations))

    def test_fail_closed_unreadable_pyproject(self):
        """Missing project metadata is not treated as safe."""
        security_scan = _load_script("security_scan")
        with tempfile.TemporaryDirectory() as tmpdir:
            missing = Path(tmpdir) / "pyproject.toml"
            violations = security_scan.scan_pyproject(missing)
            self.assertTrue(any("Unreadable" in v for v in violations))

    def test_no_http_import_exemption(self):
        """Forbidden urllib3 imports remain forbidden in every path."""
        security_scan = _load_script("security_scan")
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "http.py"
            source.write_text("import urllib3\n")
            violations = security_scan.scan_file(source, "src/evidence_loop_vercel_web_analytics/http.py")
            self.assertTrue(any("urllib3" in v for v in violations))

    def test_forbidden_process_variants_are_not_allowed(self):
        """Only artifact_smoke's exact subprocess.run match is excepted."""
        security_scan = _load_script("security_scan")
        with tempfile.TemporaryDirectory() as tmpdir:
            for expression in (
                "os." + "system('id')",
                "subprocess." + "call(['id'])",
                "subprocess." + "Popen(['id'])",
            ):
                source = Path(tmpdir) / "unsafe.py"
                source.write_text(expression)
                violations = security_scan.scan_file(source, "scripts/unsafe.py")
                self.assertTrue(violations, expression)

    def test_security_symlinks_fail_before_ignored_names(self):
        """Security scan checks ignored symlink directories and suffixes."""
        security_scan = _load_script("security_scan")
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "pyproject.toml").write_text("[project]\nname = 'fixture'\n")
            real_dir = root / "real-dir"
            real_dir.mkdir()
            (root / ".venv").symlink_to(real_dir, target_is_directory=True)
            real_file = root / "real.txt"
            real_file.write_text("safe")
            (root / "ignored.pyc").symlink_to(real_file)
            stderr = StringIO()
            with redirect_stderr(stderr), redirect_stdout(StringIO()):
                result = security_scan.main(root)
            self.assertEqual(result, 1)
            self.assertIn("Symlink", stderr.getvalue())

    def test_exact_subprocess_exception(self):
        """Only exact subprocess.run in artifact_smoke.py is allowed."""
        security_scan = _load_script("security_scan")
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.py"
            test_file.write_text('import subprocess\nsubprocess.' + 'run(["ls"])')
            violations = security_scan.scan_file(test_file, is_allowed=False)
            self.assertTrue(any("subprocess" in v for v in violations))


if __name__ == "__main__":
    unittest.main()
