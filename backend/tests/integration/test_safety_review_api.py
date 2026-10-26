import pytest

from app.events.services.safety import SAFETY_FACTORS
from app.extensions import db
from app.models.event import Event, EventSafetyReview


def _approval_payload():
    return {
        "decision": "approved",
        "assessedFactors": sorted(SAFETY_FACTORS),
    }


@pytest.mark.parametrize("decision", ["rejected", "changes_requested"])
def test_nonapproval_api_validates_and_returns_event_to_planning(
    client, auth_header, organiser, make_user, make_event, decision
):
    make_user("safety-integration@test.com", ["safety_officer"], name="Officer Riya")
    event_id = make_event(organiser, status="safety_check")
    payload = {
        "decision": decision,
        "comments": "Emergency access is blocked",
        "assessedFactors": ["emergency_access"],
        "concernFactors": ["emergency_access"],
        "affectedArrangements": ["venue", "equipment"],
    }

    response = client.post(
        f"/api/events/{event_id}/safety-review",
        headers=auth_header("safety-integration@test.com"),
        json=payload,
    )

    assert response.status_code == 200, response.get_json()
    assert response.get_json()["status"] == "planning"
    response_review = response.get_json()["safetyReviews"][0]
    assert response_review["safetyOfficerName"] == "Officer Riya"
    assert response_review["createdAt"]
    with client.application.app_context():
        review = EventSafetyReview.query.filter_by(event_id=event_id).one()
        assert review.decision == decision
        assert review.safety_officer.name == "Officer Riya"
        assert review.created_at is not None
        assert review.concern_factors == ["emergency_access"]
        assert review.affected_arrangements == ["venue", "equipment"]


@pytest.mark.parametrize(
    ("updates", "expected_error"),
    [
        ({"comments": ""}, "reason"),
        ({"concernFactors": []}, "at least one safety factor"),
        ({"affectedArrangements": []}, "affected arrangements"),
    ],
)
def test_invalid_nonapproval_api_shows_validation_error(
    client, auth_header, organiser, make_user, make_event, updates, expected_error
):
    make_user("safety-validation@test.com", ["safety_officer"])
    event_id = make_event(organiser, status="safety_check")
    payload = {
        "decision": "rejected",
        "comments": "This change is required",
        "assessedFactors": ["emergency_access"],
        "concernFactors": ["emergency_access"],
        "affectedArrangements": ["venue"],
    }
    payload.update(updates)

    response = client.post(
        f"/api/events/{event_id}/safety-review",
        headers=auth_header("safety-validation@test.com"),
        json=payload,
    )

    assert response.status_code == 400
    assert expected_error in response.get_json()["error"]
    with client.application.app_context():
        assert db.session.get(Event, event_id).status == "safety_check"
        assert EventSafetyReview.query.filter_by(event_id=event_id).count() == 0


def test_approval_api_requires_all_factors_to_be_assessed(
    client, auth_header, organiser, make_user, make_event
):
    make_user("safety-incomplete-api@test.com", ["safety_officer"])
    event_id = make_event(organiser, status="safety_check")

    response = client.post(
        f"/api/events/{event_id}/safety-review",
        headers=auth_header("safety-incomplete-api@test.com"),
        json={"decision": "approved", "assessedFactors": ["emergency_access"]},
    )

    assert response.status_code == 400
    assert "All safety factors" in response.get_json()["error"]
    with client.application.app_context():
        assert db.session.get(Event, event_id).status == "safety_check"
        assert EventSafetyReview.query.filter_by(event_id=event_id).count() == 0


def test_approval_api_records_name_and_time_and_rejects_repeat_decision(
    client, auth_header, organiser, make_user, make_event
):
    make_user("safety-approve-integration@test.com", ["safety_officer"], name="Officer Riya")
    event_id = make_event(organiser, status="safety_check")
    headers = auth_header("safety-approve-integration@test.com")

    response = client.post(
        f"/api/events/{event_id}/safety-review",
        headers=headers,
        json=_approval_payload(),
    )

    assert response.status_code == 200, response.get_json()
    assert response.get_json()["status"] == "safety_check"  # still pending Coordinator confirmation
    response_review = response.get_json()["safetyReviews"][0]
    assert response_review["safetyOfficerName"] == "Officer Riya"
    assert response_review["createdAt"]
    assert response_review["assessedFactors"] == sorted(SAFETY_FACTORS)
    with client.application.app_context():
        review = EventSafetyReview.query.filter_by(event_id=event_id).one()
        assert review.decision == "approved"
        assert review.safety_officer.name == "Officer Riya"
        assert review.created_at is not None
        assert review.assessed_factors == sorted(SAFETY_FACTORS)

    repeated = client.post(
        f"/api/events/{event_id}/safety-review",
        headers=headers,
        json={
            "decision": "rejected",
            "comments": "Second attempt",
            "assessedFactors": ["emergency_access"],
            "concernFactors": ["emergency_access"],
            "affectedArrangements": ["venue"],
        },
    )

    assert repeated.status_code == 409
    with client.application.app_context():
        assert EventSafetyReview.query.filter_by(event_id=event_id).count() == 1


