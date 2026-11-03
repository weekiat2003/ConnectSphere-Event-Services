from datetime import datetime

import pytest

from app.events.services import status as status_service
from app.extensions import db
from app.models.event import Event, EventEquipmentRequirement
from app.models.equipment import EquipmentItem, EquipmentReservation
from app.models.notification import TYPE_EQUIPMENT_RESERVATION_UPDATE, Notification
from app.models.user import User
from app.models.venue import Venue, VenueBooking


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


def make_planning_event(organiser, coordinator, make_event):
    event_id = make_event(
        organiser, status="planning", coordinator_id=coordinator, capacity_needed=100
    )
    event = db.session.get(Event, event_id)
    venue = Venue(name=f"Ready venue {event_id}", capacity=150)
    db.session.add(venue)
    db.session.flush()
    db.session.add(VenueBooking(
        event_id=event.id,
        venue_id=venue.id,
        requested_by=coordinator,
        status="approved",
        start_datetime=datetime(2026, 12, 1, 10),
        end_datetime=datetime(2026, 12, 1, 12),
    ))
    db.session.commit()
    return event


def add_reserved_requirement(event, equipment_type="Projector", quantity=2, needs_recheck=False):
    requirement = EventEquipmentRequirement(
        event_id=event.id,
        equipment_type=equipment_type,
        quantity=quantity,
        status="confirmed",
        needs_recheck=needs_recheck,
    )
    item = EquipmentItem(name=equipment_type, total_quantity=quantity)
    db.session.add_all([requirement, item])
    db.session.flush()
    db.session.add(EquipmentReservation(
        event_id=event.id,
        equipment_requirement_id=requirement.id,
        equipment_item_id=item.id,
        quantity=quantity,
        start_datetime=datetime(2026, 12, 1, 10),
        end_datetime=datetime(2026, 12, 1, 12),
        status="reserved",
    ))
    db.session.commit()
    return requirement, item


def test_confirm_recheck_clears_flag_and_notifies_coordinator(
    client, tech_headers, line, coordinator
):
    line.status = "confirmed"
    line.needs_recheck = True
    db.session.commit()
    res = client.post(
        f"/api/equipment/requirements/{line.id}/confirm-recheck",
        headers=tech_headers,
    )
    assert res.status_code == 200
    assert res.get_json()["needsRecheck"] is False
    assert "testingStatus" not in res.get_json()
    assert "installationStatus" not in res.get_json()
    notice = Notification.query.filter_by(
        recipient_id=coordinator,
        type=TYPE_EQUIPMENT_RESERVATION_UPDATE,
    ).one()
    assert notice.data == {
        "kind": "suitability_confirmed",
        "item": "Projector",
        "field": "needs_recheck",
        "new_value": False,
    }


def test_confirm_recheck_returns_forbidden_when_live_user_role_was_revoked(
    client, tech_headers, line
):
    line.status = "confirmed"
    line.needs_recheck = True
    user = User.query.filter_by(email="tech@test.com").one()
    user.roles = []
    db.session.commit()

    response = client.post(
        f"/api/equipment/requirements/{line.id}/confirm-recheck",
        headers=tech_headers,
    )

    assert response.status_code == 403
    assert response.get_json()["error"] == (
        "Only Technical Support Staff can confirm equipment suitability."
    )
    db.session.expire_all()
    assert db.session.get(EventEquipmentRequirement, line.id).needs_recheck is True


def test_confirm_recheck_for_missing_requirement_returns_not_found(
    client, tech_headers
):
    response = client.post(
        "/api/equipment/requirements/9999/confirm-recheck",
        headers=tech_headers,
    )

    assert response.status_code == 404
    assert response.get_json()["error"] == "Equipment requirement not found"


def test_flagged_reserved_requirement_blocks_safety_check(
    app, organiser, coordinator, make_event
):
    event = make_planning_event(organiser, coordinator, make_event)
    add_reserved_requirement(event, "Projector", needs_recheck=True)
    add_reserved_requirement(event, "Speaker")

    with pytest.raises(status_service.InvalidTransitionError):
        status_service.change_status(event, "safety_check", coordinator)

    db.session.expire_all()
    assert db.session.get(Event, event.id).status == "planning"


