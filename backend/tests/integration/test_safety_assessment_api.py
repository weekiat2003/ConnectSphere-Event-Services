"""API: Safety Officer review list, assessment view/save, and access control."""
from datetime import datetime

import pytest

from app.events.services.safety import SAFETY_FACTOR_ORDER
from app.extensions import db
from app.models.event import Event, EventSafetyAssessment, EventSafetyReview
from app.models.venue import Venue, VenueBooking


def _booked_event(make_event, organiser, status="safety_check", **fields):
    event_id = make_event(organiser, status=status, **fields)
    venue = Venue(name="Main Hall", capacity=200, known_restrictions="No open flames")
    venue.supported_layouts.append("theatre")
    db.session.add(venue)
    db.session.commit()
    db.session.add(
        VenueBooking(
            event_id=event_id,
            venue_id=venue.id,
            requested_by=organiser,
            status="approved",
            start_datetime=datetime(2026, 12, 1, 9),
            end_datetime=datetime(2026, 12, 1, 12),
        )
    )
    db.session.commit()
    return event_id


def test_safety_officer_sees_only_events_awaiting_safety_check(
    client, auth_header, organiser, make_user, make_event
):
    make_user("list-officer@test.com", ["safety_officer"])
    waiting = _booked_event(make_event, organiser, name="Waiting Event", expected_attendance=150)
    make_event(organiser, status="planning", name="Still planning")
    make_event(organiser, status="confirmed", name="Already confirmed")

    response = client.get("/api/events/safety-reviews", headers=auth_header("list-officer@test.com"))

    assert response.status_code == 200
    body = response.get_json()
    assert [e["id"] for e in body] == [waiting]
    assert body[0]["name"] == "Waiting Event"
    assert body[0]["proposedDate"] == "2026-12-01"
    assert body[0]["expectedAttendance"] == 150
    assert body[0]["venues"][0]["name"] == "Main Hall"


def test_safety_officer_views_assessment_facts(
    client, auth_header, organiser, make_user, make_event
):
    make_user("view-officer@test.com", ["safety_officer"])
    event_id = _booked_event(make_event, organiser, required_layout=None, accessibility_needs=None)

    response = client.get(
        f"/api/events/{event_id}/safety-assessment", headers=auth_header("view-officer@test.com")
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body["expectedAttendance"] == 50
    assert body["requiredLayout"] is None
    assert body["accessibilityRequirements"] is None
    assert body["equipmentRequirements"] == []
    venue = body["venues"][0]
    assert venue["capacity"] == 200
    assert venue["supportedLayouts"] == [{"name": "theatre", "maxCapacity": None}]
    assert venue["knownRestrictions"] == "No open flames"
    assert body["assessment"] is None


def test_safety_officer_saves_assessment_then_decides_with_it(
    client, auth_header, organiser, make_user, make_event
):
    make_user("save-officer@test.com", ["safety_officer"], name="Officer Tan")
    headers = auth_header("save-officer@test.com")
    event_id = _booked_event(make_event, organiser)
    factors = {key: {"outcome": "satisfactory", "notes": None} for key in SAFETY_FACTOR_ORDER}
    factors["venue_restrictions"] = {"outcome": "concern", "notes": "Stage pyrotechnics planned"}

    saved = client.put(
        f"/api/events/{event_id}/safety-assessment",
        headers=headers,
        json={"factorAssessments": factors},
    )
    assert saved.status_code == 200, saved.get_json()
    assessment = saved.get_json()["assessment"]
    assert assessment["factors"]["venue_restrictions"] == {
        "outcome": "concern",
        "notes": "Stage pyrotechnics planned",
    }
    assert assessment["safetyOfficerName"] == "Officer Tan"
    assert assessment["updatedAt"]

    decided = client.post(
        f"/api/events/{event_id}/safety-review",
        headers=headers,
        json={
            "decision": "rejected",
            "comments": "Pyrotechnics are not allowed in this venue",
            "affectedArrangements": ["venue", "equipment"],
            "factorAssessments": factors,
        },
    )

    assert decided.status_code == 200, decided.get_json()
    assert decided.get_json()["status"] == "planning"
    review = decided.get_json()["safetyReviews"][0]
    assert review["concernFactors"] == ["venue_restrictions"]
    assert review["factorNotes"] == {"venue_restrictions": "Stage pyrotechnics planned"}
    with client.application.app_context():
        assert EventSafetyAssessment.query.filter_by(event_id=event_id).count() == 0


def test_invalid_assessment_returns_400(client, auth_header, organiser, make_user, make_event):
    make_user("invalid-officer@test.com", ["safety_officer"])
    event_id = _booked_event(make_event, organiser)

    response = client.put(
        f"/api/events/{event_id}/safety-assessment",
        headers=auth_header("invalid-officer@test.com"),
        json={"factorAssessments": {"emergency_access": {"outcome": "maybe"}}},
    )

    assert response.status_code == 400
    assert "satisfactory or a concern" in response.get_json()["error"]


def test_assessment_cannot_be_saved_once_event_left_safety_check(
    client, auth_header, organiser, make_user, make_event
):
    make_user("conflict-officer@test.com", ["safety_officer"])
    event_id = make_event(organiser, status="confirmed")

    response = client.put(
        f"/api/events/{event_id}/safety-assessment",
        headers=auth_header("conflict-officer@test.com"),
        json={"factorAssessments": {"emergency_access": {"outcome": "concern"}}},
    )

    assert response.status_code == 409


def test_draft_events_are_not_found(client, auth_header, organiser, make_user, make_event):
    make_user("draft-officer@test.com", ["safety_officer"])
    event_id = make_event(organiser, status="draft")

    response = client.get(
        f"/api/events/{event_id}/safety-assessment", headers=auth_header("draft-officer@test.com")
    )

    assert response.status_code == 404


NON_SAFETY_ROLES = [
    "event_organiser",
    "event_coordinator",
    "venue_staff",
    "technical_support_staff",
    "attendee",
]


@pytest.mark.parametrize("role", NON_SAFETY_ROLES)
def test_other_roles_are_denied_the_review_list_and_assessment(
    client, auth_header, organiser, make_user, make_event, role
):
    email = f"denied-{role}@test.com"
    make_user(email, [role])
    headers = auth_header(email)
    event_id = _booked_event(make_event, organiser)

    responses = [
        client.get("/api/events/safety-reviews", headers=headers),
        client.get(f"/api/events/{event_id}/safety-assessment", headers=headers),
        client.put(
            f"/api/events/{event_id}/safety-assessment",
            headers=headers,
            json={"factorAssessments": {"emergency_access": {"outcome": "concern"}}},
        ),
    ]

    assert [r.status_code for r in responses] == [403, 403, 403]
    with client.application.app_context():
        assert EventSafetyAssessment.query.count() == 0
        assert EventSafetyReview.query.count() == 0
        assert db.session.get(Event, event_id).status == "safety_check"


def test_unauthenticated_requests_are_denied(client, organiser, make_event):
    event_id = make_event(organiser, status="safety_check")

    assert client.get("/api/events/safety-reviews").status_code == 401
    assert client.get(f"/api/events/{event_id}/safety-assessment").status_code == 401
