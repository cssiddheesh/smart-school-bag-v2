import re
import unittest
from pathlib import Path
from unittest import mock

from tests.helpers import AppCase, TOKEN

ROOT = Path(__file__).resolve().parent.parent


class PageTests(AppCase):
    def test_all_pages_render(self):
        c = self.client()
        for url in ("/", "/exhibition", "/books", "/timetable", "/history", "/history?view=sessions", "/settings",
                    "/timetable?day=999", "/history?page=999&q=%25&session=x", "/dashboard"):
            response = c.get(url, follow_redirects=True)
            self.assertEqual(response.status_code, 200, url)

    def test_dashboard_embeds_state_and_sends_security_headers(self):
        response = self.client().get("/")
        html = response.get_data(as_text=True)
        self.assertIn('id="initial-state"', html)
        self.assertIn('id="voice-toggle"', html)
        self.assertIn('id="voice-repeat"', html)
        self.assertIn("default-src 'self'", response.headers["Content-Security-Policy"])
        self.assertEqual(response.headers["X-Frame-Options"], "DENY")
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")

    def test_session_page_and_history_after_scans(self):
        self.card("English", "AAAA1111")
        self.scan("AAAA1111")
        self.scan("AAAA1111", "SIMULATION")
        c = self.client()
        page = c.get("/sessions/1").get_data(as_text=True)
        self.assertIn("Simulated", page)
        self.assertIn("Real card", page)
        self.assertEqual(c.get("/sessions/42").status_code, 404)

    def test_history_filters(self):
        self.card("English", "AAAA1111")
        self.card("Tamil", "BBBB2222")
        self.scan("AAAA1111", "RFID")
        self.scan("BBBB2222", "SIMULATION")
        c = self.client()
        both = c.get("/history").get_data(as_text=True)
        self.assertIn("English", both)
        self.assertIn("Tamil", both)
        only_sim = c.get("/history?source=SIMULATION").get_data(as_text=True)
        self.assertIn("Tamil", only_sim)
        self.assertNotIn(">English<", only_sim.replace("English</td>", ">English<"))
        search = c.get("/history?q=eng").get_data(as_text=True)
        self.assertIn("English", search)
        self.assertNotIn("Tamil", search)
        self.assertIn("Nothing matches", c.get("/history?q=zzz").get_data(as_text=True))
        self.assertEqual(c.get("/history?view=sessions&status=completed").status_code, 200)

    def test_clear_history_backs_up_first_and_keeps_active_session(self):
        self.card("English", "AAAA1111")
        self.scan("AAAA1111")
        self.s.sessions.reset()  # session 1 abandoned, session 2 active
        self.scan("AAAA1111", "SIMULATION")
        c = self.client()
        self.post_form(c, "/history/clear")
        self.assertEqual(self.sql("SELECT COUNT(*) FROM packing_sessions")[0][0], 1)
        self.assertEqual(self.sql("SELECT COUNT(*) FROM scan_history")[0][0], 1)  # active session's scan kept
        self.assertEqual(len(list((self.root / "backups").glob("*pre-clear.db"))), 1)


