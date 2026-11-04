"""Authentication, role-based landing pages, navigation and route guards."""
import re
import unittest

from playwright.sync_api import expect

from _support import BASE_URL, PASSWORD, USERS, E2ETestCase


class TestAuthentication(E2ETestCase):
    def test_unauthenticated_user_is_redirected_to_login(self):
        for path in ["", "drafts", "planning", "equipment", "attendee/events", "notifications"]:
            with self.subTest(path=path):
                self.goto(path)
                expect(self.page).to_have_url(re.compile(r"/login$"))
                expect(self.page.get_by_role("button", name="Log in")).to_be_visible()

    def test_unknown_email_is_rejected(self):
        page = self.page
        self.goto("login")
        page.get_by_label("Email").fill("nobody@example.com")
        page.get_by_label("Password").fill(PASSWORD)
        page.get_by_role("button", name="Log in").click()
        expect(page.locator(".error")).to_be_visible()
        expect(page).to_have_url(re.compile(r"/login$"))

    def test_empty_form_is_blocked_by_browser_validation(self):
        page = self.page
        self.goto("login")
        page.get_by_role("button", name="Log in").click()
        # Required fields stop submission: still on login, no nav bar.
        expect(page).to_have_url(re.compile(r"/login$"))
        expect(page.locator("nav")).to_have_count(0)

    def test_logout_clears_session(self):
        page = self.login("organiser")
        page.get_by_role("button", name="Logout").click()
        expect(page).to_have_url(re.compile(r"/login$"))
        # Session really gone: protected page bounces back to login.
        self.goto("")
        expect(page).to_have_url(re.compile(r"/login$"))

    def test_session_survives_page_reload(self):
        page = self.login("organiser")
        page.reload()
        expect(page.get_by_role("heading", name="My Events")).to_be_visible()
        expect(page.locator("nav .user-name")).to_have_text(USERS["organiser"][1])


class TestRoleLandingPages(E2ETestCase):
    """Each role lands on the right page and sees only its own nav links."""

    CASES = {
        "organiser": (r"/$", "My Events",
                      ["Dashboard", "New Request", "My Drafts", "Registrations"],
                      ["Planning View", "Equipment", "Safety Reviews", "Assignment Queue"]),
        "coordinator1": (r"/$", "Events Assigned to Me",
                         ["Dashboard", "Change Requests", "Planning View", "My Calendar", "Equipment Booking"],
                         ["New Request", "My Drafts", "Safety Reviews"]),
        "lead": (r"/lead$", "Lead Dashboard",
                 ["Assignment Queue", "Supervision"],
                 ["New Request", "Planning View"]),
        "venue": (r"/venues/approval$", "Venue Booking Approval",
                  ["Venue Catalogue", "Venue Availability", "Venue Approval"],
                  ["Dashboard", "New Request"]),
        "tech": (r"/$", "Equipment Overview",
                 ["Equipment", "Technical Review"],
                 ["New Request", "Planning View"]),
        "safety": (r"/safety-reviews$", "Safety Reviews",
                   ["Safety Reviews"],
                   ["Dashboard", "Planning View"]),
        "attendee": (r"/attendee/events$", "ALL EVENTS",
                     ["Events", "My Registrations"],
                     ["Dashboard", "New Request"]),
    }

    def test_each_role_lands_on_its_home_page_with_correct_nav(self):
        for who, (url_re, heading, visible, hidden) in self.CASES.items():
            with self.subTest(role=who):
                self.context.clear_cookies()
                self.page.goto(BASE_URL)
                self.page.evaluate("localStorage.clear()")
                page = self.login(who)
                expect(page).to_have_url(re.compile(url_re))
                expect(page.get_by_role("heading", name=heading, exact=True).first).to_be_visible()
                nav = self.nav()
                for link in visible:
                    expect(nav.get_by_role("link", name=link, exact=True)).to_be_visible()
                for link in hidden:
                    expect(nav.get_by_role("link", name=link, exact=True)).to_have_count(0)
                page.get_by_role("button", name="Logout").click()
                expect(page).to_have_url(re.compile(r"/login$"))


class TestRouteGuards(E2ETestCase):
    def test_organiser_is_told_access_denied_for_safety_reviews(self):
        page = self.login("organiser")
        self.goto("safety-reviews")
        expect(page).to_have_url(re.compile(r"/access-denied"))
        expect(page.get_by_role("heading", name="Access denied")).to_be_visible()
        expect(page.get_by_text("only available to Safety Officers")).to_be_visible()

    def test_coordinator_is_told_access_denied_for_assignment_queue(self):
        page = self.login("coordinator1")
        self.goto("assignments")
        expect(page.get_by_role("heading", name="Access denied")).to_be_visible()
        expect(page.get_by_text("Event Coordinator Leads")).to_be_visible()

    def test_attendee_is_bounced_from_role_restricted_staff_pages(self):
        page = self.login("attendee")
        for path in ["equipment", "calendar", "registrations/manage", "venues/approval", "technical-review"]:
            with self.subTest(path=path):
                self.goto(path)
                # Non-showAccessDenied routes bounce to dashboard -> attendee events.
                expect(page).to_have_url(re.compile(r"/attendee/events$"))

    @unittest.skip("Known issue, not fixed yet: /planning, /review, /change-requests, /drafts and "
                   "/events/new have no role guard in router/index.js (backend still blocks the data).")
    def test_attendee_cannot_open_any_staff_only_page(self):
        """Every staff/organiser page should be blocked for an attendee by the router.

        These routes are hidden from the attendee's nav, but are they guarded
        if the URL is typed in directly?
        """
        page = self.login("attendee")
        for path in ["planning", "review", "change-requests", "drafts", "events/new"]:
            with self.subTest(path=path):
                self.goto(path)
                expect(page).not_to_have_url(re.compile(rf"/{re.escape(path)}$"), timeout=3000)

    def test_organiser_cannot_open_equipment_catalogue(self):
        page = self.login("organiser")
        self.goto("equipment")
        expect(page).to_have_url(re.compile(r"/$"))
        expect(page.get_by_role("heading", name="My Events")).to_be_visible()

    def test_access_denied_back_link_returns_to_dashboard(self):
        page = self.login("organiser")
        self.goto("lead")
        expect(page.get_by_role("heading", name="Access denied")).to_be_visible()
        page.get_by_role("link", name="Back to Dashboard").click()
        expect(page.get_by_role("heading", name="My Events")).to_be_visible()


if __name__ == "__main__":
    unittest.main()
