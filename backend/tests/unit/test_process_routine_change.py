"""Coordinator processes a routine change (Event Change Requests)."""
from datetime import date, datetime, time, timedelta

import pytest
from flask import url_for
from flask_jwt_extended import create_access_token
from werkzeug.security import generate_password_hash

from app.change_requests.services import (
    ChangeRequestError,
    get_review_detail,
    process_routine_change,
    request_withdrawal,
    submit_change_request,
)
from app.extensions import db
from app.models.change_request import ChangeRequest, EventChangeHistory
from app.models.event import Event, EventEquipmentRequirement
from app.models.user import Role, User
from app.models.venue import BOOKING_APPROVED, VenueBooking

BASE_DAY = date.today() + timedelta(days=60)
REASON = "The client renamed their launch."


# ---------------------------------------------------------------------
# Helpers (call inside `with app.app_context():`)
# ---------------------------------------------------------------------

def _user(role_name, name):
    user = User(
        name=name,
        email=f"{name.replace(' ', '.').lower()}@process-tests.com",
        password_hash=generate_password_hash("password"),
    )
    user.roles = [Role.query.filter_by(name=role_name).first()]
    db.session.add(user)
    db.session.commit()
    return user.id


def _people():
    """A real organiser and two real coordinators, as ids."""
    return (
        _user("event_organiser", "Olivia Organiser"),
        _user("event_coordinator", "Carlos Coordinator"),
        _user("event_coordinator", "Priya Coordinator"),
    )


def _event(organiser_id, coordinator_id, status="confirmed"):
    event = Event(
        organiser_id=organiser_id,
        coordinator_id=coordinator_id,
        status=status,
        name="Annual Conference",
        purpose="Networking",
        description="A conference for the team",
        proposed_date=BASE_DAY,
        proposed_time=time(9, 30),
        expected_attendance=80,
        accessibility_needs="Step-free access",
    )
    db.session.add(event)
    db.session.commit()
    return event


def _request(event, changes):
    return submit_change_request(event, event.organiser_id, changes, REASON)


def _stored_request(event, requested_changes):
    """A pending routine request written straight to the table, for values
    that could no longer be submitted through the normal checks."""
    row = ChangeRequest(
        event_id=event.id, organiser_id=event.organiser_id, request_type="change",
        requested_changes=requested_changes, reason=REASON, is_significant=False, status="pending",
    )
    db.session.add(row)
    db.session.commit()
    return row


def _booking(event):
    booking = VenueBooking(
        event_id=event.id, venue_id=1, requested_by=500, status=BOOKING_APPROVED,
        start_datetime=datetime.combine(BASE_DAY, time(9, 30)),
        end_datetime=datetime.combine(BASE_DAY, time(17, 0)),
    )
    db.session.add(booking)
    db.session.commit()
    return booking


# ---------------------------------------------------------------------
# 2. Applied
# ---------------------------------------------------------------------

def test_processing_applies_every_proposed_value_and_marks_the_request_processed(app):
    with app.app_context():
        organiser, coordinator, _ = _people()
        event = _event(organiser, coordinator)
        change = _request(event, {
            "name": "Annual Summit",
            "description": "A bigger event",
            "accessibility_needs": "Hearing loop",
            "registration_required": True,
            "intended_capacity": 50,
        })

        processed = process_routine_change(change.id, coordinator)

        db.session.refresh(event)
        assert (event.name, event.description, event.accessibility_needs) == (
            "Annual Summit", "A bigger event", "Hearing loop",
        )
        assert (event.registration_required, event.intended_capacity) == (True, 50)
        assert processed.status == "processed"
        assert processed.coordinator_id == coordinator
        assert processed.decided_at is not None


def test_an_optional_value_can_be_cleared(app):
    with app.app_context():
        organiser, coordinator, _ = _people()
        event = _event(organiser, coordinator)
        change = _request(event, {"accessibility_needs": ""})

        process_routine_change(change.id, coordinator)

        db.session.refresh(event)
        assert event.accessibility_needs is None