class ApiTests(AppCase):
    def test_state_envelope_and_revision_shortcut(self):
        c = self.client()
        body = c.get("/api/state").get_json()
        self.assertTrue(body["success"])
        self.assertTrue(body["data"]["changed"])
        again = c.get(f"/api/state?rev={body['data']['revision']}").get_json()
        self.assertEqual(again["data"], {"changed": False, "revision": body["data"]["revision"]})
        self.post_json(c, "/api/demo/scan", {"book_id": self.book("English")["id"]})
        self.assertTrue(c.get(f"/api/state?rev={body['data']['revision']}").get_json()["data"]["changed"])

    def test_demo_scan_to_ready_flow(self):
        c = self.client()
        self.post_json(c, "/api/session/start")
        for name in ("English", "Mathematics", "Computer Science"):
            r = self.post_json(c, "/api/demo/scan", {"book_id": self.book(name)["id"]}).get_json()
            self.assertEqual(r["data"]["scan"]["source"], "SIMULATION")
        self.assertEqual(r["data"]["state"]["percentage"], 60)
        self.assertEqual(self.post_json(c, "/api/session/complete").status_code, 409)
        for name in ("Science", "Tamil"):
            r = self.post_json(c, "/api/demo/scan", {"book_id": self.book(name)["id"]}).get_json()
        self.assertTrue(r["data"]["scan"]["became_ready"])
        done = self.post_json(c, "/api/session/complete").get_json()
        self.assertEqual(done["data"]["summary"]["packed_count"], 5)

    def test_unknown_card_and_reset(self):
        c = self.client()
        self.assertEqual(self.post_json(c, "/api/demo/scan", {"unknown": True}).get_json()["message"], "Unknown RFID card")
        self.assertEqual(self.post_json(c, "/api/session/reset").status_code, 200)

    def test_invalid_requests_get_consistent_errors(self):
        c = self.client()
        cases = [
            (self.post_json(c, "/api/day", {"day_id": "abc"}), 400, "validation_error"),
            (self.post_json(c, "/api/day", {"day_id": 9999}), 404, "not_found"),
            (self.post_json(c, "/api/day", ["not", "an", "object"]), 400, "validation_error"),
            (self.post_json(c, "/api/demo/scan", {"book_id": 9999}), 404, "not_found"),
            (self.post_json(c, "/api/demo/scan", {"book_id": True}), 400, "validation_error"),
            (self.post_json(c, "/api/session/complete"), 409, "no_session"),
            (c.get("/api/session/start"), 405, "http_405"),
            (c.get("/api/nope"), 404, "http_404"),
        ]
        for response, status, code in cases:
            body = response.get_json()
            self.assertEqual((response.status_code, body["success"], body["error"]["code"]), (status, False, code))
            self.assertIn("message", body)

    def test_malformed_json_does_not_crash(self):
        c = self.client()
        r = c.post("/api/day", data="{not json", headers={"X-CSRF-Token": TOKEN, "Content-Type": "application/json"})
        self.assertIn(r.status_code, (400, 415))
        self.assertFalse(r.get_json()["success"])

    def test_demo_can_be_switched_off(self):
        c = self.client()
        self.s.settings.update({"demo_enabled": False})
        r = self.post_json(c, "/api/demo/scan", {"unknown": True})
        self.assertEqual((r.status_code, r.get_json()["error"]["code"]), (403, "demo_disabled"))
        self.assertEqual(c.get("/exhibition").status_code, 302)
        self.assertNotIn("Exhibition</span>", c.get("/").get_data(as_text=True))

    def test_reader_endpoint_reports_status_honestly(self):
        data = self.client().get("/api/reader").get_json()["data"]
        self.assertEqual(data["status"]["state"], "disabled")
        self.assertEqual(data["raw"], [])

    def test_healthz(self):
        body = self.client().get("/healthz").get_json()
        self.assertEqual((body["success"], body["data"]["status"]), (True, "ok"))


class ErrorHandlingTests(AppCase):
    def test_unexpected_exceptions_never_leak_tracebacks(self):
        c = self.client()
        with mock.patch.object(self.s.state, "snapshot", side_effect=RuntimeError("secret internal detail")):
            page = c.get("/")
            api = c.get("/api/state")
        for response in (page, api):
            text = response.get_data(as_text=True)
            self.assertEqual(response.status_code, 500)
            self.assertNotIn("Traceback", text)
            self.assertNotIn("secret internal detail", text)
        self.assertRegex(page.get_data(as_text=True), r"Reference: <span class=\"raw\">[0-9a-f]{6}")
        self.assertEqual(api.get_json()["error"]["code"], "internal_error")

    def test_database_errors_become_friendly_503(self):
        import sqlite3
        c = self.client()
        with mock.patch.object(self.s.state, "snapshot", side_effect=sqlite3.OperationalError("database is locked")):
            response = c.get("/")
        self.assertEqual(response.status_code, 503)
        self.assertIn("temporarily unavailable", response.get_data(as_text=True))
        self.assertNotIn("locked", response.get_data(as_text=True))

    def test_404_page_is_friendly(self):
        r = self.client().get("/missing")
        self.assertEqual(r.status_code, 404)
        self.assertIn("does not exist", r.get_data(as_text=True))

    def test_oversized_body_is_rejected(self):
        r = self.client().post("/api/day", data=b"x" * 200_000,
                               headers={"X-CSRF-Token": TOKEN, "Content-Type": "application/json"})
        self.assertEqual(r.status_code, 413)


