"""Coordinator Assignment: separate Lead and Coordinator responsibilities.

Bug-doc items covered:
- Coordinators can no longer reassign an event themselves (the old
  POST /events/<id>/reassign is gone). They ask a Lead, with a reason.
- Leads are notified of the request, then reassign it or decline it.
- Closed events (cancelled/rejected/completed) cannot be reassigned.
- The assignment queue shows each coordinator's number of ACTIVE events
  (under review through confirmed) and the event type.
- A Coordinator's calendar includes every event currently assigned to them.
"""
from datetime import date, timedelta

import pytest

from app.extensions import db
from app.models.event import CoordinatorReassignmentRequest, Event
from app.models.notification import (
    TYPE_COORDINATOR_ASSIGNMENT,
    TYPE_REASSIGNMENT_REQUEST,
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
        "lead2": make_user("lead2@test.com", ["event_coordinator_lead"], name="Leo Lead"),
        "coord_a": make_user("coord-a@test.com", ["event_coordinator"], name="Ada Coordinator"),
        "coord_b": make_user("coord-b@test.com", ["event_coordinator"], name="Ben Coordinator"),
    }


@pytest.fixture()
def submit(client, auth_header):
    def _submit(name="Gala Night", category="Social"):
        org = auth_header("organiser@test.com")
        draft = client.post("/api/events/drafts", headers=org, json={
            "name": name, "purpose": "Fundraising", "description": "Annual fundraising gala",
            "category": category, "proposed_date": FUTURE.isoformat(), "proposed_time": "19:00",
            "expected_attendance": 120, "capacity_needed": 140,
            "required_layout": "banquet", "accessibility_needs": "Step-free access",
        })
        assert draft.status_code in (200, 201), draft.get_json()
        event_id = draft.get_json()["id"]
        assert client.post(f"/api/events/{event_id}/submit", headers=org).status_code == 200
        return event_id
    return _submit


@pytest.fixture()
def assigned(client, auth_header, people, submit):
    """A submitted request assigned to Ada by a Lead (status Under Review)."""
    def _assigned(name="Gala Night"):
        event_id = submit(name=name)
        lead = auth_header("lead@test.com")
        res = client.post(f"/api/events/{event_id}/assign", headers=lead,
                          json={"coordinatorId": people["coord_a"], "confirmed": True})
        assert res.status_code == 200, res.get_json()
        return event_id
    return _assigned


def ask(client, auth_header, event_id, reason="On leave from next week", email="coord-a@test.com"):
    return client.post(f"/api/events/{event_id}/reassignment-request",
                       headers=auth_header(email), json={"reason": reason})


# --- Coordinators cannot reassign directly --------------------------------

def test_coordinator_cannot_reassign_directly(app, client, auth_header, people, assigned):
    event_id = assigned()
    res = client.post(f"/api/events/{event_id}/reassign", headers=auth_header("coord-a@test.com"),
                      json={"newCoordinatorId": people["coord_b"]})
    assert res.status_code in (404, 405)
    res = client.post(f"/api/events/{event_id}/lead-reassign", headers=auth_header("coord-a@test.com"),
                      json={"coordinatorId": people["coord_b"], "confirmed": True})
    assert res.status_code == 403
    assert db.session.get(Event, event_id).coordinator_id == people["coord_a"]


# --- Asking for reassignment ---------------------------------------------

def test_assigned_coordinator_can_ask_and_every_lead_is_notified(app, client, auth_header, people, assigned):
    event_id = assigned()
    res = ask(client, auth_header, event_id)
    assert res.status_code == 201, res.get_json()
    body = res.get_json()
    assert body["status"] == "pending" and body["requestedByName"] == "Ada Coordinator"

    for lead in ("lead", "lead2"):
        [n] = inbox(people[lead], TYPE_REASSIGNMENT_REQUEST)
        assert n.event_id == event_id
        assert "Ada Coordinator" in n.message and "On leave from next week" in n.message
        assert n.link == f"/assignments?event={event_id}"

    pending = client.get("/api/events/reassignment-requests", headers=auth_header("lead@test.com")).get_json()
    assert [r["eventId"] for r in pending] == [event_id]
    # Still assigned to Ada until a Lead decides.
    assert db.session.get(Event, event_id).coordinator_id == people["coord_a"]


