"""Event Coordinator Lead — unassigned queue, assign / reassign, supervision.

User story: As an Event Coordinator Lead, I want newly submitted requests to
wait in an unassigned queue where I can assign or reassign a coordinator, so
that requests go to the right person. One test per acceptance criteria,
driven through the real HTTP API.
"""
from datetime import date, timedelta

import pytest

from app.extensions import db
from app.models.event import Event, EventCoordinatorHistory
from app.models.notification import (
    TYPE_COORDINATOR_ASSIGNMENT,
    TYPE_ORGANISER_UPDATE,
    Notification,
)

FUTURE = date.today() + timedelta(days=45)


def inbox(user_id, type_):
    return Notification.query.filter_by(recipient_id=user_id, type=type_).order_by(Notification.id).all()


@pytest.fixture()
def people(make_user, organiser):
    return {
        "organiser": organiser,
        "lead": make_user("lead@test.com", ["event_coordinator_lead"], name="Lena Lead"),
        "coord_a": make_user("coord-a@test.com", ["event_coordinator"], name="Ada Coordinator"),
        "coord_b": make_user("coord-b@test.com", ["event_coordinator"], name="Ben Coordinator"),
        "venue": make_user("venue@test.com", ["venue_staff"], name="Vic Venue"),
    }


@pytest.fixture()
def submit(client, auth_header):
    """Creates a draft as the organiser and submits it through the API."""
    def _submit(name="Gala Night", attendance=120):
        org = auth_header("organiser@test.com")
        draft = client.post("/api/events/drafts", headers=org, json={
            "name": name, "purpose": "Fundraising", "description": "Annual fundraising gala",
            "category": "Social", "proposed_date": FUTURE.isoformat(), "proposed_time": "19:00",
            "expected_attendance": attendance, "capacity_needed": attendance + 20,
            "required_layout": "banquet", "accessibility_needs": "Step-free access",
        })
        assert draft.status_code in (200, 201), draft.get_json()
        event_id = draft.get_json()["id"]
        res = client.post(f"/api/events/{event_id}/submit", headers=org)
        assert res.status_code == 200, res.get_json()
        return event_id
    return _submit


def lead_post(client, auth_header, path, coordinator_id):
    """Ask, then confirm — the same two-step flow the Lead UI uses."""
    lead = auth_header("lead@test.com")
    first = client.post(path, headers=lead, json={"coordinatorId": coordinator_id})
    assert first.status_code == 409 and first.get_json()["requiresConfirmation"], first.get_json()
    return client.post(path, headers=lead, json={"coordinatorId": coordinator_id, "confirmed": True})


def queue_ids(client, auth_header):
    res = client.get("/api/events/unassigned", headers=auth_header("lead@test.com"))
    assert res.status_code == 200
    return [e["id"] for e in res.get_json()]


# AC1 -----------------------------------------------------------------------
def test_ac1_submitted_request_is_unassigned_and_in_queue(app, client, auth_header, people, submit):
    event_id = submit()
    event = db.session.get(Event, event_id)
    assert event.status == "submitted"
    assert event.coordinator_id is None
    assert EventCoordinatorHistory.query.filter_by(event_id=event_id).count() == 0
    assert event_id in queue_ids(client, auth_header)


# AC2 -----------------------------------------------------------------------
def test_ac2_queue_shows_name_organiser_date_attendance_and_coordinators(
        app, client, auth_header, people, submit):
    event_id = submit(name="Charity Run", attendance=340)
    [row] = [e for e in client.get("/api/events/unassigned",
                                   headers=auth_header("lead@test.com")).get_json() if e["id"] == event_id]
    assert row["name"] == "Charity Run"
    assert row["organiserName"] == "Test Organiser"
    assert row["proposedDate"] == FUTURE.isoformat()
    assert row["expectedAttendance"] == 340

    coords = client.get("/api/events/coordinators", headers=auth_header("lead@test.com")).get_json()
    assert {c["name"] for c in coords} == {"Ada Coordinator", "Ben Coordinator"}
    assert all("openRequests" in c for c in coords)


# AC3 -----------------------------------------------------------------------
def test_ac3_assign_and_reassign_leave_queue_new_coordinator_sees_it_history_kept(
        app, client, auth_header, people, submit):
    event_id = submit()

    res = lead_post(client, auth_header, f"/api/events/{event_id}/assign", people["coord_a"])
    assert res.status_code == 200, res.get_json()
    assert res.get_json()["coordinatorId"] == people["coord_a"]
    assert event_id not in queue_ids(client, auth_header)
    mine = client.get("/api/events/assigned", headers=auth_header("coord-a@test.com")).get_json()
    assert event_id in [e["id"] for e in mine]

    res = lead_post(client, auth_header, f"/api/events/{event_id}/lead-reassign", people["coord_b"])
    assert res.status_code == 200, res.get_json()
    assert event_id not in queue_ids(client, auth_header)
    b_list = client.get("/api/events/assigned", headers=auth_header("coord-b@test.com")).get_json()
    a_list = client.get("/api/events/assigned", headers=auth_header("coord-a@test.com")).get_json()
    assert event_id in [e["id"] for e in b_list]
    assert event_id not in [e["id"] for e in a_list]

    history = client.get(f"/api/events/{event_id}/assignment-history",
                         headers=auth_header("lead@test.com")).get_json()
    assert [h["coordinatorName"] for h in history] == ["Ada Coordinator", "Ben Coordinator"]
    assert [h["assignmentType"] for h in history] == ["lead", "reassignment"]
    assert all(h["assignedByName"] == "Lena Lead" for h in history)
    assert history[0]["unassignedAt"] is not None and not history[0]["isCurrent"]
    assert history[1]["unassignedAt"] is None and history[1]["isCurrent"]