def test_a_dry_run_checks_everything_but_writes_nothing(app):
    with app.app_context():
        organiser, coordinator, _ = _people()
        event = _event(organiser, coordinator)
        change = _request(event, {"name": "Annual Summit"})

        checked = process_routine_change(change.id, coordinator, dry_run=True)

        db.session.refresh(event)
        db.session.refresh(change)
        assert checked.id == change.id
        assert event.name == "Annual Conference"
        assert change.status == "pending"
        assert EventChangeHistory.query.count() == 0


# ---------------------------------------------------------------------
# 3. Significant changes are refused
# ---------------------------------------------------------------------

@pytest.mark.parametrize(
    "changes",
    [{"expected_attendance": 120}, {"name": "Annual Summit", "expected_attendance": 120}],
    ids=["significant-only", "mixed-with-a-routine-field"],
)
def test_a_significant_request_cannot_be_processed_directly(app, changes):
    with app.app_context():
        organiser, coordinator, _ = _people()
        event = _event(organiser, coordinator)
        change = _request(event, changes)

        with pytest.raises(ChangeRequestError, match="re-review"):
            process_routine_change(change.id, coordinator)

        db.session.refresh(event)
        db.session.refresh(change)
        assert (event.name, event.expected_attendance) == ("Annual Conference", 80)
        assert change.status == "pending"
        assert EventChangeHistory.query.count() == 0


def test_a_withdrawal_request_is_not_a_routine_change(app):
    with app.app_context():
        organiser, coordinator, _ = _people()
        event = _event(organiser, coordinator)
        withdrawal = request_withdrawal(event, organiser, REASON)

        with pytest.raises(ChangeRequestError, match="withdrawal"):
            process_routine_change(withdrawal.id, coordinator)

        db.session.refresh(withdrawal)
        assert withdrawal.status == "pending"


# ---------------------------------------------------------------------
# 4. Status and arrangements untouched
# ---------------------------------------------------------------------

@pytest.mark.parametrize("status", ["approved", "planning", "confirmed"])
def test_status_bookings_and_equipment_stay_as_they_were(app, status):
    with app.app_context():
        organiser, coordinator, _ = _people()
        event = _event(organiser, coordinator, status=status)
        booking = _booking(event)
        start, end = booking.start_datetime, booking.end_datetime
        event.equipment_requirements.append(
            EventEquipmentRequirement(equipment_type="Projector", quantity=2, status="confirmed")
        )
        db.session.commit()
        change = _request(event, {"name": "Annual Summit"})

        process_routine_change(change.id, coordinator)

        db.session.refresh(event)
        db.session.refresh(booking)
        assert event.status == status
        assert (booking.status, booking.start_datetime, booking.end_datetime) == (BOOKING_APPROVED, start, end)
        assert [(e.equipment_type, e.quantity, e.status) for e in event.equipment_requirements] == [
            ("Projector", 2, "confirmed")
        ]


# ---------------------------------------------------------------------
# 5. Re-validated
# ---------------------------------------------------------------------

def test_a_value_that_no_longer_passes_the_rules_is_refused_and_nothing_is_saved(app):
    with app.app_context():
        organiser, coordinator, _ = _people()
        event = _event(organiser, coordinator)
        change = _stored_request(event, {
            "name": {"from": "Annual Conference", "to": "  "},
            "intended_capacity": {"from": None, "to": 0},
            "description": {"from": "A conference for the team", "to": "A bigger event"},
        })

        with pytest.raises(ChangeRequestError) as raised:
            process_routine_change(change.id, coordinator)

        assert {"name", "intended_capacity"} <= set(raised.value.errors)
        assert "description" not in raised.value.errors
        db.session.refresh(event)
        db.session.refresh(change)
        # all or nothing: even the valid field was not applied
        assert (event.name, event.description) == ("Annual Conference", "A conference for the team")
        assert change.status == "pending"
        assert EventChangeHistory.query.count() == 0


# ---------------------------------------------------------------------
# 6. Record
# ---------------------------------------------------------------------

def test_the_decision_shows_who_processed_it_and_when(app):
    with app.app_context():
        organiser, coordinator, _ = _people()
        change = _request(_event(organiser, coordinator), {"name": "Annual Summit"})

        process_routine_change(change.id, coordinator)
        detail = get_review_detail(change.id, coordinator)

        assert detail["decision"]["status"] == "processed"
        assert detail["decision"]["decidedBy"] == "Carlos Coordinator"
        datetime.fromisoformat(detail["decision"]["decidedAt"])
        assert detail["availableActions"] == []