@pytest.mark.parametrize("reason", ["", "   ", "!!!"])
def test_reason_is_required(app, client, auth_header, people, assigned, reason):
    event_id = assigned()
    assert ask(client, auth_header, event_id, reason=reason).status_code == 400
    assert CoordinatorReassignmentRequest.query.count() == 0


def test_only_the_assigned_coordinator_can_ask(app, client, auth_header, people, assigned):
    event_id = assigned()
    assert ask(client, auth_header, event_id, email="coord-b@test.com").status_code == 403
    assert ask(client, auth_header, event_id, email="lead@test.com").status_code == 403
    assert ask(client, auth_header, event_id, email="organiser@test.com").status_code == 403


def test_cannot_ask_twice_while_pending(app, client, auth_header, people, assigned):
    event_id = assigned()
    assert ask(client, auth_header, event_id).status_code == 201
    res = ask(client, auth_header, event_id, reason="Another reason")
    assert res.status_code == 400 and "already waiting" in res.get_json()["error"]


@pytest.mark.parametrize("status", ["cancelled", "rejected", "completed"])
def test_closed_events_cannot_be_reassigned(app, client, auth_header, people, assigned, status):
    event_id = assigned()
    event = db.session.get(Event, event_id)
    event.status = status
    db.session.commit()
    assert ask(client, auth_header, event_id).status_code == 400
    res = client.post(f"/api/events/{event_id}/lead-reassign", headers=auth_header("lead@test.com"),
                      json={"coordinatorId": people["coord_b"], "confirmed": True})
    assert res.status_code == 400


# --- Lead decisions --------------------------------------------------------

def test_lead_reassign_completes_the_request_and_clears_lead_notices(app, client, auth_header, people, assigned):
    event_id = assigned()
    ask(client, auth_header, event_id)
    res = client.post(f"/api/events/{event_id}/lead-reassign", headers=auth_header("lead@test.com"),
                      json={"coordinatorId": people["coord_b"], "confirmed": True})
    assert res.status_code == 200, res.get_json()

    req = CoordinatorReassignmentRequest.query.one()
    assert req.status == "completed" and req.decided_by == people["lead"]
    assert client.get("/api/events/reassignment-requests", headers=auth_header("lead@test.com")).get_json() == []
    for lead in ("lead", "lead2"):
        assert all(n.cleared_at is not None for n in inbox(people[lead], TYPE_REASSIGNMENT_REQUEST))
    # Ada hears she was reassigned away; Ben that it is now his.
    assert inbox(people["coord_a"], TYPE_COORDINATOR_ASSIGNMENT)[-1].data["kind"] == "removed"
    assert inbox(people["coord_b"], TYPE_COORDINATOR_ASSIGNMENT)[-1].data["kind"] == "reassigned"


def test_lead_can_decline_and_coordinator_is_told_why(app, client, auth_header, people, assigned):
    event_id = assigned()
    ask(client, auth_header, event_id)
    res = client.post(f"/api/events/{event_id}/reassignment-request/decline",
                      headers=auth_header("lead2@test.com"), json={"note": "Ben is fully booked"})
    assert res.status_code == 200, res.get_json()
    assert res.get_json()["status"] == "declined"

    [n] = inbox(people["coord_a"], TYPE_REASSIGNMENT_REQUEST)
    assert n.title == "Reassignment request declined" and n.cleared_at is None
    assert "Leo Lead" in n.message and "Ben is fully booked" in n.message
    assert all(x.cleared_at is not None for x in inbox(people["lead"], TYPE_REASSIGNMENT_REQUEST))
    assert db.session.get(Event, event_id).coordinator_id == people["coord_a"]

    latest = client.get(f"/api/events/{event_id}/reassignment-request",
                        headers=auth_header("coord-a@test.com")).get_json()
    assert latest["status"] == "declined" and latest["decidedByName"] == "Leo Lead"
    # After a decline the Coordinator may ask again.
    assert ask(client, auth_header, event_id, reason="Still on leave").status_code == 201


def test_only_leads_can_decline_or_list(app, client, auth_header, people, assigned):
    event_id = assigned()
    ask(client, auth_header, event_id)
    coord = auth_header("coord-a@test.com")
    assert client.post(f"/api/events/{event_id}/reassignment-request/decline", headers=coord,
                       json={}).status_code == 403
    assert client.get("/api/events/reassignment-requests", headers=coord).status_code == 403


