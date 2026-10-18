import pytest
from datetime import datetime, date, time, timedelta
from unittest.mock import MagicMock

from app.models.event import Event, EventStatusHistory
from app.models.user import Role, User
from app.models.venue import Venue, VenueBooking
from app.models.change_request import ChangeRequest
from app.models.equipment import EquipmentReservation
from app.events.routes import _require_confirmation
from app.events.services.status import (
    cancel_event,
    ensure_not_cancelled,
)
from app.extensions import db
from app.common.text_validation import validate_descriptive_text


@pytest.fixture
def event():
    return Event(
        id=1,
        organiser_id=100,
        coordinator_id=200,
        status="confirmed",
        name="Annual Tech Conference",
        purpose="Discuss latest tech trends",
        description="A conference for tech enthusiasts",
        proposed_date=date(2030, 6, 1),
        proposed_time=time(10, 0),
        expected_attendance=500,
        registration_required=True,
    )


@pytest.fixture
def coordinator():
    return {"id": 200, "role": "event_coordinator"}


@pytest.fixture
def second_coordinator():
    return {"id": 201, "role": "event_coordinator"}


@pytest.fixture
def organiser():
    return {"id": 100, "role": "event_organiser"}


@pytest.fixture
def two_real_coordinators(app):
    with app.app_context():
        role = Role.query.filter_by(name="event_coordinator").first()

        coordinator_a = User(
            name="Real Coordinator A",
            email="cancel.coord.a@test.com",
            password_hash="password",
        )
        coordinator_a.roles = [role]

        coordinator_b = User(
            name="Real Coordinator B",
            email="cancel.coord.b@test.com",
            password_hash="password",
        )
        coordinator_b.roles = [role]

        db.session.add_all([coordinator_a, coordinator_b])
        db.session.commit()

        return coordinator_a.id, coordinator_b.id


def _persist_event(coordinator_id=200, status="confirmed", **overrides):
    values = dict(
        organiser_id=100,
        coordinator_id=coordinator_id,
        status=status,
        name="Cancellation Test Event",
        purpose="Testing cancellation",
        description="An event used to test cancellation.",
        proposed_date=date(2030, 6, 1),
        proposed_time=time(9, 30),
        expected_attendance=80,
        registration_required=True,
    )
    values.update(overrides)

    event = Event(**values)
    db.session.add(event)
    db.session.commit()
    return event


def _persist_booking(event, status="approved"):
    venue = Venue(
        name="Cancellation Test Venue",
        capacity=100,
    )
    db.session.add(venue)
    db.session.commit()

    booking = VenueBooking(
        event_id=event.id,
        venue_id=venue.id,
        requested_by=event.organiser_id,
        status=status,
        start_datetime=datetime.combine(event.proposed_date, time(9, 0)),
        end_datetime=datetime.combine(event.proposed_date, time(17, 0)),
    )
    db.session.add(booking)
    db.session.commit()
    return booking


def _persist_change_request(event, status="pending"):
    change_request = ChangeRequest(
        event_id=event.id,
        organiser_id=event.organiser_id,
        request_type="change",
        requested_changes={
            "expected_attendance": {"from": 80, "to": 120}
        },
        reason="Please move the event to a larger room.",
        is_significant=True,
        status=status,
    )
    db.session.add(change_request)
    db.session.commit()
    return change_request


# =======================================================================
# Cancellation eligibility
# =======================================================================

@pytest.mark.parametrize(
    "status",
    ["submitted", "under_review", "approved", "planning", "confirmed"],
)
def test_cancel_event_is_allowed_for_eligible_statuses(app, event, coordinator, status):
    with app.app_context():
        event.status = status

        updated = cancel_event(
            event,
            coordinator["id"],
            "The event has been postponed.",
        )

        assert updated.status == "cancelled"