def test_requirement_without_reserved_status_blocks_safety_check(
    organiser, coordinator, make_event
):
    event = make_planning_event(organiser, coordinator, make_event)
    requirement, _ = add_reserved_requirement(event)
    requirement.status = "requested"
    db.session.commit()

    with pytest.raises(status_service.InvalidTransitionError):
        status_service.change_status(event, "safety_check", coordinator)

    db.session.expire_all()
    assert db.session.get(Event, event.id).status == "planning"


def test_unflagged_reserved_requirements_advance_without_preparation_statuses(
    organiser, coordinator, make_event
):
    event = make_planning_event(organiser, coordinator, make_event)
    requirements = [
        add_reserved_requirement(event, "Projector")[0],
        add_reserved_requirement(event, "Speaker")[0],
    ]

    assert all(requirement.status == "confirmed" for requirement in requirements)
    assert all(not requirement.needs_recheck for requirement in requirements)

    status_service.change_status(event, "safety_check", coordinator)

    db.session.expire_all()
    assert db.session.get(Event, event.id).status == "safety_check"


def test_confirming_last_flagged_requirement_advances_to_safety_check(
    client, tech_headers, organiser, coordinator, make_event
):
    event = make_planning_event(organiser, coordinator, make_event)
    requirement, _ = add_reserved_requirement(event, needs_recheck=True)

    response = client.post(
        f"/api/equipment/requirements/{requirement.id}/confirm-recheck",
        headers=tech_headers,
    )

    assert response.status_code == 200

    db.session.expire_all()
    saved_event = db.session.get(Event, event.id)

    saved_requirement = db.session.get(
        EventEquipmentRequirement, requirement.id
    )

    assert saved_requirement.needs_recheck is False
    assert saved_event.status == "planning"


def test_reserving_flagged_requested_requirement_advances_to_safety_check(
    client, tech_headers, organiser, coordinator, make_event
):
    event = make_planning_event(organiser, coordinator, make_event)
    requirement = EventEquipmentRequirement(
        event_id=event.id,
        equipment_type="Projector",
        quantity=2,
        needs_recheck=True,
    )
    item = EquipmentItem(name="Projector", total_quantity=2)
    db.session.add_all([requirement, item])
    db.session.commit()

    response = client.post(
        "/api/equipment/reservations",
        json={
            "eventId": event.id,
            "requirementId": requirement.id,
            "equipmentItemId": item.id,
            "start": "2026-12-01T10:00:00",
            "end": "2026-12-01T12:00:00",
        },
        headers=tech_headers,
    )

    assert response.status_code == 201

    db.session.expire_all()

    saved = db.session.get(EventEquipmentRequirement, requirement.id)
    saved_event = db.session.get(Event, event.id)

    assert saved.needs_recheck is False
    assert saved_event.status == "planning"


def test_event_without_equipment_rows_is_not_blocked_by_recheck_gate(
    organiser, coordinator, make_event
):
    event_id = make_event(organiser, status="planning", coordinator_id=coordinator)
    event = db.session.get(Event, event_id)

    status_service.change_status(event, "safety_check", coordinator)

    assert event.status == "safety_check"


@pytest.mark.parametrize(
    "status,needs_recheck,error",
    [
        ("confirmed", False, "not flagged"),
        ("requested", True, "Reserved"),
    ],
)
def test_confirm_recheck_refuses_invalid_state(
    client, tech_headers, line, status, needs_recheck, error
):
    line.status = status
    line.needs_recheck = needs_recheck
    db.session.commit()
    res = client.post(
        f"/api/equipment/requirements/{line.id}/confirm-recheck",
        headers=tech_headers,
    )
    assert res.status_code == 400
    assert error in res.get_json()["error"]
    db.session.expire_all()
    assert db.session.get(EventEquipmentRequirement, line.id).needs_recheck is needs_recheck


def test_confirm_recheck_is_technical_support_only(client, auth_header, line):
    line.status = "confirmed"
    line.needs_recheck = True
    db.session.commit()
    res = client.post(
        f"/api/equipment/requirements/{line.id}/confirm-recheck",
        headers=auth_header("coordinator@test.com"),
    )
    assert res.status_code == 403
    assert db.session.get(EventEquipmentRequirement, line.id).needs_recheck is True


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