def test_coordinator_can_withdraw(app, client, auth_header, people, assigned):
    event_id = assigned()
    ask(client, auth_header, event_id)
    res = client.delete(f"/api/events/{event_id}/reassignment-request", headers=auth_header("coord-a@test.com"))
    assert res.status_code == 200 and res.get_json()["status"] == "withdrawn"
    assert client.get("/api/events/reassignment-requests", headers=auth_header("lead@test.com")).get_json() == []
    assert all(n.cleared_at is not None for n in inbox(people["lead"], TYPE_REASSIGNMENT_REQUEST))


def test_cancelling_the_event_closes_a_pending_request(app, client, auth_header, people, assigned):
    event_id = assigned()
    event = db.session.get(Event, event_id)
    event.status = "planning"
    db.session.commit()
    ask(client, auth_header, event_id)
    res = client.post(f"/api/events/{event_id}/cancel", headers=auth_header("coord-a@test.com"),
                      json={"reason": "Venue fell through", "confirmed": True})
    assert res.status_code == 200, res.get_json()
    assert CoordinatorReassignmentRequest.query.one().status == "closed"
    assert client.get("/api/events/reassignment-requests", headers=auth_header("lead@test.com")).get_json() == []


# --- Queue details (Lead story AC3 / AC4 / AC6) ---------------------------

def test_queue_shows_event_type(app, client, auth_header, people, submit):
    event_id = submit(category="Conference")
    [row] = [e for e in client.get("/api/events/unassigned", headers=auth_header("lead@test.com")).get_json()
             if e["id"] == event_id]
    assert row["category"] == "Conference"
    assert row["status"] == "submitted" and row["statusLabel"] == "Submitted"


def test_workload_counts_every_active_status(app, client, auth_header, people, assigned):
    ids = [assigned(name=f"Event {i}") for i in range(3)]
    for event_id, status in zip(ids, ("safety_check", "confirmed", "cancelled")):
        db.session.get(Event, event_id).status = status
    db.session.commit()

    coords = {c["name"]: c for c in client.get("/api/events/coordinators",
                                                headers=auth_header("lead@test.com")).get_json()}
    assert coords["Ada Coordinator"]["activeEvents"] == 2   # safety check + confirmed, not cancelled
    assert coords["Ben Coordinator"]["activeEvents"] == 0
    # Least busy is suggested first.
    first = client.get("/api/events/coordinators", headers=auth_header("lead@test.com")).get_json()[0]
    assert first["name"] == "Ben Coordinator"


def test_second_lead_is_told_who_got_it(app, client, auth_header, people, submit):
    event_id = submit()
    client.post(f"/api/events/{event_id}/assign", headers=auth_header("lead@test.com"),
                json={"coordinatorId": people["coord_a"], "confirmed": True})
    res = client.post(f"/api/events/{event_id}/assign", headers=auth_header("lead2@test.com"),
                      json={"coordinatorId": people["coord_b"], "confirmed": True})
    assert res.status_code == 409
    assert res.get_json()["assignedTo"] == "Ada Coordinator"


# --- Lead calendar data & Coordinator calendar ----------------------------

def test_lead_sees_all_events_with_coordinator_and_status(app, client, auth_header, people, submit, assigned):
    unassigned_id = submit(name="Waiting")
    assigned_id = assigned(name="Taken")
    rows = {e["id"]: e for e in client.get("/api/events", headers=auth_header("lead@test.com")).get_json()}
    assert rows[unassigned_id]["coordinatorId"] is None
    assert rows[assigned_id]["coordinatorName"] == "Ada Coordinator"
    assert rows[assigned_id]["statusLabel"] == "Under review"


def test_coordinator_calendar_includes_events_without_history(app, client, auth_header, people, make_event):
    event_id = make_event(people["organiser"], status="planning", coordinator_id=people["coord_a"])
    rows = client.get("/api/events/calendar", headers=auth_header("coord-a@test.com")).get_json()
    assert [(r["id"], r["isReadOnly"]) for r in rows] == [(event_id, False)]
    assert client.get("/api/events/calendar", headers=auth_header("lead@test.com")).status_code == 403
