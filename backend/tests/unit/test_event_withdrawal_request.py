"""Organiser requests withdrawal of a submitted event (Event Change Requests)."""
from datetime import date, datetime, time, timedelta

import pytest

from app.change_requests.services import (
    ChangeRequestError,
    can_request_withdrawal,
    list_change_requests_for_coordinator,
    list_change_requests_for_event,
    request_withdrawal,
    submit_change_request,
)
from app.extensions import db
from app.models.change_request import ChangeRequest
from app.models.event import Event
from app.models.venue import BOOKING_APPROVED, VenueBooking

ORGANISER_ID = 100
OTHER_ORGANISER_ID = 101
COORDINATOR_ID = 200
OTHER_COORDINATOR_ID = 201
BASE_DAY = date.today() + timedelta(days=60)
REASON = "The client has cancelled the launch."
WITHDRAWABLE = ("submitted", "under_review", "approved", "planning", "confirmed")
NOT_WITHDRAWABLE = ("draft", "rejected", "completed", "cancelled")


# ---------------------------------------------------------------------
# Helpers (call inside `with app.app_context():`)
# ---------------------------------------------------------------------

def _event(status="under_review", **overrides):
    values = dict(
        organiser_id=ORGANISER_ID,
        coordinator_id=COORDINATOR_ID,
        status=status,
        name="Annual Conference",
        purpose="Networking",
        description="A conference for the team",
        proposed_date=BASE_DAY,
        proposed_time=time(9, 30),
        expected_attendance=80,
    )
    values.update(overrides)
    event = Event(**values)
    db.session.add(event)
    db.session.commit()
    return event


def _withdraw(event, reason=REASON, organiser_id=ORGANISER_ID):
    return request_withdrawal(event, organiser_id, reason)


# ---------------------------------------------------------------------
# 1. Who and when
# ---------------------------------------------------------------------

@pytest.mark.parametrize("status", WITHDRAWABLE)
def test_option_is_offered_for_every_eligible_status(app, status):
    with app.app_context():
        assert can_request_withdrawal(_event(status), ORGANISER_ID) is True


@pytest.mark.parametrize("status", NOT_WITHDRAWABLE)
def test_option_is_not_offered_for_any_other_status(app, status):
    with app.app_context():
        assert can_request_withdrawal(_event(status), ORGANISER_ID) is False


def test_option_is_not_offered_to_another_organiser(app):
    with app.app_context():
        assert can_request_withdrawal(_event(), OTHER_ORGANISER_ID) is False


@pytest.mark.parametrize("status", NOT_WITHDRAWABLE)
def test_request_is_refused_for_any_other_status(app, status):
    with app.app_context():
        event = _event(status)
        with pytest.raises(ChangeRequestError, match="Withdrawal can only be requested"):
            _withdraw(event)
        assert ChangeRequest.query.count() == 0


def test_request_is_refused_for_another_organiser(app):
    with app.app_context():
        event = _event()
        with pytest.raises(PermissionError, match="organiser"):
            _withdraw(event, organiser_id=OTHER_ORGANISER_ID)
        assert ChangeRequest.query.count() == 0


# ---------------------------------------------------------------------
# 2. Reason
# ---------------------------------------------------------------------

@pytest.mark.parametrize(
    "reason",
    ["", "   ", "!!!", "12345", None],
    ids=["empty", "blank", "symbols", "digits", "missing"],
)
def test_reason_must_contain_real_words(app, reason):
    with app.app_context():
        event = _event()
        with pytest.raises(ChangeRequestError) as raised:
            _withdraw(event, reason=reason)
        assert "reason" in raised.value.errors
        assert ChangeRequest.query.count() == 0


# ---------------------------------------------------------------------
# 3. Submission
# ---------------------------------------------------------------------

def test_valid_request_is_saved_as_a_pending_withdrawal_linked_to_the_event(app):
    with app.app_context():
        event = _event()
        saved = _withdraw(event)

        stored = db.session.get(ChangeRequest, saved.id)
        assert stored.request_type == "withdrawal"
        assert stored.status == "pending"
        assert stored.event_id == event.id
        assert stored.organiser_id == ORGANISER_ID
        assert stored.reason == REASON
        assert stored.requested_changes == {}


def test_pending_request_is_available_to_the_assigned_coordinator_only(app):
    with app.app_context():
        saved = _withdraw(_event())

        assert [r.id for r in list_change_requests_for_coordinator(COORDINATOR_ID)] == [saved.id]
        assert list_change_requests_for_coordinator(OTHER_COORDINATOR_ID) == []


