import json

import pytest

from app.extensions import db
from app.models.event import Event, EventFieldEditLog

EDITABLE_STATUSES = ["under_review", "approved", "planning", "safety_check"]


def new_event(make_event, organiser, coordinator, status="planning"):
    return make_event(organiser, status=status, coordinator_id=coordinator)


def put_lines(client, headers, event_id, lines, confirmed=True):
    return client.put(
        f"/api/events/{event_id}/update", headers=headers,
        json={"fields": {"equipment_requirements": lines}, "offlineReviewConfirmed": confirmed})


def saved_lines(event_id):
    db.session.expire_all()
    return db.session.get(Event, event_id).equipment_requirements


@pytest.mark.parametrize("status", EDITABLE_STATUSES)
def test_ac1_assigned_coordinator_saves_a_line_and_it_appears(
        client, auth_header, organiser, coordinator, make_event, status):
    event_id = new_event(make_event, organiser, coordinator, status)
    headers = auth_header("coordinator@test.com")
    res = put_lines(client, headers, event_id, [{"type": "Projector", "quantity": 2}])
    assert res.status_code == 200, res.get_json()
    lines = saved_lines(event_id)
    assert [(item.equipment_type, item.quantity, item.status) for item in lines] == [("Projector", 2, "requested")]
    shown = client.get(f"/api/events/{event_id}", headers=headers).get_json()
    assert "Projector" in json.dumps(shown) and "requested" in json.dumps(shown)


@pytest.mark.parametrize("line, field", [
    ({"quantity": 2}, "type"),
    ({"type": "   ", "quantity": 2}, "type"),
    ({"type": "Projector", "quantity": 0}, "quantity"),
    ({"type": "Projector", "quantity": -3}, "quantity"),
    ({"type": "Projector", "quantity": 1.5}, "quantity"),
])
def test_ac2_invalid_line_returns_400_naming_the_field_and_saves_nothing(
        client, auth_header, organiser, coordinator, make_event, line, field):
    event_id = new_event(make_event, organiser, coordinator)
    res = put_lines(client, auth_header("coordinator@test.com"), event_id, [line])
    assert res.status_code == 400
    assert any(field in key for key in res.get_json()["errors"])
    assert saved_lines(event_id) == []


def test_ac3_technical_requirements_are_returned_unchanged(
        client, auth_header, organiser, coordinator, make_event):
    event_id = new_event(make_event, organiser, coordinator)
    headers = auth_header("coordinator@test.com")
    text = "Needs 2 x HDMI, 5m cable; stage left!"
    put_lines(client, headers, event_id, [{"type": "Projector", "quantity": 1, "technicalNotes": text}])
    shown = client.get(f"/api/events/{event_id}", headers=headers).get_json()
    assert text in json.dumps(shown)


def test_ac4_unassigned_coordinator_gets_403_and_nothing_changes(
        client, auth_header, make_user, organiser, coordinator, make_event):
    make_user("other-coord@test.com", ["event_coordinator"], name="Other Coord")
    event_id = new_event(make_event, organiser, coordinator)
    res = put_lines(client, auth_header("other-coord@test.com"), event_id,
                    [{"type": "Projector", "quantity": 1}])
    assert res.status_code == 403
    assert saved_lines(event_id) == []


def test_ac4_non_coordinator_roles_get_403(client, auth_header, organiser, coordinator, make_event):
    event_id = new_event(make_event, organiser, coordinator)
    res = put_lines(client, auth_header("organiser@test.com"), event_id,
                    [{"type": "Projector", "quantity": 1}])
    assert res.status_code == 403
    assert saved_lines(event_id) == []


def test_ac5_confirmed_event_returns_423_and_the_attempt_is_logged(
        client, auth_header, organiser, coordinator, make_event):
    event_id = new_event(make_event, organiser, coordinator, "confirmed")
    res = put_lines(client, auth_header("coordinator@test.com"), event_id,
                    [{"type": "Projector", "quantity": 1}])
    assert res.status_code == 423
    assert saved_lines(event_id) == []
    logs = EventFieldEditLog.query.filter_by(event_id=event_id).all()
    assert len(logs) == 1 and logs[0].was_rejected is True


def test_ac6_unconfirmed_offline_review_returns_400_and_saves_nothing(
        client, auth_header, organiser, coordinator, make_event):
    event_id = new_event(make_event, organiser, coordinator)
    res = put_lines(client, auth_header("coordinator@test.com"), event_id,
                    [{"type": "Projector", "quantity": 1}], confirmed=False)
    assert res.status_code == 400
    assert saved_lines(event_id) == []


def test_ac7_edit_log_records_the_equipment_change(
        client, auth_header, organiser, coordinator, make_event):
    event_id = new_event(make_event, organiser, coordinator)
    headers = auth_header("coordinator@test.com")
    put_lines(client, headers, event_id, [{"type": "Microphone", "quantity": 4, "technicalNotes": "Wireless"}])
    shown = client.get(f"/api/events/{event_id}", headers=headers).get_json()
    entries = shown["fieldEditLogs"]
    assert len(entries) == 1
    assert "equipment_requirements" in entries[0]["newValues"]
    assert entries[0]["wasSignificant"] is True
    assert "Microphone" in json.dumps(shown) and "Wireless" in json.dumps(shown)