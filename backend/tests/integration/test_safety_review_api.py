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
    assert response.get_json()["status"] == "confirmed"
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
