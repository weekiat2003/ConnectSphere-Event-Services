"""Regression tests for the Coordinator items on the Notification System bug
list (team test sheet).

Each test performs the real service action and checks the Coordinator's inbox.
"""
from datetime import timedelta

import pytest

from app.change_requests import services as cr
from app.common.time import utcnow
from app.events.services import review, safety
from app.events.services.safety import SAFETY_FACTOR_ORDER
from app.extensions import db
from app.models.event import Event
from app.models.notification import (
    TYPE_CHANGE_REQUEST,
    TYPE_CLARIFICATION,
    TYPE_ORGANISER_UPDATE,
    TYPE_SAFETY_CHECK,
    TYPE_VENUE_BOOKING_UPDATE,
)
from app.models.venue import BOOKING_APPROVED, Venue, VenueBooking
from app.venues.services import availability, catalogue
from tests.unit.test_notification_stories import inbox, new_event, submitted_and_assigned


@pytest.fixture()
def staff(make_user):
    return {
        "venue1": make_user("venue1@test.com", ["venue_staff"], name="Vic Venue"),
        "lead1": make_user("lead1@test.com", ["event_coordinator_lead"], name="Lena Lead"),
        "safety1": make_user("safety1@test.com", ["safety_officer"], name="Sid Safety"),
    }


def _planning_event_with_booking(organiser, coordinator, venue_manager, days=20):
    event = new_event(organiser, "planning", coordinator)
    venue = Venue(name="Grand Hall", capacity=300, created_by=venue_manager)
    db.session.add(venue)
    db.session.flush()
    start = (utcnow() + timedelta(days=days)).replace(hour=19, minute=0, second=0, microsecond=0)
    booking = VenueBooking(event_id=event.id, venue_id=venue.id, requested_by=coordinator,
                           status=BOOKING_APPROVED, start_datetime=start,
                           end_datetime=start + timedelta(hours=3))
    db.session.add(booking)
    db.session.commit()
    return event, venue, booking


# --- Change / withdrawal requests ------------------------------------------

class TestCoordinatorToldOfChangeRequest:
    def test_change_request(self, app, organiser, coordinator, staff):
        event = submitted_and_assigned(organiser, coordinator)
        request = cr.submit_change_request(event, organiser, {"name": "Gala Night 2"}, "Updated the event branding.")
        [n] = inbox(coordinator, TYPE_CHANGE_REQUEST)
        assert n.title == "Change requested"
        assert "Name" in n.message and "Updated the event branding." in n.message
        assert n.link == f"/change-requests?id={request.id}"

    def test_significant_change_is_labelled(self, app, organiser, coordinator, staff):
        event = submitted_and_assigned(organiser, coordinator)
        cr.submit_change_request(event, organiser, {"expected_attendance": 200}, "More guests confirmed.")
        [n] = inbox(coordinator, TYPE_CHANGE_REQUEST)
        assert n.title == "Significant change requested"

    def test_withdrawal_request(self, app, organiser, coordinator, staff):
        event = submitted_and_assigned(organiser, coordinator)
        withdrawal = cr.request_withdrawal(event, organiser, "The sponsor has pulled out.")
        [n] = inbox(coordinator, TYPE_CHANGE_REQUEST)
        assert n.title == "Withdrawal requested"
        assert "The sponsor has pulled out." in n.message
        assert n.link == f"/change-requests?id={withdrawal.id}"

    def test_unassigned_event_sends_nothing(self, app, organiser, staff):
        event = review.submit_event(new_event(organiser), organiser)  # waiting in the Unassigned queue
        cr.submit_change_request(event, organiser, {"name": "Gala Night 2"}, "Updated the event branding.")
        assert inbox(organiser, TYPE_CHANGE_REQUEST) == []

    def test_organiser_gets_no_extra_notification(self, app, organiser, coordinator, staff):
        event = submitted_and_assigned(organiser, coordinator)
        before = len(inbox(organiser, TYPE_ORGANISER_UPDATE))
        cr.submit_change_request(event, organiser, {"name": "Gala Night 2"}, "Updated the event branding.")
        cr.request_withdrawal(event, organiser, "The sponsor has pulled out.")
        assert len(inbox(organiser, TYPE_ORGANISER_UPDATE)) == before


# --- Clarification ----------------------------------------------------------

class TestCoordinatorClarification:
    def test_confirmation_when_comment_posted(self, app, organiser, coordinator, staff):
        event = submitted_and_assigned(organiser, coordinator)
        review.request_clarification(event, coordinator, "Please confirm the guest list size.")
        [n] = inbox(coordinator, TYPE_CLARIFICATION)
        assert n.title == "Clarification request sent"
        assert "Please confirm the guest list size." in n.message

    def test_notified_when_organiser_responds(self, app, organiser, coordinator, staff):
        event = submitted_and_assigned(organiser, coordinator)
        review.request_clarification(event, coordinator, "Please confirm the guest list size.")
        review_id = event.reviews[-1].id
        review.respond_to_clarification(event, organiser, review_id, {"comments": "About 120 guests in total."})

        responses = [n for n in inbox(coordinator, TYPE_CLARIFICATION)
                     if n.data["kind"] == "clarification_response"]
        assert len(responses) == 1
        assert responses[0].title == "Clarification response received"
        assert "About 120 guests in total." in responses[0].message


