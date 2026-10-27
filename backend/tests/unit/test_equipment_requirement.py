import pytest

from app.events.services import update as updateservice
from app.events.services.update import (
    EventLockedError,
    EventValidationError,
    OfflineReviewNotConfirmedError,
)
from app.extensions import db
from app.models.event import Event, EventFieldEditLog
from app.models.user import User

EDITABLE_STATUSES = ["under_review", "approved", "planning", "safety_check"]


def make(make_event, organiser, coordinator, status):
    return db.session.get(Event, make_event(organiser, status=status, coordinator_id=coordinator))


def add_line(event, coordinator, line, confirmed=True):
    return updateservice.update_event_fields(
        event, db.session.get(User, coordinator),
        {"equipment_requirements": [line]}, offline_review_confirmed=confirmed)


@pytest.mark.parametrize("status", EDITABLE_STATUSES)
def test_ac1_assigned_coordinator_can_add_a_line_in_editable_statuses(
        app, organiser, coordinator, make_event, status):
    event = make(make_event, organiser, coordinator, status)
    add_line(event, coordinator, {"type": "Projector", "quantity": 2, "technicalNotes": "HDMI input"})
    db.session.expire_all()
    lines = db.session.get(Event, event.id).equipment_requirements
    assert len(lines) == 1
    assert lines[0].equipment_type == "Projector" and lines[0].quantity == 2
    assert lines[0].status == "requested"


@pytest.mark.parametrize("line, field", [
    ({"quantity": 2}, "type"),
    ({"type": "   ", "quantity": 2}, "type"),
    ({"type": "Projector", "quantity": 0}, "quantity"),
    ({"type": "Projector", "quantity": -3}, "quantity"),
    ({"type": "Projector", "quantity": 1.5}, "quantity"),
    ({"type": "Projector", "quantity": "two"}, "quantity"),
])
def test_ac2_invalid_lines_name_the_field_and_save_nothing(
        app, organiser, coordinator, make_event, line, field):
    event = make(make_event, organiser, coordinator, "planning")
    with pytest.raises(EventValidationError) as exc:
        add_line(event, coordinator, line)
    assert any(field in key for key in exc.value.field_errors)
    db.session.rollback()
    assert db.session.get(Event, event.id).equipment_requirements == []


def test_ac3_technical_requirements_are_stored_unchanged(app, organiser, coordinator, make_event):
    event = make(make_event, organiser, coordinator, "planning")
    text = "  Needs 2 × HDMI, 5m cable; stage left!  "
    add_line(event, coordinator, {"type": "Projector", "quantity": 1, "technicalNotes": text})
    db.session.expire_all()
    line = db.session.get(Event, event.id).equipment_requirements[0]
    assert line.technical_notes == text


def test_ac4_unassigned_coordinator_gets_403_and_nothing_changes(
        app, organiser, coordinator, make_event, make_user):
    other = make_user("other-coord@test.com", ["event_coordinator"], name="Other Coord")
    event = make(make_event, organiser, coordinator, "planning")
    with pytest.raises(PermissionError):
        add_line(event, other, {"type": "Projector", "quantity": 1})
    db.session.rollback()
    assert db.session.get(Event, event.id).equipment_requirements == []


def test_ac5_confirmed_event_is_locked_and_the_attempt_is_logged(
        app, organiser, coordinator, make_event):
    event = make(make_event, organiser, coordinator, "confirmed")
    with pytest.raises(EventLockedError):
        add_line(event, coordinator, {"type": "Projector", "quantity": 1})
    db.session.rollback()
    assert db.session.get(Event, event.id).equipment_requirements == []
    log = EventFieldEditLog.query.filter_by(event_id=event.id).all()
    assert len(log) == 1 and log[0].was_rejected is True


def test_ac6_adding_equipment_needs_offline_review_confirmation(
        app, organiser, coordinator, make_event):
    event = make(make_event, organiser, coordinator, "planning")
    with pytest.raises(OfflineReviewNotConfirmedError):
        add_line(event, coordinator, {"type": "Projector", "quantity": 1}, confirmed=False)
    db.session.rollback()
    assert db.session.get(Event, event.id).equipment_requirements == []


def test_ac7_saved_line_is_returned_and_the_edit_is_logged(app, organiser, coordinator, make_event):
    event = make(make_event, organiser, coordinator, "planning")
    add_line(event, coordinator, {"type": "Microphone", "quantity": 4, "technicalNotes": "Wireless"})
    shown = updateservice._current_field_value(event, "equipment_requirements")
    assert shown[0]["type"] == "Microphone"
    assert shown[0]["quantity"] == 4
    assert shown[0]["technicalNotes"] == "Wireless"
    log = EventFieldEditLog.query.filter_by(event_id=event.id).all()
    assert len(log) == 1 and "equipment_requirements" in log[0].fields_changed