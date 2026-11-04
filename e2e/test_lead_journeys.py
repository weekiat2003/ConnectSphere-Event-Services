"""Event Coordinator Lead journeys: dashboard, assignment queue, supervision."""
import re
import unittest

from playwright.sync_api import expect

from _support import E2ETestCase


class TestLead(E2ETestCase):
    def test_lead_dashboard_shows_unassigned_request_and_workload(self):
        page = self.login("lead")
        expect(page.get_by_role("heading", name="Lead Dashboard")).to_be_visible()
        expect(page.locator("main")).to_contain_text("Python Fundamentals Workshop")
        expect(page.locator("main")).to_contain_text("Carlos Coordinator")
        expect(page.locator("main")).to_contain_text("Priya Coordinator")

    def test_supervision_lists_each_coordinator(self):
        page = self.login("lead")
        page.get_by_role("link", name="Supervision").click()
        expect(page.get_by_role("heading", name="Coordinator Supervision")).to_be_visible()
        expect(page.get_by_role("heading", name="Carlos Coordinator")).to_be_visible()
        expect(page.get_by_role("heading", name="Priya Coordinator")).to_be_visible()

    def test_z_assign_unassigned_request_to_coordinator(self):
        # 'z_' so it runs last in this class: assigning empties the dashboard's queue.
        page = self.login("lead")
        page.get_by_role("link", name="Assignment Queue").click()
        expect(page.get_by_role("heading", name="Assignment Queue")).to_be_visible()

        card = page.locator("li.request", has_text="Python Fundamentals Workshop")
        expect(card).to_be_visible()
        select = card.get_by_label("Coordinator")
        priya = select.locator("option", has_text="Priya Coordinator").get_attribute("value")
        select.select_option(priya)
        card.get_by_role("button", name="Assign").click()
        expect(page.locator(".confirm-overlay")).to_contain_text("Priya Coordinator")
        self.confirm_dialog()

        expect(page.locator("li.request", has_text="Python Fundamentals Workshop")).to_have_count(0)

        # Priya now sees it on her dashboard, under review.
        page.get_by_role("button", name="Logout").click()
        page = self.login("coordinator2")
        row = page.locator("tr", has=page.get_by_text("Python Fundamentals Workshop", exact=True))
        expect(row).to_be_visible()
        expect(row).to_contain_text(re.compile("under review", re.I))


if __name__ == "__main__":
    unittest.main()
