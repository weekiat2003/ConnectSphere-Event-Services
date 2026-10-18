"""Coordinator cancels an event (Event Status Management)."""
from datetime import date, datetime, time, timedelta

import pytest
from flask import url_for
from flask_jwt_extended import create_access_token
from werkzeug.security import generate_password_hash

from app.change_requests.services import (
    ChangeRequestError,
    process_routine_change,
    submit_change_request,
)
from app.events.services import review
from app.events.services import status as status_service
from app.events.services.status import EventActionError, InvalidTransitionError
from app.extensions import db
from app.models.equipment import EquipmentItem, EquipmentReservation
from app.models.event import Event
from app.models.user import Role, User
from app.models.venue import (
    BOOKING_APPROVED, BOOKING_PENDING, BOOKING_REJECTED, BOOKING_RELEASED, VenueBooking,
)

BASE_DAY = date.today() + timedelta(days=60)
REASON = "The client has cancelled their launch."


# ---------------------------------------------------------------------
# Helpers (call inside `with app.app_context():`)
# ---------------------------------------------------------------------

def _user(role_name, name):
    user = User(
        name=name,
        email=f"{name.replace(' ', '.').lower()}@cancel-tests.com",
        password_hash=generate_password_hash("password"),
    )
    user.roles = [Role.query.filter_by(name=role_name).first()]
    db.session.add(user)
    db.session.commit()
    return user.id


def _people():
    return (
        _user("event_organiser", "Olivia Organiser"),
        _user("event_coordinator", "Carlos Coordinator"),
        _user("event_coordinator", "Priya Coordinator"),
    )


def _event(organiser_id, coordinator_id, status="planning"):
    event = Event(
        organiser_id=organiser_id, coordinator_id=coordinator_id, status=status,
        name="Annual Conference", purpose="Networking", description="A conference for the team",
        proposed_date=BASE_DAY, proposed_time=time(9, 30), expected_attendance=80,
    )
    db.session.add(event)
    db.session.commit()
    return event


def _booking(event, status=BOOKING_APPROVED):
    booking = VenueBooking(
        event_id=event.id, venue_id=1, requested_by=500, status=status,
        start_datetime=datetime.combine(BASE_DAY, time(9, 30)),
        end_datetime=datetime.combine(BASE_DAY, time(17, 0)),
    )
    db.session.add(booking)
    db.session.commit()
    return booking


def _reservation(event):
    item = EquipmentItem(name="Projector", total_quantity=5)
    db.session.add(item)
    db.session.commit()
    reservation = EquipmentReservation(
        event_id=event.id, equipment_item_id=item.id, quantity=2, status="reserved",
        start_datetime=datetime.combine(BASE_DAY, time(9, 0)),
        end_datetime=datetime.combine(BASE_DAY, time(17, 0)),
    )
    db.session.add(reservation)
    db.session.commit()
    return reservation


def _post(app, user_id, event_id, body):
    """POST the cancel endpoint as `user_id`. Adjust the endpoint name to yours."""
    with app.test_request_context():
        path = url_for("events.cancel_event_route", event_id=event_id)
    with app.app_context():
        user = db.session.get(User, user_id)
        token = create_access_token(
            identity=str(user_id),
            additional_claims={"roles": user.role_names(), "name": user.name},
        )
    return app.test_client().post(path, json=body, headers={"Authorization": f"Bearer {token}"})


# ---------------------------------------------------------------------
# 1. Who can cancel, and when
# ---------------------------------------------------------------------

@pytest.mark.parametrize("status", ["approved", "planning", "safety_check", "confirmed"])
def test_assigned_coordinator_can_cancel_in_these_statuses(app, status):
    with app.app_context():
        organiser, coordinator, _ = _people()
        event = _event(organiser, coordinator, status)

        status_service.cancel_event(event.id, coordinator, REASON)

        assert db.session.get(Event, event.id).status == "cancelled"


@pytest.mark.parametrize("status", ["draft", "completed", "rejected", "cancelled"])
def test_cancel_is_refused_in_other_statuses(app, status):
    with app.app_context():
        organiser, coordinator, _ = _people()
        event = _event(organiser, coordinator, status)

        with pytest.raises(EventActionError):
            status_service.cancel_event(event.id, coordinator, REASON)

        assert db.session.get(Event, event.id).status == status


def test_another_coordinator_cannot_cancel(app):
    with app.app_context():
        organiser, coordinator, other = _people()
        event = _event(organiser, coordinator)

        with pytest.raises(PermissionError, match="assigned"):
            status_service.cancel_event(event.id, other, REASON)

        assert db.session.get(Event, event.id).status == "planning"


def test_direct_request_from_other_users_is_refused(app):
    with app.app_context():
        organiser, coordinator, other = _people()
        event_id = _event(organiser, coordinator).id

    assert _post(app, other, event_id, {"reason": REASON, "confirmed": True}).status_code == 403
    assert _post(app, organiser, event_id, {"reason": REASON, "confirmed": True}).status_code == 403


# ---------------------------------------------------------------------
# 2. Reason rules (same as clarification comments)
# ---------------------------------------------------------------------

