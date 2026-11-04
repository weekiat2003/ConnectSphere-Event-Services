"""Shared helpers for the ConnectSphere Playwright end-to-end tests.

- One Chromium browser per test class, a fresh context (fresh localStorage) per test.
- `login(page, email)` drives the real login form.
- `api` lets tests look up seeded data (e.g. an event id by name) without
  hard-coding database ids.
- When a test fails or errors, a full-page screenshot is saved to
  e2e/screenshots/<TestClass>.<test_name>.png so the failure can be inspected.

The tests expect a freshly seeded database (database/schema.sql +
backend/scripts/seed_users.py). Some journeys change data (e.g. approving a
request), so reseed before re-running the suite.
"""
import json
import os
import pathlib
import unittest
import urllib.error
import urllib.request

from playwright.sync_api import expect, sync_playwright

BASE_URL = os.environ.get("BASE_URL", "http://localhost:5173/").rstrip("/") + "/"
API_URL = os.environ.get("API_URL", "http://localhost:5000/api").rstrip("/")
PASSWORD = os.environ.get("E2E_PASSWORD", "Password123!")
SCREENSHOT_DIR = pathlib.Path(
    os.environ.get("E2E_SCREENSHOT_DIR", pathlib.Path(__file__).parent / "screenshots")
)

USERS = {
    "organiser": ("organiser@example.com", "Olivia Organiser"),
    "organiser2": ("organiser2@example.com", "Orlando Organiser"),
    "coordinator1": ("coordinator1@example.com", "Carlos Coordinator"),
    "coordinator2": ("coordinator2@example.com", "Priya Coordinator"),
    "lead": ("lead@example.com", "Lee Coordinator Lead"),
    "venue": ("venue@example.com", "Vince Venue"),
    "tech": ("techsupport@example.com", "Tara TechSupport"),
    "safety": ("safety@example.com", "Sam Safety Officer"),
    "attendee": ("attendee@example.com", "Alex Attendee"),
}

expect.set_options(timeout=8000)


# --------------------------------------------------------------------------
# Tiny API client (used only to look up ids / set up preconditions)
# --------------------------------------------------------------------------
class Api:
    def __init__(self):
        self._tokens = {}

    def _request(self, method, path, token=None, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(API_URL + path, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw = resp.read()
                return resp.status, (json.loads(raw) if raw else None)
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                return e.code, json.loads(raw)
            except Exception:
                return e.code, raw.decode(errors="replace")

    def token(self, who):
        if who not in self._tokens:
            email = USERS[who][0]
            status, data = self._request("POST", "/auth/login", body={"email": email, "password": PASSWORD})
            assert status == 200, f"API login for {email} failed: {status} {data}"
            self._tokens[who] = data["accessToken"]
        return self._tokens[who]

    def get(self, who, path):
        return self._request("GET", path, token=self.token(who))

    def post(self, who, path, body=None):
        return self._request("POST", path, token=self.token(who), body=body or {})

    def organiser_event_id(self, name, who="organiser"):
        status, events = self.get(who, "/events/mine")
        assert status == 200, f"/events/mine failed: {status}"
        for e in events:
            if e.get("name") == name:
                return e["id"]
        raise AssertionError(f"Seeded event {name!r} not found for {who}")


api = Api()


# --------------------------------------------------------------------------
# Base test case
# --------------------------------------------------------------------------
class E2ETestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch()

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()

    def setUp(self):
        self.context = self.browser.new_context(viewport={"width": 1280, "height": 900})
        self.page = self.context.new_page()
        self.console_errors = []
        self.page.on("pageerror", lambda exc: self.console_errors.append(str(exc)))

    def tearDown(self):
        if self._has_failed():
            SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
            name = f"{type(self).__name__}.{self._testMethodName}.png"
            try:
                self.page.screenshot(path=str(SCREENSHOT_DIR / name), full_page=True)
            except Exception:
                pass
        self.context.close()

    def _has_failed(self):
        """True if this test has already failed, under unittest or pytest."""
        result = getattr(getattr(self, "_outcome", None), "result", None)
        if result is None:
            return False
        failures = getattr(result, "failures", None)
        errors = getattr(result, "errors", None)
        if failures is not None and errors is not None:
            # unittest: failures are recorded as soon as they happen, so they
            # are visible here in tearDown (including failures inside subTests).
            for test, _ in list(failures) + list(errors):
                if test is self or getattr(test, "test_case", None) is self:
                    return True
            return False
        # pytest: its unittest adapter keeps the captured exceptions instead.
        return bool(getattr(result, "_excinfo", None))

    # -- helpers ----------------------------------------------------------
    def goto(self, path=""):
        self.page.goto(BASE_URL + path.lstrip("/"))

    def login(self, who):
        email, name = USERS[who]
        page = self.page
        self.goto("login")
        page.get_by_label("Email").fill(email)
        page.get_by_label("Password").fill(PASSWORD)
        page.get_by_role("button", name="Log in").click()
        expect(page.locator("nav .user-name")).to_have_text(name)
        return page

    def confirm_dialog(self, required=True):
        """Click Confirm on the app's shared ConfirmDialog."""
        dialog = self.page.locator(".confirm-overlay")
        if required:
            expect(dialog).to_be_visible()
        else:
            try:
                dialog.wait_for(state="visible", timeout=1500)
            except Exception:
                return
        dialog.get_by_role("button", name="Confirm").click()
        expect(dialog).to_have_count(0)

    def nav(self):
        return self.page.locator("nav")
