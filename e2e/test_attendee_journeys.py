"""Attendee journeys (browse, register, withdraw) and the organiser side of registration.

Note on cancelled events: the product owner has confirmed that for a
cancelled event the registration button may still be shown as long as it
cannot be clicked. The cancelled-event test accepts either "no button" or
"button visible but disabled" and only fails if registration is actually
possible.
"""
import re
import unittest

from playwright.sync_api import expect

from _support import E2ETestCase, api

PANEL = "Industry Panel: Future of AI"   # confirmed, registration required, closed at seed time
GALA = "Charity Gala Evening"             # cancelled, registration required


class TestAttendeeBrowsing(E2ETestCase):
    def test_events_list_shows_confirmed_event_with_status(self):
        page = self.login("attendee")
        card = page.locator("article", has_text=PANEL)
        expect(card).to_be_visible()
        expect(card).to_contain_text("Main Auditorium")
        expect(card.get_by_role("link", name="View details")).to_be_visible()

    def test_unconfirmed_events_are_not_listed(self):
        page = self.login("attendee")
        main = page.locator("main")
        expect(main.locator("article").first).to_be_visible()
        for name in ["Spring Product Showcase", "Leadership Workshop", "Open Air Music Night"]:
            expect(main).not_to_contain_text(name)

    def test_event_detail_back_link(self):
        page = self.login("attendee")
        page.locator("article", has_text=PANEL).get_by_role("link", name="View details").click()
        expect(page.get_by_role("heading", name=PANEL)).to_be_visible()
        page.get_by_role("link", name="Back to events").click()
        expect(page).to_have_url(re.compile(r"/attendee/events$"))

    def test_unknown_event_shows_not_found(self):
        page = self.login("attendee")
        self.goto("attendee/events/999999")
        expect(page.get_by_role("heading", name="Event not found")).to_be_visible()

    def test_cancelled_event_cannot_be_registered_for(self):
        gala_id = api.organiser_event_id(GALA)
        page = self.login("attendee")
        self.goto(f"attendee/events/{gala_id}")
        expect(page.get_by_role("heading", name=GALA)).to_be_visible()
        expect(page.get_by_text("Cancelled", exact=True)).to_be_visible()

        register = page.get_by_role("button", name="Register")
        if register.count():
            # Allowed by design: visible but must not be clickable.
            expect(register).to_be_disabled()
        else:
            expect(page.get_by_text("This event is cancelled. Registration is no longer possible.")).to_be_visible()
        expect(page.get_by_role("button", name="Join the waiting list")).to_have_count(0)
        # No "notify me" opt-in for a cancelled event.
        expect(page.get_by_label("Notify me when registration opens or closes")).to_have_count(0)

    def test_closed_registration_shows_reason_and_no_register_button(self):
        panel_id = api.organiser_event_id(PANEL)
        page = self.login("attendee")
        self.goto(f"attendee/events/{panel_id}")
        expect(page.get_by_text("Registration not open", exact=True)).to_be_visible()
        expect(page.get_by_text("Registration is not open for this event.")).to_be_visible()
        expect(page.get_by_role("button", name="Register")).to_have_count(0)

    def test_follow_and_unfollow_registration_updates(self):
        panel_id = api.organiser_event_id(PANEL)
        page = self.login("attendee")
        self.goto(f"attendee/events/{panel_id}")
        box = page.get_by_label("Notify me when registration opens or closes")
        expect(box).not_to_be_checked()
        box.check()
        expect(page.get_by_role("status")).to_contain_text("We'll notify you")
        expect(box).to_be_checked()
        box.uncheck()
        expect(page.get_by_role("status")).to_contain_text("You won't get updates")
        expect(box).not_to_be_checked()

    def test_my_registrations_empty_state(self):
        page = self.login("attendee")
        page.get_by_role("link", name="My Registrations").click()
        expect(page.get_by_role("heading", name="My registrations")).to_be_visible()
        expect(page.get_by_text("You have not registered for any events yet.")).to_be_visible()