@pytest.mark.parametrize(
    "status",
    ["draft", "completed", "rejected", "cancelled"],
)
def test_cancel_event_is_rejected_for_ineligible_statuses(
    app,
    event,
    coordinator,
    status,
):
    with app.app_context():
        event.status = status

        with pytest.raises(Exception, match="can be cancelled"):
            cancel_event(
                event,
                coordinator["id"],
                "The event has been postponed.",
            )

        assert event.status == status


def test_cancel_event_requires_the_assigned_coordinator(app, event, second_coordinator):
    with app.app_context():
        with pytest.raises(
            PermissionError,
            match="Only the assigned Coordinator can cancel this event",
        ):
            cancel_event(
                event,
                second_coordinator["id"],
                "The event has been postponed.",
            )

        assert event.status == "confirmed"


def test_cancel_event_cannot_be_performed_by_the_organiser(app, event, organiser):
    with app.app_context():
        with pytest.raises(
            PermissionError,
            match="Only the assigned Coordinator can cancel this event",
        ):
            cancel_event(
                event,
                organiser["id"],
                "The event has been postponed.",
            )

        assert event.status == "confirmed"


# =======================================================================
# Cancellation reason validation
# =======================================================================

@pytest.mark.parametrize(
    "invalid_reason",
    [None, "", "   ", "12345", "!!!", "@@@###", "-----"],
)
def test_cancel_event_rejects_invalid_reasons(
    app,
    event,
    coordinator,
    invalid_reason,
):
    with app.app_context():
        with pytest.raises(ValueError):
            cancel_event(event, coordinator["id"], invalid_reason)

        assert event.status == "confirmed"


def test_cancel_event_accepts_a_descriptive_reason(app, event, coordinator):
    with app.app_context():
        reason = "The venue became unavailable due to flooding."

        updated = cancel_event(event, coordinator["id"], reason)

        assert updated.status == "cancelled"


def test_cancellation_uses_the_same_text_rules_as_other_reasons():
    with pytest.raises(ValueError):
        validate_descriptive_text("!!!", "cancellation reason")

    validate_descriptive_text(
        "The event has been postponed.",
        "cancellation reason",
    )


# =======================================================================
# Confirmation gate
# =======================================================================

def test_cancel_confirmation_is_required_before_the_action(app, event):
    with app.app_context():
        event.clarification_flag = False

        result = _require_confirmation(event, {}, "cancel")

        assert result is not None

        response, status_code = result
        body = response.get_json()

        assert status_code == 409
        assert body["requiresConfirmation"] is True
        assert body["hasUnresolvedClarification"] is False
        assert "cancel" in body["message"]


def test_cancel_confirmation_warns_about_an_unresolved_clarification(app, event):
    with app.app_context():
        event.clarification_flag = True

        result = _require_confirmation(event, {}, "cancel")

        assert result is not None

        response, status_code = result
        body = response.get_json()

        assert status_code == 409
        assert body["requiresConfirmation"] is True
        assert body["hasUnresolvedClarification"] is True
        assert "unresolved clarification" in body["message"].lower()
        assert "cancel" in body["message"]


def test_explicit_confirmation_allows_cancellation(app, event):
    with app.app_context():
        event.clarification_flag = True

        result = _require_confirmation(
            event,
            {"confirmed": True},
            "cancel",
        )

        assert result is None


# =======================================================================
# Cancellation record
# =======================================================================

def test_cancel_event_sets_the_final_cancelled_status(app, event, coordinator):
    with app.app_context():
        reason = "The event has been postponed."

        updated = cancel_event(event, coordinator["id"], reason)

        assert updated.status == "cancelled"
        assert updated.registration_closed_at is not None


def test_cancel_event_records_old_status_new_status_reason_and_actor(
    app,
    two_real_coordinators,
):
    with app.app_context():
        coordinator_id, _ = two_real_coordinators
        event = _persist_event(coordinator_id=coordinator_id)

        reason = "The event has been postponed."
        cancel_event(event, coordinator_id, reason)

        history = EventStatusHistory.query.filter_by(event_id=event.id).all()

        assert len(history) == 1
        assert history[0].old_status == "confirmed"
        assert history[0].new_status == "cancelled"
        assert history[0].changed_by == coordinator_id
        assert history[0].reason == reason
        assert history[0].changed_at is not None