class SecurityTests(AppCase):
    def test_csrf_is_required_everywhere(self):
        c = self.app.test_client()
        c.get("/")  # obtains a session, but we send no token
        json_response = c.post("/api/session/start", json={})
        self.assertEqual((json_response.status_code, json_response.get_json()["error"]["code"]), (403, "csrf_failed"))
        form_response = c.post("/books/add", data={"name": "Hack"})
        self.assertEqual(form_response.status_code, 403)
        self.assertNotIn("Hack", [b["name"] for b in self.s.books.list_with_status()])
        wrong = c.post("/api/session/start", json={}, headers={"X-CSRF-Token": "wrong"})
        self.assertEqual(wrong.status_code, 403)

    def test_page_tokens_work(self):
        c = self.app.test_client()
        token = re.search(r'name="csrf-token" content="([^"]+)"', c.get("/").get_data(as_text=True)).group(1)
        self.assertEqual(c.post("/api/session/start", json={}, headers={"X-CSRF-Token": token}).status_code, 200)

    def test_user_text_is_escaped(self):
        c = self.client()
        self.post_form(c, "/books/add", {"name": "<script>alert(1)</script>"})
        for url in ("/books", "/timetable", "/history", "/exhibition"):
            html = c.get(url).get_data(as_text=True)
            self.assertNotIn("<script>alert(1)</script>", html, url)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", c.get("/books").get_data(as_text=True))

    def test_sql_injection_attempts_are_inert(self):
        c = self.client()
        evil = "'; DROP TABLE books; --"
        for url in (f"/history?q={evil}", f"/history?day={evil}&source={evil}&outcome={evil}&session={evil}&page={evil}",
                    f"/timetable?day={evil}"):
            self.assertEqual(c.get(url).status_code, 200, url)
        self.post_form(c, "/books/add", {"name": evil})
        self.assertEqual(self.sql("SELECT COUNT(*) FROM books")[0][0], 6)  # stored as plain text

    def test_open_redirects_are_blocked(self):
        c = self.client()
        r = self.post_form(c, "/books/add", {"name": "", "return_to": "//evil.example/x"})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r.headers["Location"].endswith("/books"))
        r = self.post_form(c, "/books/add", {"name": "", "return_to": "https://evil.example"})
        self.assertNotIn("evil", r.headers["Location"])
        r = self.post_form(c, "/books/add", {"name": "", "return_to": "/timetable"})
        self.assertTrue(r.headers["Location"].endswith("/timetable"))

    def test_secret_key_is_generated_not_hard_coded(self):
        from app import create_app
        other = create_app({"DATA_DIR": self.root / "k", "DATABASE_PATH": self.root / "k" / "x.db",
                            "BACKUP_DIR": self.root / "k" / "b", "LOG_DIR": self.root / "k" / "l",
                            "START_READER": False, "SECRET_KEY": None})
        key = (self.root / "k" / "secret_key").read_text().strip()
        self.assertEqual(len(key), 64)
        self.assertEqual(other.config["SECRET_KEY"], key)

    def test_no_external_resources_or_inline_styles_in_front_end(self):
        pattern = re.compile(r"https?://(?!www\.w3\.org/2000/svg)")
        for path in list((ROOT / "app/templates").rglob("*.html")) + list((ROOT / "app/static").rglob("*.*")):
            text = path.read_text(encoding="utf-8")
            self.assertIsNone(pattern.search(text), f"external URL in {path.name}")
            if path.suffix == ".html":
                self.assertNotIn('style="', text, f"inline style in {path.name}")
                self.assertNotIn("onclick=", text)

    def test_static_files_are_served_locally(self):
        c = self.client()
        for url in ("/static/css/app.css", "/static/js/live.js", "/static/icons.svg", "/static/favicon.svg"):
            with c.get(url) as response:
                self.assertEqual(response.status_code, 200, url)
        self.assertEqual(c.get("/static/../app.py").status_code, 404)


