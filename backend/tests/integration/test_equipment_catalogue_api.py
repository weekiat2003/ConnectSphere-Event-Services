import pytest

from app.extensions import db
from app.models.equipment import EquipmentItem


BASE = "/api/equipment/items"


@pytest.fixture
def tech_headers(make_user, auth_header):
    make_user("catalogue-tech@test.com", ["technical_support_staff"])
    return auth_header("catalogue-tech@test.com")


@pytest.fixture
def item_id(app):
    item = EquipmentItem(name="Projector", category="Audio visual", total_quantity=8)
    db.session.add(item)
    db.session.commit()
    return item.id


def test_create_item_returns_and_persists_catalogue_item(client, tech_headers):
    response = client.post(
        BASE,
        json={"name": "Wireless Microphone", "category": "Audio", "totalQuantity": 4},
        headers=tech_headers,
    )

    assert response.status_code == 201
    body = response.get_json()
    assert body["name"] == "Wireless Microphone"
    assert body["category"] == "Audio"
    assert body["totalQuantity"] == 4
    assert body["status"] == "active"
    saved = db.session.get(EquipmentItem, body["id"])
    assert (saved.name, saved.category, saved.total_quantity, saved.status) == (
        "Wireless Microphone", "Audio", 4, "active"
    )


@pytest.mark.parametrize(
    "payload,error",
    [
        ({"name": "   ", "totalQuantity": 1}, "Equipment name is required"),
        ({"name": "Microphone"}, "totalQuantity must be zero or greater"),
        (
            {"name": "Microphone", "totalQuantity": -1},
            "totalQuantity must be zero or greater",
        ),
    ],
)
def test_create_item_rejects_empty_name_and_invalid_quantity(
    client, tech_headers, payload, error
):
    response = client.post(BASE, json=payload, headers=tech_headers)

    assert response.status_code == 400
    assert response.get_json()["error"] == error
    assert EquipmentItem.query.count() == 0


def test_update_missing_item_returns_not_found(client, tech_headers):
    response = client.put(
        f"{BASE}/9999",
        json={"name": "Updated", "category": "Audio", "totalQuantity": 3},
        headers=tech_headers,
    )

    assert response.status_code == 404
    assert response.get_json()["error"] == "Equipment item not found"


def test_update_item_changes_name_category_and_quantity(client, tech_headers, item_id):
    response = client.put(
        f"{BASE}/{item_id}",
        json={"name": "Ceiling Projector", "category": "Display", "totalQuantity": 12},
        headers=tech_headers,
    )

    assert response.status_code == 200
    assert response.get_json() == {
        "id": item_id,
        "name": "Ceiling Projector",
        "category": "Display",
        "totalQuantity": 12,
        "status": "active",
    }
    db.session.expire_all()
    saved = db.session.get(EquipmentItem, item_id)
    assert (saved.name, saved.category, saved.total_quantity) == (
        "Ceiling Projector", "Display", 12
    )