def test_cancelled_event_remains_visible_with_its_reason(
    app,
    two_real_coordinators,
):
    with app.app_context():
        coordinator_id, _ = two_real_coordinators
        event = _persist_event(coordinator_id=coordinator_id)

        reason = "The event has been postponed."
        cancel_event(event, coordinator_id, reason)

        payload = event.to_dict()

        assert payload["status"] == "cancelled"
        assert payload["organiserId"] == event.organiser_id
        assert payload["coordinatorId"] == coordinator_id
        assert payload["statusHistory"][-1]["reason"] == reason


# =======================================================================
# Arrangements and registration
# =======================================================================

def test_cancel_event_releases_pending_and_approved_venue_bookings(
    app,
    two_real_coordinators,
):
    with app.app_context():
        coordinator_id, _ = two_real_coordinators
        event = _persist_event(coordinator_id=coordinator_id)

        approved_booking = _persist_booking(event, status="approved")
        pending_booking = _persist_booking(event, status="pending")

        reason = "The event has been postponed."
        cancel_event(event, coordinator_id, reason)

        db.session.refresh(approved_booking)
        db.session.refresh(pending_booking)

        assert approved_booking.status == "cancelled"
        assert pending_booking.status == "cancelled"
        assert approved_booking.decided_by == coordinator_id
        assert approved_booking.decided_at is not None
        assert reason in approved_booking.decision_reason


def test_cancel_event_releases_active_equipment_reservations(
    app,
    two_real_coordinators,
    monkeypatch,
):
    with app.app_context():
        coordinator_id, _ = two_real_coordinators
        event = _persist_event(coordinator_id=coordinator_id)

        reservation_query = MagicMock()
        monkeypatch.setattr(EquipmentReservation, "query", reservation_query)

        reason = "The event has been postponed."
        cancel_event(event, coordinator_id, reason)

        reservation_query.filter.return_value.update.assert_called_once_with(
            {"status": "released"},
            synchronize_session=False,
        )


def test_cancel_event_closes_registration(app, event, coordinator):
    with app.app_context():
        assert event.registration_closed_at is None

        updated = cancel_event(
            event,
            coordinator["id"],
            "The event has been postponed.",
        )

        assert updated.registration_closed_at is not None


# =======================================================================
# Open change requests
# =======================================================================

def test_cancel_event_rejects_pending_and_re_review_change_requests(
    app,
    two_real_coordinators,
):
    with app.app_context():
        coordinator_id, _ = two_real_coordinators
        event = _persist_event(coordinator_id=coordinator_id)

        pending_request = _persist_change_request(event, status="pending")
        re_review_request = _persist_change_request(event, status="re_review")

        cancel_event(
            event,
            coordinator_id,
            "The event has been postponed.",
        )

        db.session.refresh(pending_request)
        db.session.refresh(re_review_request)

        assert pending_request.status == "rejected"
        assert re_review_request.status == "rejected"
        assert pending_request.decision_reason == "Event cancelled"
        assert re_review_request.decision_reason == "Event cancelled"


# =======================================================================
# Finality
# =======================================================================

def test_cancelled_event_cannot_be_cancelled_again(app, event, coordinator):
    with app.app_context():
        reason = "The event has been postponed."

        cancel_event(event, coordinator["id"], reason)

        with pytest.raises(Exception, match="can be cancelled"):
            cancel_event(event, coordinator["id"], reason)

        assert event.status == "cancelled"
        assert EventStatusHistory.query.filter_by(event_id=event.id).count() == 1


def test_ensure_not_cancelled_blocks_further_changes(app, event, coordinator):
    with app.app_context():
        cancel_event(
            event,
            coordinator["id"],
            "The event has been postponed.",
        )

        with pytest.raises(
            PermissionError,
            match="A cancelled event cannot be changed",
        ):
            ensure_not_cancelled(event)