# --- Booked venue marked unavailable ---------------------------------------

def _booked_venue_notices(coordinator):
    return [n for n in inbox(coordinator, TYPE_VENUE_BOOKING_UPDATE)
            if n.data.get("change") == "availability_flag"]


class TestCoordinatorToldWhenBookedVenueUnavailable:
    def test_extending_a_period_over_the_booking_notifies(self, app, organiser, coordinator, staff):
        event, venue, booking = _planning_event_with_booking(organiser, coordinator, staff["venue1"])
        far = booking.start_datetime - timedelta(days=3)
        block, _ = availability.add_unavailability(venue, staff["venue1"], far, far + timedelta(hours=1), "Maintenance")
        assert _booked_venue_notices(coordinator) == []

        _, flags = availability.update_unavailability(venue, block.id, end=booking.start_datetime + timedelta(hours=1))
        assert len(flags) == 1
        [n] = _booked_venue_notices(coordinator)
        assert n.title == "Booked venue unavailable"
        assert "Grand Hall" in n.message and "Maintenance" in n.message
        assert n.link == "/venues/availability"
        assert n.data["flagId"] == flags[0].id

    def test_adding_a_period_sends_exactly_one_notice(self, app, organiser, coordinator, staff):
        event, venue, booking = _planning_event_with_booking(organiser, coordinator, staff["venue1"])
        start = booking.start_datetime + timedelta(minutes=30)
        availability.add_unavailability(venue, staff["venue1"], start, start + timedelta(minutes=30), "Burst pipe")
        notices = inbox(coordinator, TYPE_VENUE_BOOKING_UPDATE)
        assert len(notices) == 1  # the rejection notice; the flag does not duplicate it
        assert "Burst pipe" in notices[0].message

    def test_venue_detail_change_that_breaks_booking_notifies(self, app, organiser, coordinator, staff):
        event, venue, _ = _planning_event_with_booking(organiser, coordinator, staff["venue1"])
        catalogue.update_venue(venue, {"capacity": 20})
        [n] = _booked_venue_notices(coordinator)
        assert "Grand Hall" in n.message

    def test_duplicate_flag_does_not_renotify(self, app, organiser, coordinator, staff):
        event, venue, _ = _planning_event_with_booking(organiser, coordinator, staff["venue1"])
        availability.add_flag_once(event.id, venue.id, "Fire alarm testing")
        availability.add_flag_once(event.id, venue.id, "Fire alarm testing")
        db.session.commit()
        assert len(_booked_venue_notices(coordinator)) == 1

    def test_unassigned_event_is_skipped(self, app, organiser, coordinator, staff):
        event, venue, _ = _planning_event_with_booking(organiser, coordinator, staff["venue1"])
        db.session.get(Event, event.id).coordinator_id = None
        db.session.commit()
        assert availability.add_flag_once(event.id, venue.id, "Fire alarm testing") is not None
        db.session.commit()
        assert _booked_venue_notices(coordinator) == []


# --- Safety check decisions -------------------------------------------------

def _decide(event, officer_id, decision, comments=None):
    from app.models.user import User
    if decision == "approved":
        factors = {k: {"outcome": "satisfactory", "notes": None} for k in SAFETY_FACTOR_ORDER}
        affected = None
    else:
        factors = {k: {"outcome": "satisfactory", "notes": None} for k in SAFETY_FACTOR_ORDER}
        factors[SAFETY_FACTOR_ORDER[0]] = {"outcome": "concern", "notes": "Needs attention"}
        affected = ["venue"]
    safety.review_safety_check(event, db.session.get(User, officer_id), decision, comments,
                               affected_arrangements=affected, factor_assessments=factors)


class TestCoordinatorToldOfSafetyDecision:
    @pytest.mark.parametrize("decision,title", [
        ("changes_requested", "Safety check changes requested"),
        ("rejected", "Safety check rejected"),
    ])
    def test_changes_requested_or_rejected(self, app, organiser, coordinator, staff, decision, title):
        event, _, _ = _planning_event_with_booking(organiser, coordinator, staff["venue1"])
        db.session.get(Event, event.id).status = "safety_check"
        db.session.commit()
        _decide(event, staff["safety1"], decision, "The fire exits are blocked by the stage layout.")

        [n] = inbox(coordinator, TYPE_SAFETY_CHECK)
        assert n.title == title
        assert "Sid Safety" in n.message
        assert "The fire exits are blocked by the stage layout." in n.message
        assert "venue" in n.message and "returned to planning" in n.message
        assert n.data["decision"] == decision
        assert event.status == "planning"

    def test_approved_still_notifies(self, app, organiser, coordinator, staff):
        event, _, _ = _planning_event_with_booking(organiser, coordinator, staff["venue1"])
        db.session.get(Event, event.id).status = "safety_check"
        db.session.commit()
        _decide(event, staff["safety1"], "approved")
        [n] = inbox(coordinator, TYPE_SAFETY_CHECK)
        assert n.title == "Safety check approved: confirm the event"
