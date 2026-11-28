"""Unit tests for scripts/ops/load_saas_api.py (statistics, safety checks, and a run against a
local fake HTTP server on loopback; no real service, no network).
Run: python3 scripts/ops/test_load_saas_api.py
"""
import io
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import load_saas_api as la  # noqa: E402


class StatsTest(unittest.TestCase):
    def test_percentile_known_values(self):
        v = list(map(float, range(1, 101)))  # 1..100
        self.assertAlmostEqual(la.percentile(v, 50), 50.5)
        self.assertAlmostEqual(la.percentile(v, 95), 95.05)
        self.assertAlmostEqual(la.percentile(v, 99), 99.01)
        self.assertEqual(la.percentile(v, 0), 1.0)
        self.assertEqual(la.percentile(v, 100), 100.0)

    def test_percentile_edge_cases(self):
        self.assertTrue(la.percentile([], 50) != la.percentile([], 50))  # nan
        self.assertEqual(la.percentile([7.0], 99), 7.0)
        self.assertEqual(la.percentile([1.0, 3.0], 50), 2.0)

    def test_summarize(self):
        s = la.summarize("x", [10, 20, 30, 40], errors=1, elapsed_s=2.0)
        self.assertEqual(s.requests, 4)
        self.assertEqual(s.errors, 1)
        self.assertAlmostEqual(s.error_rate, 25.0)
        self.assertAlmostEqual(s.rps, 2.0)
        self.assertAlmostEqual(s.p50, 25.0)

    def test_summarize_unsorted_input_and_empty(self):
        self.assertAlmostEqual(la.summarize("x", [30, 10, 20], 0, 1).p50, 20.0)
        e = la.summarize("x", [], 0, 1.0)
        self.assertEqual((e.requests, e.error_rate, e.rps), (0, 0.0, 0.0))
        self.assertIn("n/a", la.format_table([e]))

    def test_table_has_columns(self):
        t = la.format_table([la.summarize("/health", [1, 2, 3], 0, 1.0)])
        for col in ("path", "requests", "err %", "req/s", "p50 ms", "p95 ms", "p99 ms", "/health"):
            self.assertIn(col, t)


class SafetyTest(unittest.TestCase):
    def test_staging_host_detection(self):
        for h in ("localhost", "127.0.0.1", "::1", "saas-api.staging.example.com", "staging.example.com",
                  "api-staging.example.com", "stg-api.example.com"):
            self.assertTrue(la.is_staging_host(h), h)
        for h in ("saas.example.com", "app.example.com", "stagingfoo.example.com", "", "10.0.0.5"):
            self.assertFalse(la.is_staging_host(h), h)

    def test_cookie_normalization(self):
        self.assertEqual(la.normalize_cookie("abc"), "chatbot_session=abc")
        self.assertEqual(la.normalize_cookie("other=abc"), "other=abc")
        self.assertEqual(la.normalize_cookie("  "), "")

    def test_auth_paths(self):
        self.assertEqual(la.build_auth_paths(None, []), ["/api/v1/auth/me"])
        self.assertIn("/api/v1/tenants/t-1/inbox", la.build_auth_paths("t-1", []))
        self.assertEqual(la.build_auth_paths("t-1", ["/x"]), ["/x"])
        with self.assertRaises(ValueError):
            la.build_auth_paths("../x", [])

    def test_refuses_non_staging_host(self):
        err = io.StringIO()
        rc = la.main(["--base-url", "https://app.example.com"], env={}, out=io.StringIO(), err=err)
        self.assertEqual(rc, 2)
        self.assertIn("does not look like staging", err.getvalue())

    def test_caps_and_missing_cookie(self):
        e = io.StringIO()
        self.assertEqual(la.main(["--base-url", "http://localhost:1", "--concurrency", "101"], env={}, out=io.StringIO(), err=e), 2)
        self.assertEqual(la.main(["--base-url", "http://localhost:1", "--duration", "301"], env={}, out=io.StringIO(), err=e), 2)
        e2 = io.StringIO()
        self.assertEqual(la.main(["--base-url", "http://localhost:1", "--auth"], env={}, out=io.StringIO(), err=e2), 2)
        self.assertIn("LOAD_SESSION_COOKIE", e2.getvalue())


class FakeHandler(BaseHTTPRequestHandler):
    methods_seen = []
    cookies_seen = []
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def do_GET(self):
        FakeHandler.methods_seen.append("GET")
        FakeHandler.cookies_seen.append((self.path, self.headers.get("Cookie")))
        if self.path.startswith("/api/v1/auth/me"):
            ok = self.headers.get("Cookie") == "chatbot_session=GOODVALUE"
            code = 200 if ok else 401
        elif self.path == "/ready":
            code = 503
        else:
            code = 200
        body = b"{}"
        self.send_response(code)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        FakeHandler.methods_seen.append("POST")
        self.send_response(405)
        self.send_header("Content-Length", "0")
        self.end_headers()


class RunTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), FakeHandler)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def setUp(self):
        FakeHandler.methods_seen, FakeHandler.cookies_seen = [], []

    def test_unauth_run_counts_errors_and_uses_get_only(self):
        out, err = io.StringIO(), io.StringIO()
        rc = la.main(["--base-url", f"http://127.0.0.1:{self.port}", "--concurrency", "3", "--duration", "1"],
                     env={}, out=out, err=err)
        self.assertEqual(rc, 0, err.getvalue())
        text = out.getvalue()
        self.assertIn("TOTAL", text)
        self.assertIn("/ready", text)
        self.assertEqual(set(FakeHandler.methods_seen), {"GET"})
        # /ready always answers 503: its row must show errors, /health must not.
        rows = {l.split()[0]: l.split() for l in text.splitlines() if l.startswith("/") or l.startswith("TOTAL")}
        self.assertEqual(rows["/health"][2], "0")
        self.assertEqual(rows["/ready"][2], rows["/ready"][1])  # errors == requests

    def test_auth_run_sends_cookie_and_hides_it(self):
        out, err = io.StringIO(), io.StringIO()
        rc = la.main(["--base-url", f"http://127.0.0.1:{self.port}", "--concurrency", "2", "--duration", "1", "--auth",
                      "--path", "/health"], env={"LOAD_SESSION_COOKIE": "GOODVALUE"}, out=out, err=err)
        self.assertEqual(rc, 0, err.getvalue())
        self.assertIn("/api/v1/auth/me", out.getvalue())
        self.assertNotIn("GOODVALUE", out.getvalue() + err.getvalue())
        self.assertTrue(any(c == "chatbot_session=GOODVALUE" for p, c in FakeHandler.cookies_seen if p.startswith("/api/v1/auth/me")))
        self.assertTrue(all(c is None for p, c in FakeHandler.cookies_seen if p == "/health"))

    def test_bad_cookie_aborts_at_preflight(self):
        out, err = io.StringIO(), io.StringIO()
        rc = la.main(["--base-url", f"http://127.0.0.1:{self.port}", "--duration", "1", "--auth"],
                     env={"LOAD_SESSION_COOKIE": "WRONG"}, out=out, err=err)
        self.assertEqual(rc, 2)
        self.assertIn("Preflight failed", err.getvalue())
        self.assertNotIn("WRONG", out.getvalue() + err.getvalue())

    def test_connection_refused_counts_as_errors(self):
        rows, total, _ = la.run_load("http://127.0.0.1:1", [("/health", "")], 2, 0.5, 1.0)
        self.assertGreater(total.requests, 0)
        self.assertEqual(total.errors, total.requests)


if __name__ == "__main__":
    unittest.main()
