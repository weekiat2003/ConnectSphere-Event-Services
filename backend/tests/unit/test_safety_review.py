import pytest

from app.events.services import safety
from app.extensions import db
from app.models.event import Event, EventSafetyReview
from app.models.user import User


def test_approval_records_officer_time_and_complete_assessment(
    app, organiser, make_user, make_event
):
    with app.app_context():
        officer_id = make_user(
            "safety-approval@test.com", ["safety_officer"], name="Safety Officer"
        )
        event_id = make_event(organiser, status="safety_check")
        event = db.session.get(Event, event_id)
        officer = db.session.get(User, officer_id)

        safety.review_safety_check(
            event,
            officer,
            "approved",
            assessed_factors=sorted(safety.SAFETY_FACTORS),
        )

        review = EventSafetyReview.query.filter_by(event_id=event_id).one()
        assert event.status == "confirmed"
        assert review.decision == "approved"
        assert review.assessed_factors == sorted(safety.SAFETY_FACTORS)
        assert review.safety_officer.name == "Safety Officer"
        assert review.created_at is not None
        assert review.to_dict()["safetyOfficerName"] == "Safety Officer"
        assert review.to_dict()["createdAt"] == review.created_at.isoformat()


@pytest.mark.parametrize("decision", ["rejected", "changes_requested"])
def test_nonapproval_returns_event_to_planning_without_cancelling(
    app, organiser, make_user, make_event, decision
):
    with app.app_context():
        officer_id = make_user(f"safety-{decision}@test.com", ["safety_officer"])
        event_id = make_event(organiser, status="safety_check")
        event = db.session.get(Event, event_id)

        safety.review_safety_check(
            event,
            db.session.get(User, officer_id),
            decision,
            "Emergency access is obstructed",
            assessed_factors=["emergency_access"],
            concern_factors=["emergency_access"],
            affected_arrangements=["venue", "equipment"],
        )

        review = EventSafetyReview.query.filter_by(event_id=event_id).one()
        assert event.status == "planning"
        assert event.status != "cancelled"
        assert review.comments == "Emergency access is obstructed"
        assert review.concern_factors == ["emergency_access"]
        assert review.affected_arrangements == ["venue", "equipment"]


@pytest.mark.parametrize(
    ("comments", "assessed_factors", "concern_factors", "affected_arrangements", "message"),
    [
        ("", ["emergency_access"], ["emergency_access"], ["venue"], "reason"),
        (
            "Access needs work",
            ["emergency_access"],
            [],
            ["venue"],
            "at least one safety factor",
        ),
        (
            "Access needs work",
            ["emergency_access"],
            ["emergency_access"],
            [],
            "affected arrangements",
        ),
        (
            "Access needs work",
            [],
            ["emergency_access"],
            ["venue"],
            "also be marked as assessed",
        ),
    ],
)
def test_invalid_nonapproval_does_not_record_a_decision(
    app,
    organiser,
    make_user,
    make_event,
    comments,
    assessed_factors,
    concern_factors,
    affected_arrangements,
    message,
):
    with app.app_context():
        officer_id = make_user("safety-invalid@test.com", ["safety_officer"])
        event_id = make_event(organiser, status="safety_check")
        event = db.session.get(Event, event_id)

        with pytest.raises(ValueError, match=message):
            safety.review_safety_check(
                event,
                db.session.get(User, officer_id),
                "rejected",
                comments,
                assessed_factors,
                concern_factors,
                affected_arrangements,
            )

        assert event.status == "safety_check"
        assert EventSafetyReview.query.filter_by(event_id=event_id).count() == 0


def test_approval_requires_every_factor_and_no_concerns(
    app, organiser, make_user, make_event
):
    with app.app_context():
        officer_id = make_user("safety-incomplete@test.com", ["safety_officer"])
        event_id = make_event(organiser, status="safety_check")
        event = db.session.get(Event, event_id)
        officer = db.session.get(User, officer_id)

        with pytest.raises(ValueError, match="All safety factors"):
            safety.review_safety_check(
                event,
                officer,
                "approved",
                assessed_factors=["emergency_access"],
            )
        with pytest.raises(ValueError, match="cannot be approved"):
            safety.review_safety_check(
                event,
                officer,
                "approved",
                assessed_factors=sorted(safety.SAFETY_FACTORS),
                concern_factors=["emergency_access"],
            )

        assert event.status == "safety_check"
        assert EventSafetyReview.query.filter_by(event_id=event_id).count() == 0


def test_decided_event_cannot_be_reviewed_again(app, organiser, make_user, make_event):
    with app.app_context():
        officer_id = make_user("safety-repeat@test.com", ["safety_officer"])
        event_id = make_event(organiser, status="safety_check")
        event = db.session.get(Event, event_id)
        officer = db.session.get(User, officer_id)
        safety.review_safety_check(
            event,
            officer,
            "approved",
            assessed_factors=sorted(safety.SAFETY_FACTORS),
        )

        with pytest.raises(safety.SafetyReviewConflictError):
            safety.review_safety_check(
                event,
                officer,
                "rejected",
                "Attempted second decision",
                assessed_factors=["emergency_access"],
                concern_factors=["emergency_access"],
                affected_arrangements=["venue"],
            )

        assert EventSafetyReview.query.filter_by(event_id=event_id).count() == 1
