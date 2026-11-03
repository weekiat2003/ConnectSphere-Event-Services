from datetime import date

import pytest

from app.events.services import update as updateservice
from app.events.services.update import (
    EventLockedError,
    EventValidationError,
    OfflineReviewNotConfirmedError,
)
from app.extensions import db
from app.models.event import Event, EventEquipmentRequirement, EventFieldEditLog
from app.models.user import User

def make(make_event, organiser, coordinator, status):
    return db.session.get(Event, make_event(organiser, status=status, coordinator_id=coordinator))


def add_line(event, coordinator, line, confirmed=True):
    return updateservice.update_event_fields(
        event, db.session.get(User, coordinator),
        {"equipment_requirements": [line]}, offline_review_confirmed=confirmed)


def test_ac1_assigned_coordinator_can_add_a_line_while_planning(
        app, organiser, coordinator, make_event):
    event = make(make_event, organiser, coordinator, "planning")
    add_line(event, coordinator, {"type": "Projector", "quantity": 2, "technicalNotes": "HDMI input"})
    db.session.expire_all()
    lines = db.session.get(Event, event.id).equipment_requirements
    assert len(lines) == 1
    assert lines[0].equipment_type == "Projector" and lines[0].quantity == 2
    assert lines[0].status == "requested"


def test_update_rejects_non_object_changes(app, organiser, coordinator, make_event):
    event = make(make_event, organiser, coordinator, "planning")
    user = db.session.get(User, coordinator)

    with pytest.raises(EventValidationError) as exc:
        updateservice.update_event_fields(event, user, None)

    assert exc.value.field_errors == {
        "fields": "Expected an object of fields to update"
    }


@pytest.mark.parametrize("status", ["under_review", "approved", "safety_check"])
def test_equipment_change_is_rejected_outside_planning(
        app, organiser, coordinator, make_event, status):
    event = make(make_event, organiser, coordinator, status)
    with pytest.raises(EventValidationError) as exc:
        add_line(event, coordinator, {"type": "Projector", "quantity": 2})
    assert exc.value.field_errors == {
        "equipment_requirements": (
            "Equipment can only be requested while the event is in Planning."
        )
    }
    db.session.rollback()
    assert db.session.get(Event, event.id).equipment_requirements == []


def test_unchanged_equipment_submission_is_allowed_outside_planning(
        app, organiser, coordinator, make_event):
    event = make(make_event, organiser, coordinator, "under_review")
    requirement = EventEquipmentRequirement(
        event_id=event.id, equipment_type="Projector", quantity=2
    )
    db.session.add(requirement)
    db.session.commit()

    add_line(
        event, coordinator,
        {"id": requirement.id, "type": "Projector", "quantity": 2},
    )

    db.session.expire_all()
    saved = db.session.get(Event, event.id)
    assert [(row.id, row.equipment_type, row.quantity) for row in saved.equipment_requirements] == [
        (requirement.id, "Projector", 2)
    ]
    assert EventFieldEditLog.query.filter_by(event_id=event.id).count() == 0


def test_equipment_update_accepts_snake_case_notes(app, organiser, coordinator, make_event):
    event = make(make_event, organiser, coordinator, "planning")
    requirement = EventEquipmentRequirement(
        event_id=event.id, equipment_type="Projector", quantity=2
    )
    db.session.add(requirement)
    db.session.commit()

    add_line(
        event, coordinator,
        {
            "id": requirement.id,
            "type": "Projector",
            "quantity": 2,
            "technical_notes": "Ceiling mount",
        },
    )

    db.session.expire_all()
    assert db.session.get(EventEquipmentRequirement, requirement.id).technical_notes == (
        "Ceiling mount"
    )


def test_equipment_update_rejects_non_object_requirement(app, organiser, coordinator, make_event):
    event = make(make_event, organiser, coordinator, "planning")

    with pytest.raises(EventValidationError) as exc:
        add_line(event, coordinator, None)

    assert exc.value.field_errors == {
        "equipment_requirements[0]": "Each equipment requirement must be an object"
    }


def test_equipment_update_rejects_id_from_another_event(app, organiser, coordinator, make_event):
    event = make(make_event, organiser, coordinator, "planning")

    with pytest.raises(EventValidationError) as exc:
        add_line(
            event, coordinator,
            {"id": 9999, "type": "Projector", "quantity": 1},
        )

    assert exc.value.field_errors == {
        "equipment_requirements[0].id": (
            "Equipment requirement does not belong to this event"
        )
    }


def test_optional_end_date_can_be_cleared(app, organiser, coordinator, make_event):
    event = make(
        make_event, organiser, coordinator, "planning",
    )
    event.proposed_end_date = date(2026, 12, 2)
    db.session.commit()

    updateservice.update_event_fields(
        event,
        db.session.get(User, coordinator),
        {"proposed_end_date": None},
        offline_review_confirmed=True,
    )

    db.session.expire_all()
    assert db.session.get(Event, event.id).proposed_end_date is None


def test_invalid_date_type_is_reported_as_validation_error(
        app, organiser, coordinator, make_event):
    event = make(make_event, organiser, coordinator, "planning")

    with pytest.raises(EventValidationError) as exc:
        updateservice.update_event_fields(
            event, db.session.get(User, coordinator), {"proposed_date": 42}
        )

    assert "must be a valid ISO value" in exc.value.field_errors["proposed_date"]


def test_date_update_requires_an_existing_or_submitted_time(
        app, organiser, coordinator, make_event):
    event = make(make_event, organiser, coordinator, "planning")
    event.proposed_date = None
    event.proposed_time = None
    db.session.commit()

    with pytest.raises(EventValidationError) as exc:
        updateservice.update_event_fields(
            event, db.session.get(User, coordinator), {"proposed_time": "10:00"}
        )

    assert exc.value.field_errors["proposed_date"] == "Proposed date is required"


def test_descriptive_fields_must_contain_a_word(app, organiser, coordinator, make_event):
    event = make(make_event, organiser, coordinator, "planning")
    original_name = event.name

    with pytest.raises(EventValidationError) as exc:
        updateservice.update_event_fields(
            event, db.session.get(User, coordinator), {"name": "123"}
        )

    assert "descriptive text" in exc.value.field_errors["name"]
    db.session.expire_all()
    assert db.session.get(Event, event.id).name == original_name


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