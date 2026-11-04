"""Venue Staff, Technical Support and Safety Officer journeys."""
import re
import time
import unittest

from playwright.sync_api import expect

from _support import E2ETestCase


class TestVenueStaff(E2ETestCase):
    def test_pending_requests_listed_with_actions(self):
        page = self.login("venue")
        expect(page.get_by_role("heading", name="Venue Booking Approval")).to_be_visible()
        card = page.locator("article", has_text="Hackathon Kickoff")
        expect(card).to_be_visible()
        for label in ["Place hold", "Approve booking", "Reject booking"]:
            expect(card.get_by_role("button", name=label)).to_be_visible()

    def test_tabs_switch_between_pending_and_approved(self):
        page = self.login("venue")
        approved_tab = page.get_by_role("tab", name=re.compile("Approved"))
        approved_tab.click()
        expect(approved_tab).to_have_attribute("aria-selected", "true")
        expect(page.get_by_role("button", name="Approve booking")).to_have_count(0)

    def test_approve_booking_with_confirmation(self):
        page = self.login("venue")
        card = page.locator("article", has_text="Campus Innovation Expo")
        card.get_by_role("button", name="Approve booking").click()
        dialog = page.get_by_role("alertdialog")
        expect(dialog).to_contain_text("Approve booking request?")
        expect(dialog).to_contain_text("Banquet Hall")
        dialog.locator(".approve-confirm-btn").click()
        expect(page.get_by_role("alertdialog")).to_have_count(0)
        expect(page.locator("article", has_text="Campus Innovation Expo").get_by_role(
            "button", name="Approve booking")).to_have_count(0)

    def test_cancel_reject_dialog_keeps_request(self):
        page = self.login("venue")
        card = page.locator("article", has_text="Hackathon Kickoff")
        card.get_by_role("button", name="Reject booking").click()
        dialog = page.get_by_role("dialog", name="Reject booking request?")
        expect(dialog).to_contain_text("Reject booking request?")
        dialog.get_by_role("button", name="Cancel").click()
        expect(card.get_by_role("button", name="Reject booking")).to_be_visible()

    def test_venue_catalogue_loads(self):
        page = self.login("venue")
        page.get_by_role("link", name="Venue Catalogue").click()
        expect(page.locator("main")).to_contain_text("Main Auditorium")


class TestTechnicalSupport(E2ETestCase):
    def test_equipment_overview_calendar(self):
        page = self.login("tech")
        expect(page.get_by_role("heading", name="Equipment Overview")).to_be_visible()
        expect(page.locator("main")).to_contain_text("Equipment reservation calendar")

    def test_add_new_equipment_item_and_search(self):
        page = self.login("tech")
        page.get_by_role("link", name="Equipment", exact=True).click()
        expect(page.get_by_role("heading", name="Equipment Catalogue")).to_be_visible()
        name = f"E2E Lighting Rig {int(time.time()) % 100000}"
        page.get_by_label("Equipment name").fill(name)
        page.get_by_label("Total quantity").fill("4")
        page.get_by_role("button", name="Add item").click()
        expect(page.locator("table.items")).to_contain_text(name)

        page.get_by_label("Search equipment").fill(name)
        expect(page.locator("table.items tbody tr")).to_have_count(1)

    def test_adding_duplicate_equipment_is_rejected(self):
        page = self.login("tech")
        self.goto("equipment")
        page.get_by_label("Equipment name").fill("Projector")
        page.get_by_label("Total quantity").fill("1")
        page.get_by_role("button", name="Add item").click()
        expect(page.locator(".error, .warning").first).to_be_visible()

    def test_technical_review_page_loads(self):
        page = self.login("tech")
        page.get_by_role("link", name="Technical Review").click()
        expect(page.get_by_role("heading", name=re.compile("Technical Review"))).to_be_visible()


class TestSafetyOfficer(E2ETestCase):
    def test_safety_review_list(self):
        page = self.login("safety")
        expect(page.locator("main")).to_contain_text("Hackathon Safety Check Demo")
        expect(page.locator("main")).to_contain_text("Community Fair Safety Check Demo")

    def test_reject_requires_reason_and_affected_arrangement(self):
        page = self.login("safety")
        page.locator("tr", has_text="Community Fair Safety Check Demo").get_by_role(
            "link", name="Review").or_(page.locator("tr", has_text="Community Fair Safety Check Demo")
                                       .get_by_role("button", name="Review")).first.click()
        expect(page.get_by_role("heading", name="Community Fair Safety Check Demo")).to_be_visible()
        page.get_by_role("button", name="Reject arrangement").click()
        expect(page.locator("ul.errors")).to_be_visible()

    def test_z_assess_all_factors_and_approve(self):
        # 'z_' so it runs last in this class: approving removes the event from the list.
        page = self.login("safety")
        page.locator("tr", has_text="Hackathon Safety Check Demo").get_by_role(
            "link", name="Review").or_(page.locator("tr", has_text="Hackathon Safety Check Demo")
                                       .get_by_role("button", name="Review")).first.click()
        expect(page.get_by_role("heading", name="Hackathon Safety Check Demo")).to_be_visible()

        approve = page.get_by_role("button", name="Approve safety")
        expect(approve).to_be_disabled()  # nothing assessed yet

        groups = page.get_by_role("radiogroup")
        for i in range(groups.count()):
            groups.nth(i).get_by_text("Satisfactory").click()
        page.get_by_role("button", name="Save assessment").click()
        expect(page.get_by_text(re.compile("Saved by Sam Safety Officer"))).to_be_visible()

        expect(approve).to_be_enabled()
        approve.click()
        self.confirm_dialog(required=False)
        expect(page.get_by_role("button", name="Approve safety")).to_have_count(0)


if __name__ == "__main__":
    unittest.main()
