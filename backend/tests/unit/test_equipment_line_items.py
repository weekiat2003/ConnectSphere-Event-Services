from datetime import datetime

import pytest

from app.events.services.update import (
    EventLockedError,
    EventNotEditableStatusError,
    EventValidationError,
    OfflineReviewNotConfirmedError,
    update_event_fields,
)
from app.extensions import db
from app.models.equipment import EquipmentItem, EquipmentReservation
from app.models.event import Event, EventEquipmentRequirement, EventFieldEditLog
from app.models.user import User

START = datetime(2026, 12, 1, 10, 0)
END = datetime(2026, 12, 1, 11, 0)


@pytest.fixture
def setup(app, organiser, coordinator, make_event):
    def _setup(status="approved", lines=()):
        event_id = make_event(organiser, status=status, coordinator_id=coordinator)
        for type_, quantity in lines:
            db.session.add(EventEquipmentRequirement(
                event_id=event_id, equipment_type=type_, quantity=quantity))
        db.session.commit()
        return db.session.get(Event, event_id), db.session.get(User, coordinator)
    return _setup


def lines(event_id):
    db.session.expire_all()
    rows = (EventEquipmentRequirement.query.filter_by(event_id=event_id)
            .order_by(EventEquipmentRequirement.id).all())
    return [(r.equipment_type, r.quantity) for r in rows]


def change(requirements):
    return {"equipment_requirements": requirements}


def reserve(event, line, status="reserved"):
    item = EquipmentItem(name=f"{line.equipment_type}-{line.id}", total_quantity=20)
    db.session.add(item)
    db.session.commit()
    booking = EquipmentReservation(
        event_id=event.id, equipment_requirement_id=line.id, equipment_item_id=item.id,
        quantity=line.quantity, start_datetime=START, end_datetime=END, status=status)
    db.session.add(booking)
    db.session.commit()
    return booking.id


def test_adds_a_line_that_shows_in_the_requirements(setup):
    event, coord = setup()
    update_event_fields(event, coord, change([{"type": "Projector", "quantity": 2}]),
                        offline_review_confirmed=True)
    assert lines(event.id) == [("Projector", 2)]


def test_removes_a_line_that_had_no_reservation(setup):
    event, coord = setup(lines=[("Projector", 2), ("Microphone", 1)])
    keep = event.equipment_requirements[0]
    update_event_fields(event, coord,
                        change([{"id": keep.id, "type": "Projector", "quantity": 2}]),
                        offline_review_confirmed=True)
    assert lines(event.id) == [("Projector", 2)]
    assert EquipmentReservation.query.count() == 0


def test_removing_a_line_releases_its_reservation(setup):
    event, coord = setup(lines=[("Projector", 2), ("Microphone", 1)])
    keep, removed = event.equipment_requirements
    booking_id = reserve(event, removed)
    update_event_fields(event, coord,
                        change([{"id": keep.id, "type": "Projector", "quantity": 2}]),
                        offline_review_confirmed=True)
    db.session.expire_all()
    assert db.session.get(EquipmentReservation, booking_id).status == "released"
    assert lines(event.id) == [("Projector", 2)]


def test_a_line_that_stays_keeps_its_reservation(setup):
    event, coord = setup(lines=[("Projector", 2), ("Microphone", 1)])
    keep, removed = event.equipment_requirements
    kept_booking = reserve(event, keep)
    update_event_fields(event, coord,
                        change([{"id": keep.id, "type": "Projector", "quantity": 2}]),
                        offline_review_confirmed=True)
    db.session.expire_all()
    assert db.session.get(EquipmentReservation, kept_booking).status == "reserved"


def test_an_already_released_reservation_is_left_alone(setup):
    event, coord = setup(lines=[("Projector", 2)])
    booking_id = reserve(event, event.equipment_requirements[0], status="released")
    update_event_fields(event, coord, change([]), offline_review_confirmed=True)
    db.session.expire_all()
    assert db.session.get(EquipmentReservation, booking_id).status == "released"
    assert lines(event.id) == []


def test_a_confirmed_event_refuses_the_change_and_logs_it(setup):
    event, coord = setup(status="confirmed", lines=[("Projector", 2)])
    with pytest.raises(EventLockedError):
        update_event_fields(event, coord, change([]), offline_review_confirmed=True)
    assert lines(event.id) == [("Projector", 2)]
    log = EventFieldEditLog.query.filter_by(event_id=event.id).one()
    assert log.was_rejected is True


def test_a_status_that_cannot_be_edited_returns_the_reason(setup):
    event, coord = setup(status="submitted")
    with pytest.raises(EventNotEditableStatusError, match="submitted"):
        update_event_fields(event, coord, change([{"type": "Projector", "quantity": 1}]),
                            offline_review_confirmed=True)
    assert lines(event.id) == []


def test_offline_review_must_be_confirmed(setup):
    event, coord = setup(lines=[("Microphone", 1)])
    with pytest.raises(OfflineReviewNotConfirmedError):
        update_event_fields(event, coord, change([]))
    assert lines(event.id) == [("Microphone", 1)]


@pytest.mark.parametrize("requirement, bad_key", [
    ({"type": "", "quantity": 1}, "type"),
    ({"type": "   ", "quantity": 1}, "type"),
    ({"type": "Projector", "quantity": 0}, "quantity"),
    ({"type": "Projector", "quantity": -3}, "quantity"),
    ({"type": "Projector", "quantity": "3"}, "quantity"),
    ({"type": "Projector"}, "quantity"),
])
def test_a_bad_line_names_the_field_and_saves_nothing(setup, requirement, bad_key):
    event, coord = setup(lines=[("Microphone", 1)])
    with pytest.raises(EventValidationError) as raised:
        update_event_fields(event, coord, change([requirement]), offline_review_confirmed=True)
    assert f"equipment_requirements[0].{bad_key}" in raised.value.field_errors
    assert lines(event.id) == [("Microphone", 1)]


def test_the_edit_log_records_the_old_and_new_lines(setup):
    event, coord = setup(lines=[("Microphone", 1)])
    existing = event.equipment_requirements[0]
    update_event_fields(
        event, coord,
        change([{"id": existing.id, "type": "Microphone", "quantity": 1},
                {"type": "Projector", "quantity": 2}]),
        offline_review_confirmed=True)
    log = EventFieldEditLog.query.filter_by(event_id=event.id).one()
    assert log.fields_changed == ["equipment_requirements"]
    assert [row["type"] for row in log.old_values["equipment_requirements"]] == ["Microphone"]
    assert [row["type"] for row in log.new_values["equipment_requirements"]] == ["Microphone", "Projector"]
    assert log.was_significant is True and log.was_rejected is False