def test_history_records_old_and_new_value_for_each_changed_field(app):
    with app.app_context():
        organiser, coordinator, _ = _people()
        event = _event(organiser, coordinator)
        change = _request(event, {"name": "Annual Summit", "description": "A bigger event"})

        process_routine_change(change.id, coordinator)

        rows = (
            EventChangeHistory.query.filter_by(change_request_id=change.id)
            .order_by(EventChangeHistory.field)
            .all()
        )
        assert [(r.field, r.old_value, r.new_value) for r in rows] == [
            ("description", "A conference for the team", "A bigger event"),
            ("name", "Annual Conference", "Annual Summit"),
        ]
        assert all(r.event_id == event.id and r.changed_by == coordinator and r.changed_at for r in rows)


def test_history_records_the_value_that_was_actually_replaced(app):
    with app.app_context():
        organiser, coordinator, _ = _people()
        event = _event(organiser, coordinator)
        change = _request(event, {"name": "Annual Summit"})
        event.name = "Annual Conference 2026"  # edited after the request was made
        db.session.commit()

        process_routine_change(change.id, coordinator)

        row = EventChangeHistory.query.filter_by(change_request_id=change.id).one()
        assert (row.old_value, row.new_value) == ("Annual Conference 2026", "Annual Summit")


# ---------------------------------------------------------------------
# 7. Once only
# ---------------------------------------------------------------------

def test_a_request_can_only_be_processed_once(app):
    with app.app_context():
        organiser, coordinator, _ = _people()
        event = _event(organiser, coordinator)
        change = _request(event, {"name": "Annual Summit"})
        process_routine_change(change.id, coordinator)
        event.name = "Edited afterwards"
        db.session.commit()
        history_before = EventChangeHistory.query.count()

        with pytest.raises(ChangeRequestError, match="already"):
            process_routine_change(change.id, coordinator)

        db.session.refresh(event)
        assert event.name == "Edited afterwards"  # not applied a second time
        assert EventChangeHistory.query.count() == history_before


def test_a_request_that_was_already_decided_is_refused(app):
    with app.app_context():
        organiser, coordinator, _ = _people()
        event = _event(organiser, coordinator)
        change = _request(event, {"name": "Annual Summit"})
        change.status = "rejected"
        db.session.commit()

        with pytest.raises(ChangeRequestError, match="already"):
            process_routine_change(change.id, coordinator)

        db.session.refresh(event)
        assert event.name == "Annual Conference"

def test_a_request_on_an_event_that_is_no_longer_changeable_is_refused(app):
    with app.app_context():
        organiser, coordinator, _ = _people()
        event = _event(organiser, coordinator)
        change = _request(event, {"name": "Annual Summit"})
        event.status = "cancelled"
        db.session.commit()

        with pytest.raises(ChangeRequestError, match="approved, planning or confirmed"):
            process_routine_change(change.id, coordinator)

        db.session.refresh(event)
        db.session.refresh(change)
        assert (event.name, change.status) == ("Annual Conference", "pending")


def test_a_field_that_already_has_the_proposed_value_leaves_no_history_row(app):
    with app.app_context():
        organiser, coordinator, _ = _people()
        event = _event(organiser, coordinator)
        change = _request(event, {"name": "Annual Summit", "description": "A bigger event"})
        event.name = "Annual Summit"  # already edited to the proposed value
        db.session.commit()

        process_routine_change(change.id, coordinator)

        rows = EventChangeHistory.query.filter_by(change_request_id=change.id).all()
        assert [r.field for r in rows] == ["description"]
        
# ---------------------------------------------------------------------
# Access
# ---------------------------------------------------------------------

def test_only_the_assigned_coordinator_can_process(app):
    with app.app_context():
        organiser, coordinator, other = _people()
        event = _event(organiser, coordinator)
        change = _request(event, {"name": "Annual Summit"})

        for user_id in (other, organiser):
            with pytest.raises(PermissionError, match="assigned"):
                process_routine_change(change.id, user_id)

        db.session.refresh(event)
        db.session.refresh(change)
        assert event.name == "Annual Conference"
        assert change.status == "pending"