@pytest.mark.parametrize("bad_reason", ["", "   ", None, "!!!???", "12345"])
def test_invalid_reason_is_refused_and_nothing_is_saved(app, bad_reason):
    with app.app_context():
        organiser, coordinator, _ = _people()
        event = _event(organiser, coordinator)
        booking = _booking(event)

        with pytest.raises(EventActionError) as problem:
            status_service.cancel_event(event.id, coordinator, bad_reason)

        assert "reason" in problem.value.errors
        assert db.session.get(Event, event.id).status == "planning"
        assert db.session.get(VenueBooking, booking.id).status == BOOKING_APPROVED
        assert not [h for h in event.status_history if h.new_status == "cancelled"]


def test_dry_run_validates_but_writes_nothing(app):
    with app.app_context():
        organiser, coordinator, _ = _people()
        event = _event(organiser, coordinator)

        status_service.cancel_event(event.id, coordinator, REASON, dry_run=True)

        assert db.session.get(Event, event.id).status == "planning"


# ---------------------------------------------------------------------
# 3. Confirmation
# ---------------------------------------------------------------------

def test_valid_reason_asks_for_confirmation_first(app):
    with app.app_context():
        organiser, coordinator, _ = _people()
        event_id = _event(organiser, coordinator).id

    response = _post(app, coordinator, event_id, {"reason": REASON})

    assert response.status_code == 409
    assert response.get_json()["requiresConfirmation"] is True
    with app.app_context():
        assert db.session.get(Event, event_id).status == "planning"


def test_confirmed_request_cancels_the_event(app):
    with app.app_context():
        organiser, coordinator, _ = _people()
        event_id = _event(organiser, coordinator).id

    response = _post(app, coordinator, event_id, {"reason": REASON, "confirmed": True})

    assert response.status_code == 200
    assert response.get_json()["status"] == "cancelled"


# ---------------------------------------------------------------------
# 4. What is recorded
# ---------------------------------------------------------------------

def test_cancellation_records_reason_who_and_when(app):
    with app.app_context():
        organiser, coordinator, _ = _people()
        event = _event(organiser, coordinator)

        status_service.cancel_event(event.id, coordinator, REASON)

        cancellation = db.session.get(Event, event.id).to_dict()["cancellation"]
        assert cancellation["reason"] == REASON
        assert cancellation["coordinatorId"] == coordinator
        assert cancellation["coordinatorName"] == "Carlos Coordinator"
        datetime.fromisoformat(cancellation["timestamp"])


# ---------------------------------------------------------------------
# 5. Arrangements are released
# ---------------------------------------------------------------------

def test_pending_and_approved_bookings_and_reservations_are_released(app):
    with app.app_context():
        organiser, coordinator, _ = _people()
        event = _event(organiser, coordinator)
        pending = _booking(event, BOOKING_PENDING)
        approved = _booking(event, BOOKING_APPROVED)
        rejected = _booking(event, BOOKING_REJECTED)
        reservation = _reservation(event)

        status_service.cancel_event(event.id, coordinator, REASON)

        assert db.session.get(VenueBooking, pending.id).status == BOOKING_RELEASED
        assert db.session.get(VenueBooking, approved.id).status == BOOKING_RELEASED
        assert db.session.get(VenueBooking, rejected.id).status == BOOKING_REJECTED  # untouched
        assert db.session.get(EquipmentReservation, reservation.id).status == "released"


# ---------------------------------------------------------------------
# 6. A cancelled event is frozen
# ---------------------------------------------------------------------

def test_cancelled_event_refuses_change_requests(app):
    with app.app_context():
        organiser, coordinator, _ = _people()
        event = _event(organiser, coordinator)
        status_service.cancel_event(event.id, coordinator, REASON)

        with pytest.raises(ChangeRequestError):
            submit_change_request(event, organiser, {"name": "Annual Summit"}, REASON)


def test_open_change_request_cannot_be_processed_after_cancellation(app):
    with app.app_context():
        organiser, coordinator, _ = _people()
        event = _event(organiser, coordinator)
        change = submit_change_request(event, organiser, {"name": "Annual Summit"}, REASON)
        status_service.cancel_event(event.id, coordinator, REASON)

        with pytest.raises(ChangeRequestError):
            process_routine_change(change.id, coordinator)


def test_cancelled_event_refuses_clarification_responses(app):
    with app.app_context():
        organiser, coordinator, _ = _people()
        event = _event(organiser, coordinator, "under_review")
        review.request_clarification(event, coordinator, "Please confirm the final headcount.")
        review_id = event.reviews[0].id
        event.status = "cancelled"
        db.session.commit()

        with pytest.raises(ValueError, match="cancelled"):
            review.respond_to_clarification(event, organiser, review_id, {"comments": "About 80 people."})


# ---------------------------------------------------------------------
# 7. No way back
# ---------------------------------------------------------------------

@pytest.mark.parametrize("target", ["planning", "approved", "submitted", "confirmed"])
def test_cancelled_event_cannot_be_reopened(app, target):
    with app.app_context():
        organiser, coordinator, _ = _people()
        event = _event(organiser, coordinator, "cancelled")

        with pytest.raises(InvalidTransitionError):
            status_service.change_status(event, target, coordinator, "Reopen")

        assert db.session.get(Event, event.id).status == "cancelled"