# AC4 -----------------------------------------------------------------------
def test_ac4_assignment_notifies_coordinator_and_organiser(app, client, auth_header, people, submit):
    event_id = submit()
    lead_post(client, auth_header, f"/api/events/{event_id}/assign", people["coord_a"])

    [n] = inbox(people["coord_a"], TYPE_COORDINATOR_ASSIGNMENT)
    assert n.event_id == event_id and n.data["kind"] == "assigned"
    org = [n for n in inbox(people["organiser"], TYPE_ORGANISER_UPDATE) if n.data["kind"] == "coordinator_assigned"]
    assert len(org) == 1 and "Ada Coordinator" in org[0].message


def test_ac4_reassignment_notifies_new_previous_and_organiser(app, client, auth_header, people, submit):
    event_id = submit()
    lead_post(client, auth_header, f"/api/events/{event_id}/assign", people["coord_a"])
    lead_post(client, auth_header, f"/api/events/{event_id}/lead-reassign", people["coord_b"])

    [new] = inbox(people["coord_b"], TYPE_COORDINATOR_ASSIGNMENT)
    assert new.data["kind"] == "reassigned"
    previous = inbox(people["coord_a"], TYPE_COORDINATOR_ASSIGNMENT)
    assert [n.data["kind"] for n in previous] == ["assigned", "removed"]
    org = [n for n in inbox(people["organiser"], TYPE_ORGANISER_UPDATE) if n.data["kind"] == "coordinator_reassigned"]
    assert len(org) == 1
    assert org[0].data["coordinatorName"] == "Ben Coordinator"
    assert org[0].data["previousCoordinatorName"] == "Ada Coordinator"


# AC5 -----------------------------------------------------------------------
@pytest.mark.parametrize("email", ["coord-a@test.com", "organiser@test.com", "venue@test.com"])
def test_ac5_non_lead_is_denied_queue_assign_and_supervision(app, client, auth_header, people, submit, email):
    event_id = submit()
    h = auth_header(email)
    body = {"coordinatorId": people["coord_a"], "confirmed": True}
    assert client.get("/api/events/unassigned", headers=h).status_code == 403
    assert client.get("/api/events/coordinators", headers=h).status_code == 403
    assert client.get("/api/events/supervision", headers=h).status_code == 403
    assert client.get(f"/api/events/{event_id}/assignment-history", headers=h).status_code == 403
    assert client.post(f"/api/events/{event_id}/assign", headers=h, json=body).status_code == 403
    assert client.post(f"/api/events/{event_id}/lead-reassign", headers=h, json=body).status_code == 403
    assert client.post(f"/api/events/{event_id}/auto-assign", headers=h).status_code == 403
    assert db.session.get(Event, event_id).coordinator_id is None


def test_ac5_unauthenticated_is_denied(app, client, people, submit):
    event_id = submit()
    assert client.get("/api/events/unassigned").status_code == 401
    assert client.get("/api/events/supervision").status_code == 401
    assert client.post(f"/api/events/{event_id}/assign", json={}).status_code == 401


# AC6 -----------------------------------------------------------------------
def test_ac6_supervision_lists_each_coordinator_with_active_events(app, client, auth_header, people, submit):
    e1 = submit(name="Gala Night")
    e2 = submit(name="Charity Run")
    e3 = submit(name="Old Event")
    for event_id, coord in ((e1, "coord_a"), (e2, "coord_a"), (e3, "coord_a")):
        lead_post(client, auth_header, f"/api/events/{event_id}/assign", people[coord])
    # A finished (cancelled) event is not active and must not be listed.
    event = db.session.get(Event, e3)
    event.status = "cancelled"
    db.session.commit()

    res = client.get("/api/events/supervision", headers=auth_header("lead@test.com"))
    assert res.status_code == 200
    rows = {r["name"]: r for r in res.get_json()}
    assert set(rows) == {"Ada Coordinator", "Ben Coordinator"}  # idle coordinators are listed too
    assert rows["Ada Coordinator"]["activeEventCount"] == 2
    assert {e["id"] for e in rows["Ada Coordinator"]["events"]} == {e1, e2}
    assert rows["Ben Coordinator"]["events"] == []
    sample = rows["Ada Coordinator"]["events"][0]
    assert {"name", "organiserName", "proposedDate", "expectedAttendance", "statusLabel"} <= set(sample)