class TestRegistrationLifecycle(E2ETestCase):
    """Organiser opens registration -> attendee registers -> organiser sees it ->
    attendee withdraws -> organiser closes registration."""

    def test_full_registration_lifecycle(self):
        # 1. Organiser opens registration.
        page = self.login("organiser")
        page.get_by_role("link", name="Registrations").click()
        expect(page.get_by_role("heading", name="Event registrations")).to_be_visible()
        page.get_by_role("list", name="Your events").get_by_role("button", name=re.compile(re.escape(PANEL))).click()
        expect(page.get_by_role("heading", name=PANEL, level=3)).to_be_visible()
        page.get_by_role("button", name="Open registration").click()
        self.confirm_dialog(required=False)
        expect(page.get_by_role("button", name="Close registration")).to_be_visible()
        page.get_by_role("button", name="Logout").click()

        # 2. Attendee registers.
        page = self.login("attendee")
        card = page.locator("article", has_text=PANEL)
        expect(card).to_contain_text("200 places left")
        card.get_by_role("link", name="View details").click()
        page.get_by_role("button", name="Register").click()
        expect(page.get_by_role("status")).to_contain_text("You are registered.")
        expect(page.get_by_text("You are registered.", exact=False).first).to_be_visible()
        expect(page.get_by_text("199 of 200 places left")).to_be_visible()

        # 3. My Registrations shows it.
        page.get_by_role("link", name="My Registrations").click()
        item = page.locator("li", has_text=PANEL)
        expect(item).to_contain_text("Registered")
        page.get_by_role("button", name="Logout").click()

        # 4. Organiser sees the attendee.
        page = self.login("organiser")
        self.goto("registrations/manage")
        page.get_by_role("list", name="Your events").get_by_role("button", name=re.compile(re.escape(PANEL))).click()
        expect(page.locator("table")).to_contain_text("Alex Attendee")
        page.get_by_role("button", name="Logout").click()

        # 5. Attendee withdraws (with confirmation).
        page = self.login("attendee")
        self.goto("my-registrations")
        page.locator("li", has_text=PANEL).get_by_role("button", name="Withdraw").click()
        self.confirm_dialog()
        expect(page.get_by_role("status")).to_contain_text("withdrawn")
        expect(page.locator("li", has_text=PANEL)).to_contain_text("Withdrawn")
        expect(page.locator("li", has_text=PANEL).get_by_role("button", name="Withdraw")).to_have_count(0)
        page.get_by_role("button", name="Logout").click()

        # 6. Organiser closes registration again (leave data as seeded).
        page = self.login("organiser")
        self.goto("registrations/manage")
        page.get_by_role("list", name="Your events").get_by_role("button", name=re.compile(re.escape(PANEL))).click()
        page.get_by_role("button", name="Close registration").click()
        self.confirm_dialog(required=False)
        expect(page.get_by_role("button", name="Open registration")).to_be_visible()


class TestNotifications(E2ETestCase):
    def test_bell_badge_and_mark_all_read(self):
        page = self.login("safety")  # seeded with 2 unread safety-check notifications
        bell = page.locator("nav").get_by_role("link", name=re.compile("Notifications"))
        expect(bell).to_contain_text(re.compile(r"\d"))
        bell.click()
        expect(page.get_by_role("heading", name="Notifications")).to_be_visible()
        expect(page.locator("li.item.unread").first).to_be_visible()
        page.get_by_role("button", name="Mark all as read").click()
        expect(page.locator("li.item.unread")).to_have_count(0)
        expect(page.get_by_role("button", name="Mark all as read")).to_be_disabled()
        page.get_by_label("Unread only").check()
        expect(page.get_by_text("No unread notifications.")).to_be_visible()

    def test_notification_view_link_opens_target(self):
        page = self.login("safety")
        self.goto("notifications")
        page.locator("li.item").first.get_by_role("button", name="View").click()
        expect(page).not_to_have_url(re.compile(r"/notifications$"))


if __name__ == "__main__":
    unittest.main()
