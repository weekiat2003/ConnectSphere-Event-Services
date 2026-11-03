from datetime import timedelta

import pytest

from app.common.time import utcnow
from app.extensions import db
from app.models.equipment import EquipmentItem, EquipmentReservation
from app.models.event import Event, EventEquipmentRequirement

BASE = "/api/equipment/items"


@pytest.fixture
def tech_headers(make_user, auth_header):
    make_user("tech-retire@test.com", ["technical_support_staff"])
    return auth_header("tech-retire@test.com")


@pytest.fixture
def item_id(app):
    item = EquipmentItem(name="Projector", total_quantity=10)
    db.session.add(item)
    db.session.commit()
    return item.id


def create_event_with_requirement(organiser, make_event, item_id):
    event_id = make_event(organiser, name="Retirement Test Event")
    event = db.session.get(Event, event_id)
    requirement = EventEquipmentRequirement(
        event_id=event_id, equipment_type="Projector", quantity=2
    )
    db.session.add(requirement)
    db.session.commit()
    return event, requirement


def create_reservation(event, item_id, requirement, start, end, status="reserved"):
    record = EquipmentReservation(
        event_id=event.id,
        equipment_requirement_id=requirement.id,
        equipment_item_id=item_id,
        quantity=2,
        start_datetime=start,
        end_datetime=end,
        status=status,
    )
    db.session.add(record)
    db.session.commit()
    return record


def retire(client, headers, item_id):
    return client.post(f"{BASE}/{item_id}/retire", headers=headers)


def restore(client, headers, item_id):
    return client.post(f"{BASE}/{item_id}/restore", headers=headers)


def fresh_item(item_id):
    db.session.expire_all()
    return db.session.get(EquipmentItem, item_id)


def test_retire_succeeds_and_preserves_requirements_and_historical_reservations(
    client, tech_headers, item_id, organiser, make_event
):
    event, requirement = create_event_with_requirement(organiser, make_event, item_id)
    now = utcnow().replace(tzinfo=None)
    released = create_reservation(
        event, item_id, requirement, now + timedelta(days=2),
        now + timedelta(days=2, hours=1), status="released",
    )
    past = create_reservation(
        event, item_id, requirement, now - timedelta(days=2),
        now - timedelta(days=2, hours=-1),
    )

    response = retire(client, tech_headers, item_id)

    assert response.status_code == 200
    assert response.get_json() == {
        "id": item_id,
        "name": "Projector",
        "category": None,
        "totalQuantity": 10,
        "status": "retired",
    }
    assert fresh_item(item_id).status == "retired"
    assert db.session.get(EventEquipmentRequirement, requirement.id) is not None
    assert db.session.get(EquipmentReservation, released.id).status == "released"
    assert db.session.get(EquipmentReservation, past.id).status == "reserved"


@pytest.mark.parametrize("period", ["current", "future"])
def test_active_or_future_reservation_blocks_retirement_without_changing_status(
    client, tech_headers, item_id, organiser, make_event, period
):
    event, requirement = create_event_with_requirement(organiser, make_event, item_id)
    now = utcnow().replace(tzinfo=None)
    if period == "current":
        start, end = now - timedelta(hours=1), now + timedelta(hours=1)
    else:
        start, end = now + timedelta(days=3), now + timedelta(days=3, hours=1)
    reservation = create_reservation(event, item_id, requirement, start, end)

    response = retire(client, tech_headers, item_id)
    body = response.get_json()

    assert response.status_code == 409
    assert body["error"]
    assert body["itemId"] == item_id
    assert body["itemName"] == "Projector"
    assert body["affectedReservations"] == [{
        "id": reservation.id,
        "eventId": event.id,
        "equipmentItemId": item_id,
        "quantity": 2,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "status": "reserved",
        "eventName": "Retirement Test Event",
    }]
    assert fresh_item(item_id).status == "active"


