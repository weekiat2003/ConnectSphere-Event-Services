from datetime import datetime

import pytest

from app.equipment.services.preparation import confirm_equipment_suitability
from app.events.services import safety
from app.extensions import db
from app.models.equipment import EquipmentItem, EquipmentReservation
from app.models.event import Event, EventEquipmentRequirement, EventSafetyReview
from app.models.notification import Notification, TYPE_ARRANGEMENT_REVIEW
from app.models.user import User


def _add_reserved_requirements(event, equipment_types=("Projector", "Speaker")):
    requirements = []
    for equipment_type in equipment_types:
        requirement = EventEquipmentRequirement(
            event_id=event.id,
            equipment_type=equipment_type,
            quantity=1,
            status="confirmed",
        )
        item = EquipmentItem(name=equipment_type, total_quantity=1)
        db.session.add_all([requirement, item])
        db.session.flush()
        db.session.add(
            EquipmentReservation(
                event_id=event.id,
                equipment_requirement_id=requirement.id,
                equipment_item_id=item.id,
                quantity=1,
                start_datetime=datetime(2026, 12, 1, 10),
                end_datetime=datetime(2026, 12, 1, 12),
                status="reserved",
            )
        )
        requirements.append(requirement)
    db.session.commit()
    return requirements


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
        assert event.status == "safety_approved"  # out of Safety Check; Coordinator confirms next
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


@pytest.mark.parametrize("decision", ["rejected", "changes_requested"])
def test_nonapproval_for_equipment_flags_all_requirements_without_releasing_reservations(
    app, organiser, make_user, make_event, decision
):
    with app.app_context():
        officer_id = make_user(f"safety-equipment-{decision}@test.com", ["safety_officer"])
        event_id = make_event(organiser, status="safety_check")
        event = db.session.get(Event, event_id)
        requirements = _add_reserved_requirements(event)

        safety.review_safety_check(
            event,
            db.session.get(User, officer_id),
            decision,
            "Equipment placement needs revision",
            assessed_factors=["equipment_placement"],
            concern_factors=["equipment_placement"],
            affected_arrangements=["equipment"],
        )

        assert event.status == "planning"
        assert all(requirement.needs_recheck for requirement in requirements)
        assert all(requirement.status == "confirmed" for requirement in requirements)
        assert all(
            reservation.status == "reserved"
            for reservation in EquipmentReservation.query.filter_by(event_id=event_id).all()
        )


@pytest.mark.parametrize("decision", ["changes_requested", "rejected"])
def test_safety_equipment_recheck_notifies_each_technical_support_user(
    app, organiser, make_user, make_event, decision
):
    with app.app_context():
        officer_id = make_user(f"safety-notify-{decision}@test.com", ["safety_officer"])
        tech_ids = [
            make_user("tech-notify-one@test.com", ["technical_support_staff"]),
            make_user("tech-notify-two@test.com", ["technical_support_staff"]),
        ]
        event_id = make_event(organiser, status="safety_check")
        event = db.session.get(Event, event_id)
        _add_reserved_requirements(event)

        safety.review_safety_check(
            event,
            db.session.get(User, officer_id),
            decision,
            "Equipment setup needs another check",
            assessed_factors=["equipment_placement"],
            concern_factors=["equipment_placement"],
            affected_arrangements=["equipment"],
        )

        notifications = Notification.query.filter_by(
            event_id=event_id, type=TYPE_ARRANGEMENT_REVIEW
        ).all()
        assert {notification.recipient_id for notification in notifications} == set(tech_ids)
        assert len(notifications) == len(tech_ids)
        for notification in notifications:
            assert notification.title == "Safety check: equipment recheck needed"
            action = (
                "requested changes to the arrangements"
                if decision == "changes_requested"
                else "rejected the arrangements"
            )
            assert action in notification.message
            assert "Please recheck the flagged equipment." in notification.message
            assert "Equipment setup needs another check" in notification.message
            assert notification.link == f"/technical-review?event={event_id}"