def test_an_unknown_request_is_not_found(app):
    with app.app_context():
        _, coordinator, _ = _people()
        with pytest.raises(LookupError):
            process_routine_change(999999, coordinator)


# ---------------------------------------------------------------------
# HTTP: POST /api/change-requests/<id>/process
# ---------------------------------------------------------------------

def _scene(app):
    """An organiser, two coordinators, and a routine then a significant request."""
    with app.app_context():
        organiser, coordinator, other = _people()
        event = _event(organiser, coordinator)
        routine = _request(event, {"name": "Annual Summit"})
        significant = _request(event, {"expected_attendance": 120})
        return {
            "event": event.id, "organiser": organiser, "coordinator": coordinator, "other": other,
            "routine": routine.id, "significant": significant.id,
        }


def _post(app, user_id=None, body=None, **values):
    with app.test_request_context():
        path = url_for("change_requests.process_change", **values)
    headers = {}
    if user_id:
        with app.app_context():
            user = db.session.get(User, user_id)
            token = create_access_token(
                identity=str(user_id),
                additional_claims={"roles": user.role_names(), "name": user.name},
            )
        headers = {"Authorization": f"Bearer {token}"}
    return app.test_client().post(path, json=body or {}, headers=headers)


def _event_name(app, event_id):
    with app.app_context():
        return db.session.get(Event, event_id).name


def _status(app, request_id):
    with app.app_context():
        return db.session.get(ChangeRequest, request_id).status


def test_processing_asks_for_confirmation_first_and_changes_nothing(app):
    scene = _scene(app)

    response = _post(app, scene["coordinator"], request_id=scene["routine"])

    assert response.status_code == 409
    body = response.get_json()
    assert body["requiresConfirmation"] is True
    assert body["message"]
    assert _event_name(app, scene["event"]) == "Annual Conference"
    assert _status(app, scene["routine"]) == "pending"


@pytest.mark.parametrize("confirmed", [False, None, "true", 1])
def test_only_a_literal_true_counts_as_confirmation(app, confirmed):
    scene = _scene(app)

    response = _post(app, scene["coordinator"], body={"confirmed": confirmed}, request_id=scene["routine"])

    assert response.status_code == 409
    assert _event_name(app, scene["event"]) == "Annual Conference"


def test_confirming_applies_the_change(app):
    scene = _scene(app)

    response = _post(app, scene["coordinator"], body={"confirmed": True}, request_id=scene["routine"])

    assert response.status_code == 200
    assert response.get_json()["status"] == "processed"
    assert _event_name(app, scene["event"]) == "Annual Summit"


def test_a_significant_request_is_refused_without_asking_for_confirmation(app):
    scene = _scene(app)

    response = _post(app, scene["coordinator"], request_id=scene["significant"])  # not confirmed

    assert response.status_code == 400
    assert "re-review" in response.get_data(as_text=True)


def test_values_that_no_longer_pass_are_reported_by_field(app):
    scene = _scene(app)
    with app.app_context():
        event = db.session.get(Event, scene["event"])
        bad = _stored_request(event, {"name": {"from": "Annual Conference", "to": "  "}})
        bad_id = bad.id

    response = _post(app, scene["coordinator"], body={"confirmed": True}, request_id=bad_id)

    assert response.status_code == 400
    assert "name" in response.get_json()["errors"]
    assert _event_name(app, scene["event"]) == "Annual Conference"


def test_a_second_attempt_is_refused(app):
    scene = _scene(app)
    body = {"confirmed": True}

    first = _post(app, scene["coordinator"], body=body, request_id=scene["routine"])
    second = _post(app, scene["coordinator"], body=body, request_id=scene["routine"])

    assert (first.status_code, second.status_code) == (200, 400)
    assert "already" in second.get_data(as_text=True)


def test_only_the_assigned_coordinator_can_process_over_http(app):
    scene = _scene(app)
    body = {"confirmed": True}

    assert _post(app, scene["other"], body=body, request_id=scene["routine"]).status_code == 403
    assert _post(app, scene["organiser"], body=body, request_id=scene["routine"]).status_code == 403
    assert _post(app, None, body=body, request_id=scene["routine"]).status_code == 401
    assert _post(app, scene["coordinator"], body=body, request_id=999999).status_code == 404
    assert _event_name(app, scene["event"]) == "Annual Conference"