@pytest.mark.parametrize(
    "method,path,payload",
    [
        ("put", "", {"totalQuantity": 4}),
        ("post", "/mark-unavailable", {"reason": "damaged"}),
        ("post", "/mark-active", {}),
    ],
)
def test_retired_item_rejects_catalogue_mutations(
    client, tech_headers, item_id, method, path, payload
):
    db.session.get(EquipmentItem, item_id).status = "retired"
    db.session.commit()
    request_method = getattr(client, method)

    response = request_method(
        f"{BASE}/{item_id}{path}", json=payload, headers=tech_headers
    )

    assert response.status_code == 400
    assert "retired" in response.get_json()["error"].lower()
    assert fresh_item(item_id).status == "retired"


@pytest.mark.parametrize(
    "email,roles",
    [
        ("retire-coordinator@test.com", ["event_coordinator"]),
        ("retire-organiser@test.com", ["event_organiser"]),
    ],
)
def test_non_technical_support_cannot_retire_item(
    client, make_user, auth_header, item_id, email, roles
):
    make_user(email, roles)

    response = retire(client, auth_header(email), item_id)

    assert response.status_code == 403
    assert fresh_item(item_id).status == "active"


def test_unauthenticated_user_cannot_retire_item(client, item_id):
    response = client.post(f"{BASE}/{item_id}/retire")

    assert response.status_code == 401
    assert fresh_item(item_id).status == "active"


def test_retired_item_name_cannot_be_added_again(
    client, tech_headers, item_id
):
    db.session.get(EquipmentItem, item_id).status = "retired"
    db.session.commit()

    response = client.post(
        BASE,
        json={"name": "Projector", "totalQuantity": 5},
        headers=tech_headers,
    )

    assert response.status_code == 400
    assert "including retired items" in response.get_json()["error"]
    assert EquipmentItem.query.filter_by(name="Projector").count() == 1


def test_restore_retired_item_makes_old_requirement_usable_again_without_reviving_reservations(
    client, tech_headers, item_id, organiser, make_event
):
    event, requirement = create_event_with_requirement(organiser, make_event, item_id)
    now = utcnow().replace(tzinfo=None)
    old_reservation = create_reservation(
        event, item_id, requirement, now + timedelta(days=2),
        now + timedelta(days=2, hours=1), status="released",
    )
    db.session.get(EquipmentItem, item_id).status = "retired"
    db.session.commit()
    reservations_before = EquipmentReservation.query.count()

    response = restore(client, tech_headers, item_id)

    assert response.status_code == 200
    assert response.get_json()["status"] == "active"
    assert fresh_item(item_id).status == "active"
    assert EquipmentReservation.query.count() == reservations_before
    assert db.session.get(EquipmentReservation, old_reservation.id).status == "released"
    assert db.session.get(EventEquipmentRequirement, requirement.id).equipment_type == "Projector"

    listed_items = client.get(BASE, headers=tech_headers).get_json()
    assert any(item["id"] == item_id and item["status"] == "active" for item in listed_items)
    availability = client.get(
        f"/api/equipment/events/{event.id}/availability"
        f"?start={(now + timedelta(days=4)).isoformat()}"
        f"&end={(now + timedelta(days=4, hours=1)).isoformat()}",
        headers=tech_headers,
    )
    assert availability.status_code == 200
    assert availability.get_json()["results"][0]["available"] is True


def test_restore_rejects_an_item_that_is_already_active(client, tech_headers, item_id):
    response = restore(client, tech_headers, item_id)

    assert response.status_code == 400
    assert "not retired" in response.get_json()["error"]
    assert fresh_item(item_id).status == "active"


@pytest.mark.parametrize(
    "email,roles",
    [
        ("restore-coordinator@test.com", ["event_coordinator"]),
        ("restore-organiser@test.com", ["event_organiser"]),
    ],
)
def test_non_technical_support_cannot_restore_retired_item(
    client, make_user, auth_header, item_id, email, roles
):
    make_user(email, roles)
    db.session.get(EquipmentItem, item_id).status = "retired"
    db.session.commit()

    response = restore(client, auth_header(email), item_id)

    assert response.status_code == 403
    assert fresh_item(item_id).status == "retired"


def test_unauthenticated_user_cannot_restore_retired_item(client, item_id):
    db.session.get(EquipmentItem, item_id).status = "retired"
    db.session.commit()

    response = restore(client, None, item_id)

    assert response.status_code == 401
    assert fresh_item(item_id).status == "retired"
