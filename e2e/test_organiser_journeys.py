"""Event Organiser journeys: dashboard, new requests, drafts, event detail."""
import re
import time
import unittest
from datetime import date, timedelta

from playwright.sync_api import expect

from _support import E2ETestCase, api


def unique(prefix):
    return f"{prefix} {int(time.time() * 1000) % 10_000_000}"


class TestOrganiserDashboard(E2ETestCase):
    def test_dashboard_lists_seeded_events_with_statuses(self):
        page = self.login("organiser")
        expect(page.get_by_role("heading", name="My Events")).to_be_visible()
        table = page.locator("table")
        for name, status in [
            ("Spring Product Showcase", "Draft"),
            ("Quarterly All-Hands Meeting", "Under Review"),
            ("Industry Panel: Future of AI", "Confirmed"),
            ("Charity Gala Evening", "Cancelled"),
            ("Open Air Music Night", "Rejected"),
        ]:
            row = table.locator("tr", has=page.get_by_text(name, exact=True))
            expect(row).to_contain_text(status, ignore_case=True)

    def test_view_opens_event_detail(self):
        page = self.login("organiser")
        row = page.locator("tr", has=page.get_by_text("Industry Panel: Future of AI", exact=True))
        row.get_by_role("link", name="View").or_(row.get_by_role("button", name="View")).first.click()
        expect(page).to_have_url(re.compile(r"/events/\d+$"))
        expect(page.get_by_role("heading", name="Industry Panel: Future of AI")).to_be_visible()