@pytest.mark.parametrize("status", WITHDRAWABLE)
def test_event_status_is_unchanged_until_the_coordinator_decides(app, status):
    with app.app_context():
        event = _event(status)
        _withdraw(event)
        db.session.refresh(event)
        assert event.status == status


def test_event_details_and_bookings_are_untouched(app):
    with app.app_context():
        event = _event("confirmed")
        start, end = datetime.combine(BASE_DAY, time(9, 30)), datetime.combine(BASE_DAY, time(17, 0))
        booking = VenueBooking(
            event_id=event.id, venue_id=1, requested_by=500,
            status=BOOKING_APPROVED, start_datetime=start, end_datetime=end,
        )
        db.session.add(booking)
        db.session.commit()

        _withdraw(event)

        db.session.refresh(event)
        db.session.refresh(booking)
        assert (event.name, event.proposed_date, event.expected_attendance) == ("Annual Conference", BASE_DAY, 80)
        assert (booking.status, booking.start_datetime, booking.end_datetime) == (BOOKING_APPROVED, start, end)


# ---------------------------------------------------------------------
# 4. One at a time
# ---------------------------------------------------------------------

def test_a_second_request_is_refused_while_one_is_pending(app):
    with app.app_context():
        event = _event()
        _withdraw(event)

        with pytest.raises(ChangeRequestError) as raised:
            _withdraw(event, reason="Asking again just in case.")

        assert "request" in raised.value.errors
        assert ChangeRequest.query.count() == 1


def test_a_new_request_is_allowed_once_the_earlier_one_was_rejected(app):
    with app.app_context():
        event = _event()
        first = _withdraw(event)
        first.status = "rejected"
        db.session.commit()

        second = _withdraw(event, reason="Still need to withdraw this event.")

        assert second.status == "pending"
        assert ChangeRequest.query.count() == 2


def test_a_pending_change_request_does_not_block_a_withdrawal(app):
    with app.app_context():
        event = _event("confirmed")
        submit_change_request(event, ORGANISER_ID, {"expected_attendance": 120}, REASON)

        withdrawal = _withdraw(event)

        assert withdrawal.request_type == "withdrawal"
        assert ChangeRequest.query.count() == 2


def test_a_pending_request_on_another_event_does_not_block(app):
    with app.app_context():
        _withdraw(_event())
        _withdraw(_event(name="Second Event"))
        assert ChangeRequest.query.count() == 2


# ---------------------------------------------------------------------
# 5. Tracking
# ---------------------------------------------------------------------

def test_organiser_sees_the_withdrawal_request_with_its_details(app):
    with app.app_context():
        event = _event()
        _withdraw(event)

        details = list_change_requests_for_event(event, ORGANISER_ID)[0].to_dict()

        assert details["requestType"] == "withdrawal"
        assert details["status"] == "pending"
        assert details["reason"] == REASON
        assert details["createdAt"] is not None
        assert details["decisionReason"] is None


def test_withdrawals_and_changes_are_listed_together_newest_first(app):
    with app.app_context():
        event = _event("confirmed")
        change = submit_change_request(event, ORGANISER_ID, {"expected_attendance": 120}, REASON)
        withdrawal = _withdraw(event)

        listed = list_change_requests_for_event(event, ORGANISER_ID)

        assert [r.id for r in listed] == [withdrawal.id, change.id]
        assert [r.request_type for r in listed] == ["withdrawal", "change"]


def test_the_coordinators_decision_reason_is_shown(app):
    with app.app_context():
        event = _event()
        saved = _withdraw(event)
        saved.status = "rejected"
        saved.decision_reason = "The venue deposit is already paid."
        db.session.commit()

        details = list_change_requests_for_event(event, ORGANISER_ID)[0].to_dict()

        assert details["status"] == "rejected"
        assert details["decisionReason"] == "The venue deposit is already paid."


# ---------------------------------------------------------------------
# 6. Coordinator view
# ---------------------------------------------------------------------

def test_the_coordinator_can_tell_withdrawals_from_changes(app):
    with app.app_context():
        event = _event("confirmed")
        submit_change_request(event, ORGANISER_ID, {"expected_attendance": 120}, REASON)
        _withdraw(event)

        kinds = [r.request_type for r in list_change_requests_for_coordinator(COORDINATOR_ID)]

        assert sorted(kinds) == ["change", "withdrawal"]