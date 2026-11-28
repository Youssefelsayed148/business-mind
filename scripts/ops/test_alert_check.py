"""Unit tests for scripts/ops/alert_check.py. Fakes only: no network, no SMTP server, no Docker.
Run: python3 -m unittest scripts/ops/test_alert_check.py   (or python3 scripts/ops/test_alert_check.py)
"""
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import alert_check as ac  # noqa: E402

NOW = 1_800_000_000.0


def fake_fetch(table):
    def f(url, timeout):
        v = table[url]
        if isinstance(v, Exception):
            raise v
        return v
    return f


class FakeSMTP:
    sent = []
    logins = []
    tls = 0

    def __init__(self, host, port, timeout=0):
        self.host, self.port = host, port

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self, context=None):
        FakeSMTP.tls += 1

    def login(self, u, p):
        FakeSMTP.logins.append((u, p))

    def send_message(self, msg):
        FakeSMTP.sent.append(msg)


class ChecksTest(unittest.TestCase):
    def test_health_ok_and_status_codes(self):
        f = fake_fetch({"u1": (200, '{"status":"ok"}'), "u2": (503, ""), "u3": (200, "plain text")})
        self.assertTrue(ac.check_health("u1", f).ok)
        self.assertFalse(ac.check_health("u2", f).ok)
        self.assertIn("503", ac.check_health("u2", f).detail)
        self.assertTrue(ac.check_health("u3", f).ok)

    def test_health_200_with_error_field(self):
        f = fake_fetch({"u": (200, '{"database":"ok","redis":"error"}')})
        r = ac.check_health("u", f)
        self.assertFalse(r.ok)
        self.assertIn("redis", r.detail)

    def test_health_not_ready_status(self):
        f = fake_fetch({"u": (200, '{"status":"not_ready"}')})
        self.assertFalse(ac.check_health("u", f).ok)

    def test_health_connection_error(self):
        f = fake_fetch({"u": ConnectionRefusedError("refused")})
        r = ac.check_health("u", f)
        self.assertFalse(r.ok)
        self.assertIn("ConnectionRefusedError", r.detail)

    def test_backup_age(self):
        fresh = lambda p: NOW - 3600
        old = lambda p: NOW - 30 * 3600
        none = lambda p: None
        self.assertTrue(ac.check_backup_age("/b", 26, NOW, fresh).ok)
        self.assertFalse(ac.check_backup_age("/b", 26, NOW, old).ok)
        self.assertFalse(ac.check_backup_age("/b", 26, NOW, none).ok)

    def test_newest_mtime_real_dir(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(ac.newest_mtime(Path(d)))
            (Path(d) / "x").write_text("1")
            self.assertIsNotNone(ac.newest_mtime(Path(d)))
        self.assertIsNone(ac.newest_mtime(Path("/nonexistent-dir-xyz")))

    def test_disk_threshold_boundary(self):
        self.assertTrue(ac.check_disk("/", 85, lambda p: (100, 85)).ok)
        self.assertFalse(ac.check_disk("/", 85, lambda p: (100, 86)).ok)
        self.assertFalse(ac.check_disk("/", 85, lambda p: (0, 0)).ok)

    def test_command_expect_and_queue(self):
        ok = lambda argv, t: (0, "PONG\n")
        bad = lambda argv, t: (1, "")
        self.assertTrue(ac.check_command_expect("r", "redis-cli ping", "PONG", ok).ok)
        self.assertFalse(ac.check_command_expect("r", "redis-cli ping", "PONG", bad).ok)
        self.assertFalse(ac.check_command_expect("r", "redis-cli ping", "PONG", lambda a, t: (0, "nope")).ok)
        self.assertTrue(ac.check_queue_length("q", "x", 500, lambda a, t: (0, "12\n")).ok)
        self.assertFalse(ac.check_queue_length("q", "x", 500, lambda a, t: (0, "501\n")).ok)
        self.assertFalse(ac.check_queue_length("q", "x", 500, lambda a, t: (0, "abc")).ok)

        def boom(a, t):
            raise FileNotFoundError("docker")
        self.assertFalse(ac.check_queue_length("q", "x", 500, boom).ok)

    def test_command_is_not_run_through_a_shell(self):
        seen = []
        ac.check_command_expect("r", "echo 'a b' ; rm -rf x", "z", lambda a, t: (seen.append(a) or (0, "")))
        self.assertEqual(seen[0], ["echo", "a b", ";", "rm", "-rf", "x"])


class DecideTest(unittest.TestCase):
    F = [ac.Result("a", False, "x")]

    def test_new_failure_alerts(self):
        action, st = ac.decide(self.F, {}, NOW, 6)
        self.assertEqual(action, "alert")
        self.assertEqual(st["failing"], ["a"])

    def test_same_failure_suppressed_then_repeats(self):
        _, st = ac.decide(self.F, {}, NOW, 6)
        self.assertEqual(ac.decide(self.F, st, NOW + 3600, 6)[0], "none")
        self.assertEqual(ac.decide(self.F, st, NOW + 7 * 3600, 6)[0], "alert")

    def test_changed_failure_set_alerts(self):
        _, st = ac.decide(self.F, {}, NOW, 6)
        more = self.F + [ac.Result("b", False, "y")]
        self.assertEqual(ac.decide(more, st, NOW + 60, 6)[0], "alert")

    def test_recovery(self):
        _, st = ac.decide(self.F, {}, NOW, 6)
        self.assertEqual(ac.decide([], st, NOW + 60, 6)[0], "recovery")
        self.assertEqual(ac.decide([], {"failing": []}, NOW, 6)[0], "none")


BASE_ENV = {
    "ALERT_SMTP_HOST": "smtp.example.invalid", "ALERT_SMTP_PORT": "587",
    "ALERT_SMTP_USER": "user", "ALERT_SMTP_PASSWORD": "SECRET-PLACEHOLDER",
    "ALERT_MAIL_FROM": "alerts@example.invalid", "ALERT_MAIL_TO": "owner@example.invalid, second@example.invalid",
    "ALERT_DISK_PATHS": "/",
}


def run_main(argv, env, fetch=None, **kw):
    out, err = io.StringIO(), io.StringIO()
    FakeSMTP.sent, FakeSMTP.logins, FakeSMTP.tls = [], [], 0
    rc = ac.main(argv, env=env, now=NOW, fetch=fetch or fake_fetch({}), smtp_factory=FakeSMTP,
                 usage_fn=lambda p: (100, 10), out=out, err=err, hostname="testhost", **kw)
    return rc, out.getvalue(), err.getvalue()


class MainTest(unittest.TestCase):
    def test_all_ok_sends_nothing_exit_0(self):
        env = dict(BASE_ENV, ALERT_HEALTH_URLS="http://h/health")
        rc, out, err = run_main([], env, fake_fetch({"http://h/health": (200, "{}")}))
        self.assertEqual(rc, 0)
        self.assertEqual(FakeSMTP.sent, [])

    def test_failure_sends_one_mail_exit_1_with_tls_and_login(self):
        env = dict(BASE_ENV, ALERT_HEALTH_URLS="http://h/health,http://i/health")
        rc, out, err = run_main([], env, fake_fetch({"http://h/health": (500, ""), "http://i/health": (200, "{}")}))
        self.assertEqual(rc, 1)
        self.assertEqual(len(FakeSMTP.sent), 1)
        msg = FakeSMTP.sent[0]
        self.assertIn("ALERT on testhost", msg["Subject"])
        self.assertIn("1 check(s) failing", msg["Subject"])
        self.assertIn("second@example.invalid", msg["To"])
        self.assertEqual(FakeSMTP.tls, 1)
        self.assertEqual(FakeSMTP.logins, [("user", "SECRET-PLACEHOLDER")])
        self.assertNotIn("SECRET-PLACEHOLDER", msg.get_content() + out + err)

    def test_dry_run_prints_and_sends_nothing(self):
        env = dict(BASE_ENV, ALERT_HEALTH_URLS="http://h/health")
        rc, out, err = run_main(["--dry-run"], env, fake_fetch({"http://h/health": (500, "")}))
        self.assertEqual(rc, 1)
        self.assertEqual(FakeSMTP.sent, [])
        self.assertIn("DRY RUN", out)
        self.assertIn("Subject: [business-mind] ALERT", out)
        self.assertNotIn("SECRET-PLACEHOLDER", out)

    def test_dry_run_works_without_mail_settings(self):
        rc, out, err = run_main(["--dry-run", "--test-alert"], {})
        self.assertEqual(rc, 0)
        self.assertIn("TEST alert", out)

    def test_test_alert_sends_mail_even_when_all_ok(self):
        rc, out, err = run_main(["--test-alert"], dict(BASE_ENV))
        self.assertEqual(rc, 0)
        self.assertEqual(len(FakeSMTP.sent), 1)
        self.assertIn("TEST alert", FakeSMTP.sent[0]["Subject"])

    def test_missing_mail_settings_exit_2(self):
        env = {"ALERT_HEALTH_URLS": "http://h/health"}
        rc, out, err = run_main([], env, fake_fetch({"http://h/health": (500, "")}))
        self.assertEqual(rc, 2)
        self.assertIn("ALERT_SMTP_HOST", err)

    def test_smtp_failure_exit_2_without_leaking(self):
        class Bad(FakeSMTP):
            def send_message(self, msg):
                raise OSError("boom SECRET-PLACEHOLDER")
        out, err = io.StringIO(), io.StringIO()
        env = dict(BASE_ENV, ALERT_HEALTH_URLS="http://h/health")
        rc = ac.main([], env=env, now=NOW, fetch=fake_fetch({"http://h/health": (500, "")}),
                     smtp_factory=Bad, usage_fn=lambda p: (100, 10), out=out, err=err, hostname="t")
        self.assertEqual(rc, 2)
        self.assertNotIn("SECRET-PLACEHOLDER", out.getvalue() + err.getvalue())

    def test_state_file_suppresses_repeat_and_mails_recovery(self):
        with tempfile.TemporaryDirectory() as d:
            env = dict(BASE_ENV, ALERT_HEALTH_URLS="http://h/health", ALERT_STATE_FILE=str(Path(d) / "s.json"))
            bad = fake_fetch({"http://h/health": (500, "")})
            good = fake_fetch({"http://h/health": (200, "{}")})
            run_main([], env, bad)
            self.assertEqual(len(FakeSMTP.sent), 1)
            rc, out, _ = run_main([], env, bad)
            self.assertEqual((rc, len(FakeSMTP.sent)), (1, 0))
            self.assertIn("not mailing again", out)
            rc, _, _ = run_main([], env, good)
            self.assertEqual(rc, 0)
            self.assertEqual(len(FakeSMTP.sent), 1)
            self.assertIn("RECOVERED", FakeSMTP.sent[0]["Subject"])
            self.assertEqual(json.loads(Path(d, "s.json").read_text())["failing"], [])

    def test_disk_failure_detected(self):
        out, err = io.StringIO(), io.StringIO()
        FakeSMTP.sent = []
        rc = ac.main(["--dry-run"], env=dict(BASE_ENV), now=NOW, usage_fn=lambda p: (100, 95),
                     smtp_factory=FakeSMTP, out=out, err=err, hostname="t")
        self.assertEqual(rc, 1)
        self.assertIn("95.0% used", out.getvalue())

    def test_bad_number_in_config_exit_2(self):
        env = dict(BASE_ENV, ALERT_BACKUP_DIR="/b", ALERT_BACKUP_MAX_AGE_HOURS="abc")
        rc, out, err = run_main(["--dry-run"], env)
        self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main()
