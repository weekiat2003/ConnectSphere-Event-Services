from datetime import datetime

import pytest

from app.extensions import db
from app.models.equipment import EquipmentItem, EquipmentReservation
from app.models.event import EventEquipmentRequirement

START = datetime(2026, 12, 1, 10, 0)
END = datetime(2026, 12, 1, 11, 0)


@pytest.fixture
def tech_headers(make_user, auth_header):
    make_user("tech@test.com", ["technical_support_staff"])
    return auth_header("tech@test.com")


@pytest.fixture
def event_id(organiser, make_event):
    return make_event(organiser, status="approved")


def url(event_id):
    return f"/api/equipment/events/{event_id}/requirements"


def add_requirement(event_id, type_="Projector", quantity=2, **extra):
    line = EventEquipmentRequirement(
        event_id=event_id, equipment_type=type_, quantity=quantity, **extra)
    db.session.add(line)
    db.session.commit()
    return line


def test_lists_every_requirement_with_its_details(client, tech_headers, event_id):
    add_requirement(event_id, "Projector", 2, technical_notes="HDMI input")
    add_requirement(event_id, "Microphone", 4)
    res = client.get(url(event_id), headers=tech_headers)
    assert res.status_code == 200
    rows = res.get_json()["requirements"]
    assert [(r["type"], r["quantity"]) for r in rows] == [("Projector", 2), ("Microphone", 4)]
    assert rows[0]["technicalNotes"] == "HDMI input"
    assert rows[0]["status"] == "requested"


def test_event_with_no_requirements_returns_an_empty_list(client, tech_headers, event_id):
    res = client.get(url(event_id), headers=tech_headers)
    assert res.status_code == 200
    assert res.get_json()["requirements"] == []


def test_shows_testing_installation_and_recheck_flag(client, tech_headers, event_id):
    add_requirement(event_id, testing_status="done", installation_status="in_progress",
                    needs_recheck=True)
    row = client.get(url(event_id), headers=tech_headers).get_json()["requirements"][0]
    assert row["testingStatus"] == "done"
    assert row["installationStatus"] == "in_progress"
    assert row["needsRecheck"] is True


def test_reserved_requirement_shows_quantity_and_period(client, tech_headers, event_id):
    item = EquipmentItem(name="Projector", total_quantity=10)
    db.session.add(item)
    line = add_requirement(event_id, "Projector", 4)
    db.session.add(EquipmentReservation(
        event_id=event_id, equipment_requirement_id=line.id, equipment_item_id=item.id,
        quantity=4, start_datetime=START, end_datetime=END, status="reserved"))
    db.session.commit()
    row = client.get(url(event_id), headers=tech_headers).get_json()["requirements"][0]
    assert row["reservation"]["quantity"] == 4
    assert row["reservation"]["start"] == START.isoformat()
    assert row["reservation"]["end"] == END.isoformat()


def test_unreserved_requirement_has_no_reservation(client, tech_headers, event_id):
    add_requirement(event_id)
    row = client.get(url(event_id), headers=tech_headers).get_json()["requirements"][0]
    assert row["reservation"] is None


@pytest.mark.parametrize("email, role", [
    ("organiser@test.com", "event_organiser"),
    ("att@test.com", "attendee"),
    ("coord2@test.com", "event_coordinator"),
])
def test_other_roles_get_403(client, make_user, auth_header, organiser, event_id, email, role):
    if email != "organiser@test.com":
        make_user(email, [role])
    res = client.get(url(event_id), headers=auth_header(email))
    assert res.status_code == 403


def test_unauthenticated_gets_401(client, event_id):
    assert client.get(url(event_id)).status_code == 401


def test_unknown_event_returns_404(client, tech_headers):
    res = client.get(url(99999), headers=tech_headers)
    assert res.status_code == 404
    assert res.get_json()["error"] == "Event not found"