@pytest.mark.parametrize(
    ("decision", "affected_arrangements", "assessed_factors", "concern_factors"),
    [
        ("changes_requested", ["venue"], ["emergency_access"], ["emergency_access"]),
        ("approved", [], sorted(safety.SAFETY_FACTORS), []),
    ],
)
def test_safety_decisions_without_equipment_impact_do_not_notify_technical_support(
    app,
    organiser,
    make_user,
    make_event,
    decision,
    affected_arrangements,
    assessed_factors,
    concern_factors,
):
    with app.app_context():
        officer_id = make_user(f"safety-no-notify-{decision}@test.com", ["safety_officer"])
        make_user("tech-no-notify@test.com", ["technical_support_staff"])
        event_id = make_event(organiser, status="safety_check")
        event = db.session.get(Event, event_id)
        _add_reserved_requirements(event)

        safety.review_safety_check(
            event,
            db.session.get(User, officer_id),
            decision,
            "Review decision",
            assessed_factors=assessed_factors,
            concern_factors=concern_factors,
            affected_arrangements=affected_arrangements,
        )

        assert Notification.query.filter_by(
            event_id=event_id, type=TYPE_ARRANGEMENT_REVIEW
        ).count() == 0


def test_changes_requested_for_venue_does_not_flag_equipment(
    app, organiser, make_user, make_event
):
    with app.app_context():
        officer_id = make_user("safety-venue@test.com", ["safety_officer"])
        event_id = make_event(organiser, status="safety_check")
        event = db.session.get(Event, event_id)
        requirements = _add_reserved_requirements(event)

        safety.review_safety_check(
            event,
            db.session.get(User, officer_id),
            "changes_requested",
            "Venue access needs revision",
            assessed_factors=["emergency_access"],
            concern_factors=["emergency_access"],
            affected_arrangements=["venue"],
        )

        assert event.status == "planning"
        assert all(not requirement.needs_recheck for requirement in requirements)


def test_approval_does_not_flag_equipment(app, organiser, make_user, make_event):
    with app.app_context():
        officer_id = make_user("safety-no-recheck-approved@test.com", ["safety_officer"])
        event_id = make_event(organiser, status="safety_check")
        event = db.session.get(Event, event_id)
        requirements = _add_reserved_requirements(event)

        safety.review_safety_check(
            event,
            db.session.get(User, officer_id),
            "approved",
            assessed_factors=sorted(safety.SAFETY_FACTORS),
        )

        assert all(not requirement.needs_recheck for requirement in requirements)


def test_equipment_rechecks_wait_for_coordinator_to_send_safety_check(
    app, organiser, make_user, make_event
):
    with app.app_context():
        officer_id = make_user("safety-recheck@test.com", ["safety_officer"])
        tech_id = make_user("tech-recheck@test.com", ["technical_support_staff"])
        event_id = make_event(organiser, status="safety_check")
        event = db.session.get(Event, event_id)
        requirements = _add_reserved_requirements(event)

        safety.review_safety_check(
            event,
            db.session.get(User, officer_id),
            "changes_requested",
            "Equipment placement needs revision",
            assessed_factors=["equipment_placement"],
            concern_factors=["equipment_placement"],
            affected_arrangements=["equipment"],
        )
        tech = db.session.get(User, tech_id)
            
        confirm_equipment_suitability(requirements[0], tech)
        assert requirements[0].needs_recheck is False
        assert requirements[1].needs_recheck is True
        assert event.status == "planning"

        confirm_equipment_suitability(requirements[1], tech)
        assert requirements[1].needs_recheck is False

        # Technical Support has finished the rechecks.
        # The event remains in planning until the Coordinator initiates the safety check.
        assert event.status == "planning"

        # The Coordinator explicitly sends the event for safety review.
        from app.events.services import status as status_service

        status_service.change_status(event, "safety_check", event.coordinator_id)

        assert event.status == "safety_check"


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


@pytest.mark.parametrize("decision", ["rejected", "changes_requested"])
def test_nonapproval_reports_every_missing_detail_at_once(
    app, organiser, make_user, make_event, decision
):
    with app.app_context():
        officer_id = make_user(f"safety-all-missing-{decision}@test.com", ["safety_officer"])
        event_id = make_event(organiser, status="safety_check")
        event = db.session.get(Event, event_id)

        with pytest.raises(safety.SafetyReviewValidationError) as excinfo:
            safety.review_safety_check(
                event,
                db.session.get(User, officer_id),
                decision,
                "   ",
                assessed_factors=["emergency_access"],
                concern_factors=[],
                affected_arrangements=[],
            )

        errors = excinfo.value.errors
        assert len(errors) == 3
        assert any("reason" in error for error in errors)
        assert any("at least one safety factor" in error for error in errors)
        assert any("affected arrangements" in error for error in errors)
        assert event.status == "safety_check"
        assert EventSafetyReview.query.filter_by(event_id=event_id).count() == 0
