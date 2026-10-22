from datetime import datetime

import pytest

from app.equipment.services.technical_review import get_event_requirements
from app.extensions import db
from app.models.equipment import EquipmentItem, EquipmentReservation
from app.models.event import EventEquipmentRequirement

START = datetime(2026, 12, 1, 10, 0)
END = datetime(2026, 12, 1, 11, 0)


@pytest.fixture
def event_id(organiser, make_event):
    return make_event(organiser, status="approved", name="Annual Summit")


def add_requirement(event_id, type_="Projector", quantity=2, **extra):
    line = EventEquipmentRequirement(
        event_id=event_id, equipment_type=type_, quantity=quantity, **extra)
    db.session.add(line)
    db.session.commit()
    return line


def add_reservation(event_id, line, status="reserved", quantity=None):
    item = EquipmentItem(name=f"{line.equipment_type}-{line.id}", total_quantity=20)
    db.session.add(item)
    db.session.commit()
    booking = EquipmentReservation(
        event_id=event_id, equipment_requirement_id=line.id, equipment_item_id=item.id,
        quantity=quantity or line.quantity, start_datetime=START, end_datetime=END,
        status=status)
    db.session.add(booking)
    db.session.commit()
    return booking


def test_returns_the_event_summary(event_id):
    result = get_event_requirements(event_id)
    assert result["eventId"] == event_id
    assert result["name"] == "Annual Summit"
    assert result["status"] == "approved"


def test_event_without_requirements_gives_an_empty_list(event_id):
    assert get_event_requirements(event_id)["requirements"] == []


def test_lists_every_requirement_in_order_with_its_details(event_id):
    add_requirement(event_id, "Projector", 2, technical_notes="HDMI input")
    add_requirement(event_id, "Microphone", 4)
    rows = get_event_requirements(event_id)["requirements"]
    assert [(r["type"], r["quantity"]) for r in rows] == [("Projector", 2), ("Microphone", 4)]
    assert rows[0]["technicalNotes"] == "HDMI input"
    assert rows[0]["status"] == "requested"


def test_includes_testing_installation_and_recheck_flag(event_id):
    add_requirement(event_id, testing_status="done", installation_status="in_progress",
                    needs_recheck=True)
    row = get_event_requirements(event_id)["requirements"][0]
    assert row["testingStatus"] == "done"
    assert row["installationStatus"] == "in_progress"
    assert row["needsRecheck"] is True


def test_active_reservation_shows_quantity_and_period(event_id):
    line = add_requirement(event_id, "Projector", 4)
    add_reservation(event_id, line)
    row = get_event_requirements(event_id)["requirements"][0]
    assert row["reservation"]["quantity"] == 4
    assert row["reservation"]["start"] == START.isoformat()
    assert row["reservation"]["end"] == END.isoformat()


def test_released_reservation_is_not_shown(event_id):
    line = add_requirement(event_id)
    add_reservation(event_id, line, status="released")
    assert get_event_requirements(event_id)["requirements"][0]["reservation"] is None


def test_unreserved_requirement_has_no_reservation(event_id):
    add_requirement(event_id)
    assert get_event_requirements(event_id)["requirements"][0]["reservation"] is None


def test_only_this_events_reservations_are_used(event_id, organiser, make_event):
    other_id = make_event(organiser, status="approved")
    line = add_requirement(event_id, "Projector", 2)
    other_line = add_requirement(other_id, "Projector", 3)
    add_reservation(other_id, other_line)
    row = get_event_requirements(event_id)["requirements"][0]
    assert row["id"] == line.id
    assert row["reservation"] is None


def test_unknown_event_raises_lookup_error(app):
    with pytest.raises(LookupError, match="Event not found"):
        get_event_requirements(99999)