"""Operational Feasibility Check: what happens after the Safety Officer approves.

Approval moves the event out of Safety Check to Safety approved, which takes
it off the Safety Officer's review list and records who decided and when. The
Coordinator is notified and confirms it (Clarification Session 3), which moves
it to Confirmed.
"""
from datetime import datetime

from app.events.services.safety import SAFETY_FACTOR_ORDER
from app.extensions import db
from app.models.event import Event, EventStatusHistory
from app.models.notification import Notification
from app.models.venue import Venue, VenueBooking

OFFICER = "approve-officer@test.com"


def _event_in_safety_check(make_event, organiser, coordinator, **fields):
    event_id = make_event(organiser, status="safety_check", coordinator_id=coordinator, **fields)
    venue = Venue(name="Hall A", capacity=200)
    db.session.add(venue)
    db.session.commit()
    db.session.add(VenueBooking(
        event_id=event_id, venue_id=venue.id, requested_by=organiser, status="approved",
        start_datetime=datetime(2026, 12, 1, 9), end_datetime=datetime(2026, 12, 1, 12),
    ))
    db.session.commit()
    return event_id


def _approve(client, auth_header, event_id):
    factors = {key: {"outcome": "satisfactory", "notes": None} for key in SAFETY_FACTOR_ORDER}
    return client.post(
        f"/api/events/{event_id}/safety-review",
        headers=auth_header(OFFICER),
        json={"decision": "approved", "factorAssessments": factors},
    )


def test_approval_moves_event_out_of_safety_check(
    client, auth_header, organiser, coordinator, make_user, make_event
):
    make_user(OFFICER, ["safety_officer"])
    event_id = _event_in_safety_check(make_event, organiser, coordinator)

    before = client.get(f"/api/events/{event_id}", headers=auth_header("coordinator@test.com")).get_json()
    assert before["statusLabel"] == "Safety check"
    assert before["safetyApproved"] is False

    assert _approve(client, auth_header, event_id).status_code == 200

    after = client.get(f"/api/events/{event_id}", headers=auth_header("coordinator@test.com")).get_json()
    assert after["status"] == "safety_approved"
    assert after["statusLabel"] == "Safety approved"
    assert after["safetyApproved"] is True
    # AC1: the decision is recorded with the officer's name and the time.
    decision = after["safetyReviews"][-1]
    assert decision["decision"] == "approved"
    assert decision["safetyOfficerName"] == "approve-officer"
    assert decision["createdAt"]
    history = EventStatusHistory.query.filter_by(event_id=event_id).order_by(EventStatusHistory.id).all()
    assert (history[-1].old_status, history[-1].new_status) == ("safety_check", "safety_approved")


def test_approved_event_leaves_the_safety_review_list(
    client, auth_header, organiser, coordinator, make_user, make_event
):
    make_user(OFFICER, ["safety_officer"])
    approved = _event_in_safety_check(make_event, organiser, coordinator, name="Approved one")
    waiting = _event_in_safety_check(make_event, organiser, coordinator, name="Still waiting")
    assert _approve(client, auth_header, approved).status_code == 200

    body = client.get("/api/events/safety-reviews", headers=auth_header(OFFICER)).get_json()

    assert [e["id"] for e in body] == [waiting]


def test_coordinator_is_notified_to_confirm_after_approval(
    client, auth_header, organiser, coordinator, make_user, make_event
):
    make_user(OFFICER, ["safety_officer"], name="Officer Lim")
    event_id = _event_in_safety_check(make_event, organiser, coordinator, name="Gala")

    assert _approve(client, auth_header, event_id).status_code == 200

    notes = Notification.query.filter_by(recipient_id=coordinator, event_id=event_id).all()
    assert len(notes) == 1
    assert notes[0].title == "Safety check approved: confirm the event"
    assert "Officer Lim" in notes[0].message and "Confirm event" in notes[0].message


def test_coordinator_confirm_moves_event_to_confirmed(
    client, auth_header, organiser, coordinator, make_user, make_event
):
    make_user(OFFICER, ["safety_officer"])
    event_id = _event_in_safety_check(make_event, organiser, coordinator)
    assert _approve(client, auth_header, event_id).status_code == 200

    response = client.post(f"/api/events/{event_id}/confirm", headers=auth_header("coordinator@test.com"))

    assert response.status_code == 200, response.get_json()
    body = response.get_json()
    assert body["status"] == "confirmed"
    assert body["statusLabel"] == "Confirmed"
    assert body["safetyApproved"] is False
    assert db.session.get(Event, event_id).status == "confirmed"


def test_rejected_event_is_not_labelled_safety_approved(
    client, auth_header, organiser, coordinator, make_user, make_event
):
    make_user(OFFICER, ["safety_officer"])
    event_id = _event_in_safety_check(make_event, organiser, coordinator)
    factors = {key: {"outcome": "satisfactory", "notes": None} for key in SAFETY_FACTOR_ORDER}
    factors["crowd_movement"] = {"outcome": "concern", "notes": "Single exit"}

    response = client.post(
        f"/api/events/{event_id}/safety-review",
        headers=auth_header(OFFICER),
        json={"decision": "rejected", "comments": "Exit route is blocked",
              "affectedArrangements": ["venue"], "factorAssessments": factors},
    )

    assert response.status_code == 200, response.get_json()
    body = client.get(f"/api/events/{event_id}", headers=auth_header("coordinator@test.com")).get_json()
    assert body["status"] == "planning"
    assert body["statusLabel"] == "Planning"
    assert body["safetyApproved"] is False


def test_safety_review_cannot_be_repeated_after_approval(
    client, auth_header, organiser, coordinator, make_user, make_event
):
    make_user(OFFICER, ["safety_officer"])
    event_id = _event_in_safety_check(make_event, organiser, coordinator)
    assert _approve(client, auth_header, event_id).status_code == 200

    again = _approve(client, auth_header, event_id)
    view = client.get(f"/api/events/{event_id}/safety-assessment", headers=auth_header(OFFICER)).get_json()

    assert again.status_code == 409
    assert view["canAssess"] is False


def test_coordinator_cannot_set_safety_approved_through_status_endpoint(
    client, auth_header, organiser, coordinator, make_event
):
    event_id = make_event(organiser, status="safety_check", coordinator_id=coordinator)

    response = client.post(
        f"/api/events/{event_id}/status",
        headers=auth_header("coordinator@test.com"),
        json={"status": "safety_approved"},
    )

    assert response.status_code == 403
    assert db.session.get(Event, event_id).status == "safety_check"
