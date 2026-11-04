"""Event Coordinator journeys: dashboard, review/approve, planning, calendar, venues."""
import re
import unittest

from playwright.sync_api import expect

from _support import E2ETestCase, api


class TestCoordinatorViews(E2ETestCase):
    def test_dashboard_shows_only_assigned_events(self):
        page = self.login("coordinator1")
        expect(page.get_by_role("heading", name="Events Assigned to Me")).to_be_visible()
        table = page.locator("table")
        expect(table).to_contain_text("Industry Panel: Future of AI")   # coordinator1
        expect(table).not_to_contain_text("Leadership Workshop")         # coordinator2
        expect(table).not_to_contain_text("Spring Product Showcase")     # draft, never assigned

    def test_planning_view_tabs_filter_events(self):
        page = self.login("coordinator1")
        page.get_by_role("link", name="Planning View").click()
        expect(page.get_by_role("heading", name="Planning View")).to_be_visible()
        tabs = page.get_by_role("tablist", name="Filter events")
        all_tab = tabs.get_by_role("tab", name=re.compile(r"^All"))
        mine_tab = tabs.get_by_role("tab", name=re.compile(r"^Assigned to me"))
        expect(all_tab).not_to_have_text(re.compile(r"All\s*0$"))
        mine_tab.click()
        expect(mine_tab).to_have_attribute("aria-selected", "true")
        expect(page.locator("main")).to_contain_text("Industry Panel: Future of AI")

    def test_my_calendar_loads(self):
        page = self.login("coordinator1")
        page.get_by_role("link", name="My Calendar").click()
        expect(page).to_have_url(re.compile(r"/calendar$"))
        expect(page.locator("main")).not_to_be_empty()
        self.assertEqual(self.console_errors, [], f"JS errors: {self.console_errors}")

    def test_venue_dropdown_menu_navigation(self):
        page = self.login("coordinator1")
        page.get_by_role("button", name=re.compile(r"^Venue")).click()
        menu = page.locator(".dropdown-menu")
        for link in ["Venue Booking", "Venue Search", "Venue Catalogue", "Venue Availability"]:
            expect(menu.get_by_role("link", name=link)).to_be_visible()
        menu.get_by_role("link", name="Venue Search").click()
        expect(page.get_by_role("heading", name="Venue Search")).to_be_visible()
        expect(menu).to_have_count(0)  # closes after navigation

    def test_venue_search_returns_matching_venues(self):
        page = self.login("coordinator1")
        self.goto("venues/search")
        page.get_by_label("Date").fill("2027-03-10")
        page.get_by_label("Start time").fill("10:00")
        page.get_by_label("End time").fill("12:00")
        page.get_by_label("Expected attendance").fill("100")
        page.get_by_role("button", name="Search venues").click()
        results = page.locator("section.results")
        expect(results).to_be_visible()
        cards = results.locator(".venue-card")
        expect(cards.first).to_be_visible()
        # Every returned venue must actually hold 100 people.
        for text in cards.locator(".badge.cap").all_inner_texts():
            self.assertGreaterEqual(int(re.search(r"\d+", text).group()), 100, text)

    def test_venue_search_validates_attendance(self):
        page = self.login("coordinator1")
        self.goto("venues/search")
        page.get_by_label("Date").fill("2027-03-10")
        page.get_by_label("Start time").fill("10:00")
        page.get_by_label("End time").fill("12:00")
        page.get_by_label("Expected attendance").fill("abc")
        page.get_by_role("button", name="Search venues").click()
        expect(page.locator(".field-error").first).to_be_visible()

    def test_change_requests_page_lists_open_request(self):
        page = self.login("coordinator1")
        page.get_by_role("link", name="Change Requests").click()
        expect(page.locator("main")).to_contain_text("Research Symposium Change Request Demo")

    def test_registrations_manage_lists_registration_events(self):
        page = self.login("coordinator1")
        page.get_by_role("link", name="Registrations").click()
        expect(page.get_by_role("heading", name="Event registrations")).to_be_visible()
        events = page.get_by_role("list", name="Your events")
        expect(events).to_contain_text("Industry Panel: Future of AI")


class TestCoordinatorReview(E2ETestCase):
    """Leadership Workshop is seeded 'under_review' and assigned to coordinator2."""

    def _open(self, who, name):
        event_id = api.organiser_event_id(name)
        page = self.login(who)
        self.goto(f"events/{event_id}")
        expect(page.get_by_role("heading", name=name, exact=True)).to_be_visible()
        return page

    def test_unassigned_coordinator_sees_no_review_actions(self):
        page = self._open("coordinator1", "Leadership Workshop")
        expect(page.get_by_role("button", name="Approve")).to_have_count(0)
        expect(page.get_by_role("button", name="Reject")).to_have_count(0)

    def test_request_clarification_then_approve_then_proceed_to_planning(self):
        page = self._open("coordinator2", "Leadership Workshop")
        expect(page.get_by_role("heading", name="Coordinator Actions")).to_be_visible()

        page.get_by_placeholder("Comments / reason").fill("Please confirm the room layout.")
        page.get_by_role("button", name="Request Clarification").click()
        expect(page.get_by_text("Please confirm the room layout.").first).to_be_visible()

        page.get_by_placeholder("Comments / reason").fill("Looks good.")
        page.get_by_role("button", name="Approve").click()
        # Open clarification -> app warns before approving anyway.
        expect(page.get_by_text("unresolved clarification")).to_be_visible()
        page.get_by_role("button", name="Yes, continue").click()
        expect(page.get_by_role("button", name="Proceed to Planning")).to_be_visible()

        page.get_by_role("button", name="Proceed to Planning").click()
        expect(page.get_by_role("button", name="Send for Safety Check")).to_be_visible()
        # Arrangements are not complete yet, so it must be disabled.
        expect(page.get_by_role("button", name="Send for Safety Check")).to_be_disabled()

    def test_cancel_event_requires_reason(self):
        page = self._open("coordinator1", "Startup Pitch Finals")
        page.get_by_role("button", name="Cancel Event").click()
        page.get_by_role("button", name="Confirm Cancellation").click()
        expect(page.locator("#cancel-form .field-error")).to_be_visible()


if __name__ == "__main__":
    unittest.main()