class TestNewEventRequest(E2ETestCase):
    def _fill_basic(self, name, days_ahead=60):
        page = self.page
        d = (date.today() + timedelta(days=days_ahead)).isoformat()
        page.get_by_label("Name").fill(name)
        page.get_by_label("Purpose").fill("E2E test purpose")
        page.get_by_label("Event Type").select_option("Workshop")
        page.get_by_label("Description").fill("Created by the Playwright end-to-end suite.")
        page.get_by_label("Start Date").fill(d)
        page.get_by_label("Start Time").fill("10:00")
        page.get_by_label("End Date").fill(d)
        page.get_by_label("End Time").fill("12:00")
        page.get_by_label("Expected Attendance").fill("30")
        page.get_by_label("Capacity Needed").fill("40")
        layout = page.get_by_label("Required Layout")
        options = layout.locator("option:not([value=''])")
        expect(options.first).to_be_attached()
        layout.select_option(index=1)
        page.get_by_label("Accessibility Needs").fill("Step-free access")

    def test_save_as_draft_then_edit_and_delete(self):
        page = self.login("organiser")
        name = unique("E2E Draft")
        page.get_by_role("link", name="New Request").click()
        expect(page.get_by_role("heading", name="New Event Request")).to_be_visible()
        self._fill_basic(name)
        page.get_by_role("button", name="Save as Draft").click()

        expect(page).to_have_url(re.compile(r"/drafts$"))
        item = page.locator("li", has_text=name)
        expect(item).to_be_visible()

        # Edit the draft: name change persists.
        item.get_by_role("button", name="Edit").click()
        expect(page.get_by_role("heading", name="Edit Draft Event Request")).to_be_visible()
        expect(page.get_by_label("Name")).to_have_value(name)
        page.get_by_label("Name").fill(name + " (edited)")
        page.get_by_role("button", name="Save Changes").click()
        expect(page).to_have_url(re.compile(r"/drafts$"))
        edited = page.locator("li", has_text=name + " (edited)")
        expect(edited).to_be_visible()

        # Delete it (confirm dialog).
        edited.get_by_role("button", name="Delete").click()
        self.confirm_dialog(required=False)
        expect(page.locator("li", has_text=name)).to_have_count(0)

    def test_submit_new_request_appears_on_dashboard_as_submitted(self):
        page = self.login("organiser")
        name = unique("E2E Submitted")
        self.goto("events/new")
        self._fill_basic(name)
        page.get_by_role("button", name="Submit Now").click()
        self.confirm_dialog()
        expect(page).to_have_url(re.compile(r"/$"))
        row = page.locator("tr", has=page.get_by_text(name, exact=True))
        expect(row).to_be_visible()
        expect(row).to_contain_text(re.compile(r"Submitted|Under Review", re.I))

    def test_submit_with_equipment_requirement(self):
        page = self.login("organiser")
        name = unique("E2E With Equipment")
        self.goto("events/new")
        self._fill_basic(name)
        page.get_by_role("button", name="+ Add Equipment").click()
        page.get_by_label("Equipment Type *").select_option(index=1)
        page.get_by_label("Quantity *").fill("2")
        page.get_by_role("button", name="Submit Now").click()
        self.confirm_dialog()
        expect(page).to_have_url(re.compile(r"/$"))
        expect(page.locator("tr", has=page.get_by_text(name, exact=True))).to_be_visible()

    def test_required_fields_block_submission(self):
        page = self.login("organiser")
        self.goto("events/new")
        page.get_by_role("button", name="Submit Now").click()
        expect(page).to_have_url(re.compile(r"/events/new$"))
        # Browser validation flags the empty required Name field.
        invalid = page.get_by_label("Name").evaluate("el => !el.checkValidity()")
        self.assertTrue(invalid)

    def test_end_before_start_is_rejected(self):
        page = self.login("organiser")
        self.goto("events/new")
        self._fill_basic(unique("E2E Bad Times"))
        page.get_by_label("End Time").fill("08:00")  # same day, before 10:00 start
        page.get_by_role("button", name="Submit Now").click()
        self.confirm_dialog(required=False)
        expect(page.locator("p.error")).to_be_visible()
        expect(page).to_have_url(re.compile(r"/events/new$"))

    def test_missing_accessibility_needs_shows_clear_error(self):
        # The API requires accessibility needs on submission; the form should say so.
        page = self.login("organiser")
        self.goto("events/new")
        self._fill_basic(unique("E2E No Access Needs"))
        page.get_by_label("Accessibility Needs").fill("")
        page.get_by_role("button", name="Submit Now").click()
        self.confirm_dialog(required=False)
        expect(page.locator("p.error")).to_contain_text("Accessibility Needs")
        expect(page).to_have_url(re.compile(r"/events/new$"))

    @unittest.skip("Known issue, not fixed yet: a failed 'Submit Now' leaves a stray draft "
                   "(create_event in backend/app/events/routes.py saves the draft before validating).")
    def test_fixing_a_failed_submission_does_not_create_duplicates(self):
        """Submit with a missing field, fix it, submit again: the organiser
        should end up with exactly ONE event of that name, not a stray draft."""
        page = self.login("organiser")
        name = unique("E2E Retry")
        self.goto("events/new")
        self._fill_basic(name)
        page.get_by_label("Accessibility Needs").fill("")
        page.get_by_role("button", name="Submit Now").click()
        self.confirm_dialog(required=False)
        expect(page.locator("p.error")).to_be_visible()

        page.get_by_label("Accessibility Needs").fill("Step-free access")
        page.get_by_role("button", name="Submit Now").click()
        self.confirm_dialog(required=False)
        expect(page).to_have_url(re.compile(r"/$"))

        rows = page.locator("tbody tr", has=page.get_by_text(name, exact=True))
        expect(rows).to_have_count(1)

    def test_intended_capacity_label_matches_validation(self):
        """The Intended Capacity field must behave the way its label says.

        Passes with either fix: keep it '(optional)' and let a blank value
        submit, or make it required (label without 'optional') and show an
        error when it is left blank.
        """
        page = self.login("organiser")
        name = unique("E2E Reg No Cap")
        self.goto("events/new")
        self._fill_basic(name)
        page.get_by_label("Registration required").check()
        label = page.locator("label", has_text="Intended Capacity")
        field = label.locator("input")
        expect(field).to_be_visible()
        expect(field).to_have_value("")
        label_text = label.inner_text()
        says_optional = "optional" in label_text.lower()

        page.get_by_role("button", name="Submit Now").click()
        self.confirm_dialog(required=False)

        if says_optional:
            # Labelled optional -> a blank value must be accepted.
            expect(page).to_have_url(re.compile(r"/$"))
            expect(page.locator("tr", has=page.get_by_text(name, exact=True))).to_be_visible()
        else:
            # Labelled required -> blank value is refused, with a message, before anything is submitted.
            browser_blocked = field.evaluate("el => !el.checkValidity()")
            if not browser_blocked:
                expect(page.locator("p.error")).to_contain_text(re.compile("capacity", re.I))
            expect(page).to_have_url(re.compile(r"/events/new$"))

    def test_registration_required_reveals_intended_capacity(self):
        page = self.login("organiser")
        self.goto("events/new")
        capacity = page.locator("label", has_text="Intended Capacity").locator("input")
        expect(capacity).to_have_count(0)
        page.get_by_label("Registration required").check()
        expect(capacity).to_be_visible()


class TestOrganiserEventDetail(E2ETestCase):
    def test_rejected_event_shows_reason(self):
        event_id = api.organiser_event_id("Open Air Music Night")
        page = self.login("organiser")
        self.goto(f"events/{event_id}")
        expect(page.get_by_role("heading", name="Open Air Music Night", exact=True)).to_be_visible()
        expect(page.get_by_text("Expected attendance exceeds the capacity").first).to_be_visible()

    def test_other_organisers_event_is_not_visible(self):
        # Python Fundamentals Workshop belongs to organiser2.
        other_id = api.organiser_event_id("Python Fundamentals Workshop", who="organiser2")
        page = self.login("organiser")
        self.goto(f"events/{other_id}")
        expect(page.get_by_role("heading", name="Python Fundamentals Workshop")).to_have_count(0, timeout=4000)


if __name__ == "__main__":
    unittest.main()
