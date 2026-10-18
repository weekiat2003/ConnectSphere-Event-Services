"""End-to-end browser tests for ConnectSphere's most important journey: logging in.

Written with unittest and Playwright's sync API, as in the Week 9 lab. They drive
the built Vue frontend in a real (headless) Chromium browser, talking to a running
backend whose database holds the seeded test users.

BASE_URL defaults to the locally served frontend; set it to test another copy.

This folder has no __init__.py on purpose, so the backend `test` job never picks
these up: that job has no browser and no running app.
"""
import os
import unittest

from playwright.sync_api import expect, sync_playwright

BASE_URL = os.environ.get("BASE_URL", "http://localhost:5173/")
EMAIL = os.environ.get("E2E_EMAIL", "organiser@example.com")
PASSWORD = os.environ.get("E2E_PASSWORD", "Password123!")
USER_NAME = os.environ.get("E2E_USER_NAME", "Olivia Organiser")


class TestLoginJourney(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch()

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()

    def setUp(self):
        # A fresh context per test = fresh localStorage, so no one is logged in.
        self.context = self.browser.new_context()
        self.page = self.context.new_page()

    def tearDown(self):
        self.context.close()

    def test_organiser_logs_in_and_sees_their_events(self):
        page = self.page
        page.goto(BASE_URL)

        # Not logged in yet, so the router sends us to the login page.
        expect(page.get_by_role("button", name="Log in")).to_be_visible()

        page.get_by_label("Email").fill(EMAIL)
        page.get_by_label("Password").fill(PASSWORD)
        page.get_by_role("button", name="Log in").click()

        # Landed on the organiser's dashboard, with their name in the nav bar
        # and their seeded events loaded from the API.
        expect(page.get_by_role("heading", name="My Events")).to_be_visible()
        expect(page.get_by_text(USER_NAME)).to_be_visible()
        expect(page.get_by_text("All events")).to_be_visible()

    def test_wrong_password_shows_an_error_and_stays_on_login(self):
        page = self.page
        page.goto(BASE_URL)

        page.get_by_label("Email").fill(EMAIL)
        page.get_by_label("Password").fill("definitely-wrong")
        page.get_by_role("button", name="Log in").click()

        expect(page.get_by_text("Invalid credentials")).to_be_visible()
        expect(page.get_by_role("button", name="Log in")).to_be_visible()


if __name__ == "__main__":
    unittest.main()
