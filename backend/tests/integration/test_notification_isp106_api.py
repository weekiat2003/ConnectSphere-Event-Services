from app.events.services import review
from app.extensions import db
from app.models.event import Event, EventEquipmentRequirement


def test_technical_support_sees_the_notification_and_can_mark_it_read(
        client, auth_header, make_user, organiser, coordinator, make_event):
    make_user("tech@test.com", ["technical_support_staff"], name="Tia Tech")
    event = db.session.get(Event, make_event(organiser, status="under_review", coordinator_id=coordinator))
    event.equipment_requirements.append(EventEquipmentRequirement(equipment_type="Projector", quantity=2))
    db.session.commit()
    review.approve_event(event, coordinator)

    headers = auth_header("tech@test.com")
    items = client.get("/api/notifications", headers=headers).get_json()
    assert len(items) == 1
    assert items[0]["link"] == f"/technical-review?event={event.id}"
    assert items[0]["isRead"] is False
    assert client.get("/api/notifications/unread-count", headers=headers).get_json()["count"] == 1

    client.post(f"/api/notifications/{items[0]['id']}/read", headers=headers)
    assert client.get("/api/notifications/unread-count", headers=headers).get_json()["count"] == 0

    organiser_items = client.get("/api/notifications", headers=auth_header("organiser@test.com")).get_json()
    assert all(n["type"] != "new_equipment_request" for n in organiser_items)
    assert client.get("/api/notifications").status_code == 401