def test_nonapproval_api_lists_all_validation_errors_and_keeps_event_open(
    client, auth_header, organiser, make_user, make_event
):
    make_user("safety-all-errors-api@test.com", ["safety_officer"])
    event_id = make_event(organiser, status="safety_check")

    response = client.post(
        f"/api/events/{event_id}/safety-review",
        headers=auth_header("safety-all-errors-api@test.com"),
        json={"decision": "changes_requested", "assessedFactors": ["crowd_movement"]},
    )

    assert response.status_code == 400
    body = response.get_json()
    assert len(body["errors"]) == 3
    assert "reason" in body["error"]
    assert "at least one safety factor" in body["error"]
    assert "affected arrangements" in body["error"]
    with client.application.app_context():
        event = db.session.get(Event, event_id)
        assert event.status == "safety_check"
        assert event.status != "cancelled"
        assert EventSafetyReview.query.filter_by(event_id=event_id).count() == 0

def test_coordinator_confirm_endpoint_moves_approved_event_to_confirmed(
    client, auth_header, organiser, make_user, make_event
):
    make_user("confirm-endpoint-officer@test.com", ["safety_officer"], name="Officer Approve")
    coordinator_id = make_user("confirm-endpoint-coordinator@test.com", ["event_coordinator"], name="Coordinator Confirm")
    event_id = make_event(organiser, status="safety_check", coordinator_id=coordinator_id)

    approve_response = client.post(
        f"/api/events/{event_id}/safety-review",
        headers=auth_header("confirm-endpoint-officer@test.com"),
        json=_approval_payload(),
    )
    assert approve_response.status_code == 200, approve_response.get_json()
    assert approve_response.get_json()["status"] == "safety_check"

    confirm_response = client.post(
        f"/api/events/{event_id}/confirm",
        headers=auth_header("confirm-endpoint-coordinator@test.com"),
    )
    assert confirm_response.status_code == 200, confirm_response.get_json()
    assert confirm_response.get_json()["status"] == "confirmed"


def test_confirm_endpoint_requires_assigned_coordinator(
    client, auth_header, organiser, make_user, make_event
):
    make_user("wrong-coord-officer@test.com", ["safety_officer"])
    coordinator_id = make_user("wrong-coord-assigned@test.com", ["event_coordinator"])
    make_user("wrong-coord-other@test.com", ["event_coordinator"])
    event_id = make_event(organiser, status="safety_check", coordinator_id=coordinator_id)

    client.post(
        f"/api/events/{event_id}/safety-review",
        headers=auth_header("wrong-coord-officer@test.com"),
        json=_approval_payload(),
    )

    response = client.post(
        f"/api/events/{event_id}/confirm",
        headers=auth_header("wrong-coord-other@test.com"),
    )
    assert response.status_code == 403


def test_other_roles_cannot_call_confirm_endpoint(
    client, auth_header, organiser, make_user, make_event
):
    officer_email = "other-role-officer@test.com"
    make_user(officer_email, ["safety_officer"])
    coordinator_id = make_user("other-role-coordinator@test.com", ["event_coordinator"])
    make_user("other-role-venue-staff@test.com", ["venue_staff"])
    event_id = make_event(organiser, status="safety_check", coordinator_id=coordinator_id)

    client.post(
        f"/api/events/{event_id}/safety-review",
        headers=auth_header(officer_email),
        json=_approval_payload(),
    )

    officer_attempt = client.post(f"/api/events/{event_id}/confirm", headers=auth_header(officer_email))
    assert officer_attempt.status_code == 403

    venue_staff_attempt = client.post(
        f"/api/events/{event_id}/confirm",
        headers=auth_header("other-role-venue-staff@test.com"),
    )
    assert venue_staff_attempt.status_code == 403


def test_confirm_endpoint_rejects_without_approved_review(
    client, auth_header, organiser, make_user, make_event
):
    coordinator_id = make_user("no-review-coordinator@test.com", ["event_coordinator"])

    # Case 1: no safety review submitted yet.
    event_id = make_event(organiser, status="safety_check", coordinator_id=coordinator_id)
    response = client.post(
        f"/api/events/{event_id}/confirm",
        headers=auth_header("no-review-coordinator@test.com"),
    )
    assert response.status_code == 400

    # Case 2: latest review is a rejection, not an approval.
    make_user("no-review-officer@test.com", ["safety_officer"])
    rejected_event_id = make_event(organiser, status="safety_check", coordinator_id=coordinator_id)
    client.post(
        f"/api/events/{rejected_event_id}/safety-review",
        headers=auth_header("no-review-officer@test.com"),
        json={
            "decision": "rejected",
            "comments": "Not safe",
            "assessedFactors": [
                "expected_attendance", "venue_capacity", "venue_layout", "emergency_access",
                "accessibility", "equipment_placement", "crowd_movement", "venue_restrictions",
            ],
            "concernFactors": ["crowd_movement"],
            "affectedArrangements": ["venue"],
        },
    )
    response = client.post(
        f"/api/events/{rejected_event_id}/confirm",
        headers=auth_header("no-review-coordinator@test.com"),
    )
    assert response.status_code == 400