class AdminFormTests(AppCase):
    def test_book_crud_via_forms(self):
        c = self.client()
        self.post_form(c, "/books/add", {"name": "Geography"})
        geo = self.book("Geography")["id"]
        self.post_form(c, f"/books/{geo}/uid", {"rfid_uid": "geo-0001"})
        self.assertEqual(self.book("Geography")["rfid_uid"], "GEO0001")
        dup = self.post_form(c, f"/books/{self.book('English')['id']}/uid", {"rfid_uid": "GEO0001"}, follow_redirects=True)
        self.assertIn("already assigned to", dup.get_data(as_text=True))
        self.post_form(c, f"/books/{geo}/active", {"active": "0"})
        self.assertEqual(self.book("Geography")["is_active"], 0)
        self.post_form(c, f"/books/{geo}/delete")
        self.assertNotIn("Geography", [b["name"] for b in self.s.books.list_with_status()])

    def test_timetable_forms(self):
        c = self.client()
        self.post_form(c, "/timetable/days/add", {"name": "Saturday"})
        sat = self.day("Saturday")["id"]
        self.post_form(c, f"/timetable/days/{sat}/entries/add", {"book_id": str(self.book("Tamil")["id"])})
        self.assertEqual(len(self.s.timetable.day_view(sat)["entries"]), 1)
        entry = self.s.timetable.day_view(sat)["entries"][0]["id"]
        self.post_form(c, f"/timetable/entries/{entry}/remove")
        self.assertEqual(len(self.s.timetable.day_view(sat)["entries"]), 0)
        r = self.post_form(c, f"/timetable/days/{sat}/entries/add", {"book_id": "abc"}, follow_redirects=True)
        self.assertEqual(r.status_code, 200)

    def test_settings_validation_and_saving(self):
        c = self.client()
        bad = self.post_form(c, "/settings/general", {"school_name": "X", "student_name": "", "default_day": "Monday",
                                                      "timezone": "Mars/Phobos", "debounce_seconds": "3"}, follow_redirects=True)
        self.assertIn("not recognised", bad.get_data(as_text=True))
        self.assertEqual(self.s.settings.get("timezone"), "Asia/Kolkata")
        self.post_form(c, "/settings/general", {"school_name": "Green Valley", "student_name": "Asha", "default_day": "Friday",
                                                "timezone": "UTC", "debounce_seconds": "5", "auto_start_session": "on"})
        cfg = self.s.settings.get_all()
        self.assertEqual((cfg["school_name"], cfg["default_day"], cfg["timezone"], cfg["debounce_seconds"]),
                         ("Green Valley", "Friday", "UTC", 5))
        for field, value in (("debounce_seconds", "999"), ("default_day", "Funday")):
            data = {"school_name": "X", "student_name": "", "default_day": "Monday", "timezone": "UTC", "debounce_seconds": "3"}
            data[field] = value
            r = self.post_form(c, "/settings/general", data, follow_redirects=True)
            self.assertIn("toast--error", r.get_data(as_text=True))

    def test_reader_settings_are_validated(self):
        c = self.client()
        r = self.post_form(c, "/settings/reader", {"reader_type": "keyboard", "reader_device": "/dev/x; rm -rf /",
                                                   "reader_baud": "9600"}, follow_redirects=True)
        self.assertIn("Device paths may only contain", r.get_data(as_text=True))
        self.assertEqual(self.s.settings.get("reader_type"), "none")
        self.post_form(c, "/settings/reader", {"reader_type": "serial", "reader_device": "/dev/ttyUSB0", "reader_baud": "9600"})
        self.assertEqual(self.s.settings.get("reader_type"), "serial")
        self.assertFalse(self.s.settings.get("demo_enabled"))  # checkbox absent = off


class AdminPinTests(AppCase):
    def test_pin_protects_admin_but_not_the_exhibition_workflow(self):
        c = self.client()
        self.post_form(c, "/settings/pin", {"pin": "1234", "pin_confirm": "1234"})
        self.assertTrue(self.s.settings.get("admin_pin").startswith("pbkdf2$"))
        self.assertNotIn("1234", self.s.settings.get("admin_pin"))  # stored hashed, never plain
        other = self.client()  # a different browser that hasn't unlocked
        r = other.get("/books")
        self.assertEqual(r.status_code, 302)
        self.assertIn("/unlock", r.headers["Location"])
        self.assertEqual(other.get("/").status_code, 200)
        self.assertEqual(other.get("/history").status_code, 200)
        self.assertEqual(self.post_json(other, "/api/demo/scan", {"unknown": True}).status_code, 200)
        locked = self.post_json(other, "/api/capture/start")
        self.assertEqual((locked.status_code, locked.get_json()["error"]["code"]), (401, "admin_required"))
        self.assertEqual(self.post_form(other, "/books/add", {"name": "Nope"}).status_code, 302)
        self.assertNotIn("Nope", [b["name"] for b in self.s.books.list_with_status()])

    def test_unlock_flow_and_lockout(self):
        import app.security as security
        self.s.settings.update({"admin_pin": security.hash_pin("4321")})
        c = self.client()
        for _ in range(5):
            self.post_form(c, "/unlock", {"pin": "0000", "next": "/books"})
        r = self.post_form(c, "/unlock", {"pin": "4321", "next": "/books"}, follow_redirects=True)
        self.assertIn("Too many attempts", r.get_data(as_text=True))
        security._attempts.clear()
        ok = self.post_form(c, "/unlock", {"pin": "4321", "next": "/books"})
        self.assertTrue(ok.headers["Location"].endswith("/books"))
        self.assertEqual(c.get("/books").status_code, 200)
        self.post_form(c, "/lock")
        self.assertEqual(c.get("/books").status_code, 302)

    def test_unlock_redirect_cannot_leave_the_site(self):
        import app.security as security
        self.s.settings.update({"admin_pin": security.hash_pin("4321")})
        c = self.client()
        r = self.post_form(c, "/unlock", {"pin": "4321", "next": "https://evil.example"})
        self.assertEqual(r.headers["Location"], "/")

    def test_weak_or_mismatched_pins_are_rejected(self):
        c = self.client()
        for pin, confirm in (("12", "12"), ("abcd", "abcd"), ("1234", "9999")):
            self.post_form(c, "/settings/pin", {"pin": pin, "pin_confirm": confirm})
            self.assertEqual(self.s.settings.get("admin_pin"), "")


if __name__ == "__main__":
    unittest.main()
