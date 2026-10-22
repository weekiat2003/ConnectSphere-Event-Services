import pytest

from app.extensions import db
from app.models.event import EventEquipmentRequirement
from app.models.equipment import EquipmentItem


@pytest.fixture
def tech_headers(make_user, auth_header):
    make_user("tech@test.com", ["technical_support_staff"])
    return auth_header("tech@test.com")


@pytest.fixture
def line(organiser, coordinator, make_event):
    event_id = make_event(organiser, status="approved", coordinator_id=coordinator)
    row = EventEquipmentRequirement(event_id=event_id, equipment_type="Projector", quantity=2)
    db.session.add(row)
    db.session.commit()
    return row


def url(requirement_id):
    return f"/api/equipment/requirements/{requirement_id}/preparation"


def stored(line_id):
    db.session.expire_all()
    row = db.session.get(EventEquipmentRequirement, line_id)
    return row.testing_status, row.installation_status


def test_sets_testing_and_installation_and_returns_them(client, tech_headers, line):
    res = client.put(url(line.id), json={"testing_status": "in_progress", "installation_status": "done"},
                     headers=tech_headers)
    assert res.status_code == 200
    body = res.get_json()
    assert (body["testingStatus"], body["installationStatus"]) == ("in_progress", "done")
    assert stored(line.id) == ("in_progress", "done")


def test_invalid_status_returns_400_and_changes_nothing(client, tech_headers, line):
    res = client.put(url(line.id), json={"testing_status": "finished"}, headers=tech_headers)
    assert res.status_code == 400
    assert stored(line.id) == ("pending", "pending")


@pytest.mark.parametrize("body", [{}, {"quantity": 5}])
def test_empty_body_or_unknown_field_returns_400(client, tech_headers, line, body):
    assert client.put(url(line.id), json=body, headers=tech_headers).status_code == 400


@pytest.mark.parametrize("email, role", [
    ("coordinator@test.com", None),
    ("organiser@test.com", None),
])
def test_coordinator_and_organiser_get_403_and_nothing_changes(client, auth_header, line, email, role):
    res = client.put(url(line.id), json={"testing_status": "done"}, headers=auth_header(email))
    assert res.status_code == 403
    assert stored(line.id) == ("pending", "pending")


def test_unauthenticated_gets_401(client, line):
    assert client.put(url(line.id), json={"testing_status": "done"}).status_code == 401
    assert stored(line.id) == ("pending", "pending")


def test_unknown_requirement_returns_404(client, tech_headers):
    res = client.put(url(99999), json={"testing_status": "done"}, headers=tech_headers)
    assert res.status_code == 404
    assert res.get_json()["error"] == "Equipment requirement not found"


def test_coordinator_sees_the_latest_preparation_status(client, tech_headers, auth_header, line):
    client.put(url(line.id), json={"testing_status": "done"}, headers=tech_headers)
    res = client.get(f"/api/events/{line.event_id}", headers=auth_header("coordinator@test.com"))
    assert res.status_code == 200
    assert res.get_json()["equipmentRequirements"][0]["testingStatus"] == "done"

def test_item_can_be_reserved_again_after_being_marked_active(client, tech_headers, line):
    item = EquipmentItem(name="Projector", total_quantity=10)
    db.session.add(item)
    db.session.commit()
    body = {"eventId": line.event_id, "requirementId": line.id, "equipmentItemId": item.id,
            "start": "2026-12-01T10:00:00", "end": "2026-12-01T11:00:00"}

    res = client.post(f"/api/equipment/items/{item.id}/mark-unavailable",
                      json={"reason": "damaged"}, headers=tech_headers)
    assert res.status_code == 200
    assert client.post("/api/equipment/reservations", json=body, headers=tech_headers).status_code == 400

    assert client.post(f"/api/equipment/items/{item.id}/mark-active", headers=tech_headers).status_code == 200
    assert client.post("/api/equipment/reservations", json=body, headers=tech_headers).status_code == 201