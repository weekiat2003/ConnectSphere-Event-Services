"""Unit tests for Event Status Management: Stories 1-4.

Every test in this file calls a model, service function, or helper
directly -- no `client`, no HTTP, no JWT. Anything that needs a real
request belongs in the integration test file instead.
"""
from datetime import date, time, timedelta
from types import SimpleNamespace

import pytest

from app.common.time import utcnow
from app.equipment.services import reservation as equipment_reservation
from app.events.routes import _can_view
from app.events.services import drafts, review, safety
from app.events.services import status as status_service
from app.events.services.status import change_status
from app.extensions import db
from app.models.equipment import EquipmentItem, EquipmentReservation
from app.models.event import (
    EVENT_STATUSES,
    Event,
    EventEquipmentRequirement,
    EventSafetyAssessment,
    EventSafetyReview,
    EventStatusHistory,
    STATUS_LABELS,
    UNKNOWN_STATUS_LABEL,
)
from app.models.user import User
from app.models.venue import Venue, VenueBooking
from app.venues.services import booking as venue_booking
from app.events.services import update as update_service

ORG = "organiser@test.com"
COORD = "coordinator@test.com"


# =====================================================================
# Story 1: Consistent status display (model / permission-function level)
# =====================================================================

@pytest.mark.parametrize("status", EVENT_STATUSES)
def test_event_serialization_exposes_current_status_and_label(app, organiser, status):
    # AC1/AC6: every known status serializes with its matching label and
    # is marked valid.
    with app.app_context():
        event = Event(organiser_id=organiser, status=status)

        payload = event.to_dict()

        assert payload["status"] == status
        assert payload["statusLabel"] == STATUS_LABELS[status]
        assert payload["statusValid"] is True


def test_status_serialization_is_independent_for_each_event(app, organiser):
    # AC2: serializing several events never lets one event's status leak
    # into another's payload.
    with app.app_context():
        events = [
            Event(organiser_id=organiser, status="draft"),
            Event(organiser_id=organiser, status="planning"),
            Event(organiser_id=organiser, status="confirmed"),
        ]

        payloads = [event.to_dict() for event in events]

        assert [payload["status"] for payload in payloads] == [
            "draft",
            "planning",
            "confirmed",
        ]
        assert [payload["statusLabel"] for payload in payloads] == [
            "Draft",
            "Planning",
            "Confirmed",
        ]


def test_status_changes_are_reflected_by_a_fresh_serialization(
    app, organiser, coordinator
):
    # AC4: after a real status change, re-reading the event from the DB
    # and re-serializing it shows the new status, not a stale cached one.
    with app.app_context():
        event = Event(organiser_id=organiser, status="draft")
        db.session.add(event)
        db.session.commit()
        assert event.to_dict()["status"] == "draft"

        change_status(event, "submitted", changed_by_id=coordinator)
        refreshed = db.session.get(Event, event.id)

        assert refreshed.to_dict()["status"] == "submitted"
        assert EventStatusHistory.query.filter_by(event_id=event.id).count() == 1


def test_unauthorised_user_cannot_view_event_or_status(app, organiser):
    # AC3: _can_view denies a user with no role-based or ownership claim.
    with app.app_context():
        event = SimpleNamespace(organiser_id=organiser, status="confirmed")
        unrelated_organiser = SimpleNamespace(
            id=organiser + 1,
            has_role=lambda role: role == "event_organiser",
        )

        assert _can_view(event, unrelated_organiser) is False


def test_authorised_internal_user_can_view_non_draft_event_status(app, organiser):
    # AC3: _can_view allows an internal role to see a non-draft event.
    with app.app_context():
        event = SimpleNamespace(organiser_id=organiser, status="planning")
        coordinator = SimpleNamespace(
            id=organiser + 1,
            has_role=lambda role: role == "event_coordinator",
        )

        assert _can_view(event, coordinator) is True


def test_new_event_defaults_to_draft(app, organiser):
    # AC5: before insert, the column default hasn't applied yet, so the
    # fallback label covers the in-memory gap.
    with app.app_context():
        event = Event(organiser_id=organiser)

        payload = event.to_dict()

        # SQLAlchemy applies the column default on insert, not construction.
        assert event.status is None
        assert payload["statusLabel"] == UNKNOWN_STATUS_LABEL


def test_persisted_new_event_defaults_to_draft(app, organiser):
    # AC5: once actually saved, a new event is "draft".
    with app.app_context():
        event = Event(organiser_id=organiser)
        db.session.add(event)
        db.session.commit()

        assert event.status == "draft"
        assert event.to_dict()["statusLabel"] == "Draft"


@pytest.mark.parametrize("invalid_status", [None, "", "banana", "UNDER_REVIEW"])
def test_missing_or_unknown_status_has_explicit_fallback(
    app, organiser, invalid_status
):
    # AC6: any value that isn't a known status (missing, blank, garbage,
    # wrong case) is explicitly flagged invalid with a non-empty label.
    with app.app_context():
        payload = Event(organiser_id=organiser, status=invalid_status).to_dict()

        assert payload["statusValid"] is False
        assert payload["statusLabel"] == UNKNOWN_STATUS_LABEL
        assert payload["statusLabel"]


# =====================================================================
# Story 3: arrangements lead to a safety check before confirmation
# =====================================================================

def _create_venue_booking(
    event,
    organiser,
    status="pending",
    venue_owner_id=None,
):
    venue = Venue(
        name="Test Hall",
        location="Campus",
        capacity=200,
        created_by=venue_owner_id,
    )
    db.session.add(venue)
    db.session.flush()
    booking = VenueBooking(
        event_id=event.id,
        venue_id=venue.id,
        requested_by=organiser,
        status=status,
        start_datetime=utcnow() + timedelta(days=30),
        end_datetime=utcnow() + timedelta(days=30, hours=2),
    )
    db.session.add(booking)
    db.session.commit()
    return booking


def test_approval_leaves_event_in_approved_until_coordinator_proceeds(
    app, organiser, coordinator, make_event
):
    # Manual workflow: approval and proceeding to planning are two
    # separate Coordinator actions.
    with app.app_context():
        event_id = make_event(
            organiser, status="under_review", coordinator_id=coordinator
        )
        event = db.session.get(Event, event_id)

        review.approve_event(event, coordinator)

        assert event.status == "approved"
        assert [entry.new_status for entry in event.status_history] == ["approved"]

        # The Coordinator's separate action moves it into planning.
        change_status(
            event,
            "planning",
            changed_by_id=coordinator,
            reason="Coordinator proceeded to planning",
        )

        assert event.status == "planning"
        assert [entry.new_status for entry in event.status_history] == [
            "approved",
            "planning",
        ]


def test_pending_venue_prevents_manual_safety_check(
    app, organiser, make_event
):
    # Negative case: an unapproved venue must block the Coordinator
    # from manually sending the event for safety assessment.
    with app.app_context():
        event_id = make_event(
            organiser, status="planning", capacity_needed=100
        )
        event = db.session.get(Event, event_id)
        _create_venue_booking(event, organiser, status="pending")

        assert status_service.arrangements_are_complete(event) is False

        with pytest.raises(status_service.InvalidTransitionError):
            change_status(
                event, "safety_check", changed_by_id=organiser
            )

        assert event.status == "planning"


def test_venue_approval_does_not_automatically_start_safety_check(
    app, organiser, coordinator, make_user, make_event
):
    # Venue approval completes the arrangement, but only the
    # Coordinator's explicit action can start the safety check.
    with app.app_context():
        venue_staff_id = make_user(
            "status-venue-staff@test.com", ["venue_staff"]
        )
        event_id = make_event(
            organiser, status="planning", capacity_needed=100
        )
        event = db.session.get(Event, event_id)
        booking = _create_venue_booking(
            event, organiser, venue_owner_id=venue_staff_id
        )

        venue_booking.approve_booking(
            booking, decided_by=venue_staff_id
        )

        assert status_service.arrangements_are_complete(event) is True
        assert event.status == "planning"

        change_status(
            event,
            "safety_check",
            changed_by_id=coordinator,
            reason="Coordinator sent event for safety assessment",
        )

        assert event.status == "safety_check"
        assert EventStatusHistory.query.filter_by(
            event_id=event_id, new_status="safety_check"
        ).count() == 1


def test_pending_equipment_prevents_safety_check_after_venue_approval(
    app, organiser, coordinator, make_user, make_event, 
):
    # AC2: venue alone isn't enough once equipment is also requested --
    # arrangements aren't complete until equipment is reserved too.
    with app.app_context():
        venue_staff_id = make_user(
            "status-venue-staff-equipment@test.com",
            ["venue_staff"],
        )
        event_id = make_event(organiser, status="planning", capacity_needed=100)
        event = db.session.get(Event, event_id)
        event.equipment_requirements.append(
            EventEquipmentRequirement(equipment_type="Projector", quantity=1)
        )
        booking = _create_venue_booking(
            event,
            organiser,
            venue_owner_id=venue_staff_id,
        )

        venue_booking.approve_booking(booking, decided_by=venue_staff_id)

        assert event.status == "planning"
        assert status_service.arrangements_are_complete(event) is False

        with pytest.raises(status_service.InvalidTransitionError):
            change_status(
                event,
                "safety_check",
                changed_by_id=coordinator,
            )

        assert event.status == "planning"

def test_last_equipment_reservation_moves_event_to_safety_check(
    app, organiser, coordinator, make_event
):
    # Completing the last equipment reservation makes arrangements ready.
    # The event remains in planning until the Coordinator manually sends it
    # for safety assessment.
    with app.app_context():
        event_id = make_event(organiser, status="planning", capacity_needed=100)
        event = db.session.get(Event, event_id)
        requirement = EventEquipmentRequirement(equipment_type="Projector", quantity=2)
        event.equipment_requirements.append(requirement)
        booking = _create_venue_booking(event, organiser, status="approved")
        item = EquipmentItem(name="Projector", total_quantity=5)
        db.session.add(item)
        db.session.commit()

        equipment_reservation.reserve(
            event,
            requirement,
            item,
            booking.start_datetime,
            booking.end_datetime,
            organiser,
        )

        assert status_service.arrangements_are_complete(event) is True
        assert event.status == "planning"

        change_status(
            event,
            "safety_check",
            changed_by_id=coordinator,
            reason="Coordinator sent event for safety assessment",
        )
        assert EventStatusHistory.query.filter_by(
        event_id=event_id,
        new_status="safety_check",
        ).count() == 1

        assert event.status == "safety_check"

# Safety approval doesn't automatically confirm the event.
def test_safety_officer_approval_leaves_event_awaiting_coordinator_confirmation(app, organiser, make_user, make_event):
    with app.app_context():
        officer_id = make_user("safety@test.com", ["safety_officer"])
        officer = db.session.get(User, officer_id)
        event_id = make_event(organiser, status="safety_check")
        event = db.session.get(Event, event_id)

        safety.review_safety_check(
            event,
            officer,
            "approved",
            "Egress and access reviewed",
            assessed_factors=sorted(safety.SAFETY_FACTORS),
        )

        assert event.status == "safety_approved"
        review_record = EventSafetyReview.query.filter_by(event_id=event_id).one()
        assert review_record.decision == "approved"
        assert review_record.safety_officer_id == officer_id
        assert event.to_dict()["safetyReviews"][0]["comments"] == "Egress and access reviewed"

@pytest.mark.parametrize("decision", ["rejected", "changes_requested"])
# Rejection and change requests return the event to planning.
def test_safety_rejection_or_change_request_returns_event_to_planning(
    app, organiser, make_user, make_event, decision
):
    # AC3: rejecting or requesting changes sends the event back to
    # planning, not back to safety_check or anywhere else.
    with app.app_context():
        officer_id = make_user(f"safety-{decision}@test.com", ["safety_officer"])
        officer = db.session.get(User, officer_id)
        event_id = make_event(organiser, status="safety_check")
        event = db.session.get(Event, event_id)

        safety.review_safety_check(
            event,
            officer,
            decision,
            "Adjust emergency access",
            assessed_factors=["emergency_access"],
            concern_factors=["emergency_access"],
            affected_arrangements=["venue"],
        )

        assert event.status == "planning"
        assert EventSafetyReview.query.filter_by(event_id=event_id, decision=decision).count() == 1


def test_non_safety_user_cannot_approve_safety_check(app, organiser, coordinator, make_event):
    # AC3: a Coordinator (or anyone without the safety_officer role) is
    # rejected outright, before any status logic runs.
    with app.app_context():
        event_id = make_event(organiser, status="safety_check")
        event = db.session.get(Event, event_id)
        coordinator_user = db.session.get(User, coordinator)

        with pytest.raises(PermissionError, match="Only a Safety Officer"):
            safety.review_safety_check(event, coordinator_user, "approved")


def test_safety_officer_cannot_review_event_before_arrangements_reach_safety_check(
    app, organiser, make_user, make_event
):
    # AC2/AC3: a Safety Officer can't review an event that hasn't reached
    # safety_check yet -- the gate is the status, not the role alone.
    with app.app_context():
        officer_id = make_user("early-safety@test.com", ["safety_officer"])
        officer = db.session.get(User, officer_id)
        event_id = make_event(organiser, status="planning")
        event = db.session.get(Event, event_id)

        with pytest.raises(ValueError, match="awaiting a safety check"):
            safety.review_safety_check(event, officer, "approved")


def test_cancelling_approved_venue_reverts_confirmed_event_to_planning(
    app, organiser, coordinator, make_event
):
    # AC4: losing the (only) approved venue arrangement reverts a
    # confirmed event back to planning, with a reason recorded.
    with app.app_context():
        event_id = make_event(organiser, status="confirmed", capacity_needed=100)
        event = db.session.get(Event, event_id)
        booking = _create_venue_booking(event, organiser, status="approved", venue_owner_id=coordinator)

        venue_booking.cancel_booking(booking, decided_by=coordinator, reason="Venue unavailable")

        assert booking.status == "cancelled"
        assert booking.decided_by == coordinator
        assert booking.decision_reason == "Venue unavailable"
        assert booking.decided_at is not None
        assert event.status == "planning"
        history = EventStatusHistory.query.filter_by(
            event_id=event_id, new_status="planning"
        ).one()
        assert "venue booking" in history.reason.lower()


def test_pending_venue_booking_cannot_be_cancelled(app, organiser, coordinator, make_event):
    # AC4 guard: only an approved booking is cancellable -- a pending one
    # should be rejected or withdrawn instead, never cancelled.
    with app.app_context():
        event_id = make_event(organiser, status="planning", capacity_needed=100)
        event = db.session.get(Event, event_id)
        booking = _create_venue_booking(event, organiser, status="pending", venue_owner_id=coordinator)

        with pytest.raises(ValueError, match="Only approved bookings"):
            venue_booking.cancel_booking(
                booking,
                decided_by=coordinator,
                reason="Venue unavailable",
            )

        assert booking.status == "pending"
        assert booking.decided_by is None
        assert booking.decision_reason is None


# Verifies manual transition and prevents duplicate history.
def test_manual_safety_transition_creates_only_one_history_record(
    app, organiser, coordinator, make_event, monkeypatch
):
    with app.app_context():
        event_id = make_event(
            organiser,
            status="planning",
            coordinator_id=coordinator,
        )
        event = db.session.get(Event, event_id)

        # make_event inserts directly into the database, so no safety
        # transition should have been recorded yet.
        assert event.status == "planning"
        assert EventStatusHistory.query.filter_by(
            event_id=event_id,
            new_status="safety_check",
        ).count() == 0

        # Simulate completed venue and equipment arrangements.
        monkeypatch.setattr(
            status_service,
            "arrangements_are_complete",
            lambda event: True,
        )

        # The assigned Coordinator manually sends the event for safety check.
        status_service.change_status(
            event,
            "safety_check",
            changed_by_id=coordinator,
        )

        db.session.refresh(event)

        assert event.status == "safety_check"
        assert EventStatusHistory.query.filter_by(
            event_id=event_id,
            new_status="safety_check",
        ).count() == 1

        # Trying the same transition again must be rejected.
        with pytest.raises(status_service.InvalidTransitionError):
            status_service.change_status(
                event,
                "safety_check",
                changed_by_id=coordinator,
            )

        db.session.refresh(event)

        # The failed second attempt must not create another history record.
        assert event.status == "safety_check"
        assert EventStatusHistory.query.filter_by(
            event_id=event_id,
            new_status="safety_check",
        ).count() == 1


def test_released_equipment_is_not_counted_as_reserved(app, organiser, make_event):
    # AC2/AC4: a RELEASED reservation must not count toward "complete
    # arrangements" -- only an actively RESERVED one does.
    with app.app_context():
        event_id = make_event(organiser, status="planning")
        event = db.session.get(Event, event_id)
        requirement = EventEquipmentRequirement(equipment_type="Projector", quantity=1)
        event.equipment_requirements.append(requirement)
        db.session.flush()
        item = EquipmentItem(name="Projector", total_quantity=2)
        db.session.add(item)
        db.session.flush()
        record = EquipmentReservation(
            event_id=event_id,
            equipment_requirement_id=requirement.id,
            equipment_item_id=item.id,
            quantity=1,
            start_datetime=utcnow() + timedelta(days=30),
            end_datetime=utcnow() + timedelta(days=30, hours=1),
            status="released",
        )
        db.session.add(record)
        db.session.commit()

        assert event.status == "planning"


def test_rejected_booking_for_other_venue_does_not_block_confirmation(
    app, organiser, make_user, make_event
):
    # AC2 regression: a REJECTED booking for one venue must not
    # permanently block arrangements from completing once a different
    # venue for the same event is approved.
    with app.app_context():
        venue_staff_id = make_user("reject-then-approve@test.com", ["venue_staff"])
        event_id = make_event(organiser, status="planning", capacity_needed=100)
        event = db.session.get(Event, event_id)

        rejected = _create_venue_booking(event, organiser, venue_owner_id=venue_staff_id)
        venue_booking.reject_booking(rejected, decided_by=venue_staff_id, reason="Not available")

        approved = _create_venue_booking(event, organiser, venue_owner_id=venue_staff_id)
        venue_booking.approve_booking(approved, decided_by=venue_staff_id)

        assert event.status == "planning"


def test_releasing_equipment_reservation_reverts_confirmed_event_to_planning(
    app, organiser, make_event
):
    # AC4 regression: release() must not crash, and must revert a
    # confirmed event to planning once equipment is no longer reserved.
    with app.app_context():
        event_id = make_event(organiser, status="confirmed")
        event = db.session.get(Event, event_id)
        requirement = EventEquipmentRequirement(equipment_type="Projector", quantity=1)
        event.equipment_requirements.append(requirement)
        db.session.flush()
        item = EquipmentItem(name="Projector", total_quantity=2)
        db.session.add(item)
        db.session.flush()
        reservation = EquipmentReservation(
            event_id=event_id,
            equipment_requirement_id=requirement.id,
            equipment_item_id=item.id,
            quantity=1,
            start_datetime=utcnow() + timedelta(days=30),
            end_datetime=utcnow() + timedelta(days=30, hours=1),
            status="reserved",
            created_by=organiser,
        )
        db.session.add(reservation)
        db.session.commit()

        equipment_reservation.release(reservation)

        assert reservation.status == "released"
        assert event.status == "planning"


def test_coordinator_confirm_moves_approved_event_to_confirmed(app, organiser, make_user, make_event):
    with app.app_context():
        officer_id = make_user("confirm-flow-officer@test.com", ["safety_officer"])
        coordinator_id = make_user("confirm-flow-coordinator@test.com", ["event_coordinator"])
        officer = db.session.get(User, officer_id)
        event_id = make_event(organiser, status="safety_check")
        event = db.session.get(Event, event_id)
        event.coordinator_id = coordinator_id
        db.session.commit()

        safety.review_safety_check(
            event, officer, "approved", "Checked",
            assessed_factors=sorted(safety.SAFETY_FACTORS),
        )
        review = (
            EventSafetyReview.query.filter_by(event_id=event_id)
            .order_by(EventSafetyReview.id.desc())
            .first()
        )

        # The test currently confirms that the service function changes the status, now verify that the event is awaiting confirmation first.
        assert event.status == "safety_approved"
        assert status_service.awaiting_confirmation(event) is True

        event = status_service.confirm_after_safety_approval(event, review, coordinator_id)

       

        assert event.status == "confirmed"
        latest_history = (
            EventStatusHistory.query
            .filter_by(event_id=event_id, new_status="confirmed")
            .order_by(EventStatusHistory.id.desc())
            .first()
        )
        assert latest_history is not None
        assert latest_history.changed_by == coordinator_id


def test_confirm_after_safety_approval_rejects_when_not_in_safety_check(app, organiser, make_user, make_event):
    with app.app_context():
        coordinator_id = make_user("not-safety-check-coordinator@test.com", ["event_coordinator"])
        officer_id = make_user("not-safety-check-officer@test.com", ["safety_officer"])
        officer = db.session.get(User, officer_id)

        # Case 1: event already confirmed — confirming twice must fail.
        confirmed_event_id = make_event(organiser, status="safety_check")
        confirmed_event = db.session.get(Event, confirmed_event_id)
        confirmed_event.coordinator_id = coordinator_id
        db.session.commit()
        safety.review_safety_check(
            confirmed_event, officer, "approved", "Checked",
            assessed_factors=sorted(safety.SAFETY_FACTORS),
        )
        review = (
            EventSafetyReview.query.filter_by(event_id=confirmed_event_id)
            .order_by(EventSafetyReview.id.desc())
            .first()
        )

        confirmed_event = status_service.confirm_after_safety_approval(confirmed_event, review, coordinator_id)
        assert confirmed_event.status == "confirmed"

        with pytest.raises(status_service.InvalidTransitionError):
            status_service.confirm_after_safety_approval(confirmed_event, review, coordinator_id)

        # Case 2: a different event in planning cannot use another event's
        # approved safety review to become confirmed.        
        planning_event_id = make_event(organiser, status="planning")
        planning_event = db.session.get(Event, planning_event_id)
        planning_event.coordinator_id = coordinator_id
        db.session.commit()

        with pytest.raises(status_service.InvalidTransitionError):
            status_service.confirm_after_safety_approval(planning_event, review, coordinator_id)


def test_update_draft_rejects_edit_on_rejected_event(app, organiser, make_event):
    # AC3: a rejected event is in a terminal state, so the draft-edit
    # service must refuse to apply changes to it.
    with app.app_context():
        event_id = make_event(organiser, status="rejected")
        event = db.session.get(Event, event_id)

        with pytest.raises(ValueError, match="Only a draft request"):
            drafts.update_draft(event, {"name": "Changed after rejection"})


def test_update_draft_rejects_edit_on_cancelled_event(app, organiser, make_event):
    # AC3: same guarantee for a cancelled event.
    with app.app_context():
        event_id = make_event(organiser, status="cancelled")
        event = db.session.get(Event, event_id)

        with pytest.raises(ValueError, match="Only a draft request"):
            drafts.update_draft(event, {"name": "Changed after cancellation"})

def test_resubmission_leaves_original_rejected_event_unchanged(
    app, organiser, coordinator, make_event
):
    # AC5: resubmitting a rejected request creates a brand-new Event row;
    # the original must stay in the database, still "rejected", still
    # fetchable by its own id -- never mutated or deleted.
    with app.app_context():
        original_id = make_event(
            organiser,
            status="rejected",
            name="Original Request",
            purpose="Purpose",
            description="Description",
            proposed_date=date(2026, 12, 1),
            proposed_time=time(9, 0),
            expected_attendance=50,
            capacity_needed=100,
            required_layout="theatre",
            accessibility_needs="None",
            coordinator_id=coordinator,
        )
        original = db.session.get(Event, original_id)

        new_event = review.resubmit_rejected_event(original, organiser, {})

        refreshed_original = db.session.get(Event, original_id)
        assert refreshed_original.status == "rejected"
        assert new_event.id != original_id
        assert new_event.resubmitted_from_event_id == original_id

def test_cannot_be_resubmitted_a_second_time(app, organiser, coordinator, make_event):
    # AC5 guard: once a rejected request has one resubmission, the
    # original itself can't be resubmitted again (its own resubmission
    # can, forming a chain -- but that's review.py's job, not this check's).
    with app.app_context():
        original_id = make_event(
            organiser,
            status="rejected",
            name="Original Request",
            purpose="Purpose",
            description="Description",
            proposed_date=date(2026, 12, 1),
            proposed_time=time(9, 0),
            expected_attendance=50,
            capacity_needed=100,
            required_layout="theatre",
            accessibility_needs="None",
            coordinator_id=coordinator,
        )
        original = db.session.get(Event, original_id)
        review.resubmit_rejected_event(original, organiser, {})

        assert review.can_be_resubmitted(db.session.get(Event, original_id)) is False


# Significant changes in safety_check return the event to planning.
def test_significant_event_update_during_safety_check_reverts_to_planning(
    app, organiser, coordinator, make_event
):
    with app.app_context():
        event_id = make_event(
            organiser,
            status="safety_check",
            coordinator_id=coordinator,
            proposed_date=date(2026, 12, 1),
            proposed_time=time(9, 0),
        )
        event = db.session.get(Event, event_id)
        coordinator_user = db.session.get(User, coordinator)

        update_service.update_event_fields(
            event,
            coordinator_user,
            {
                "proposed_date": date(2027, 1, 15),
                "proposed_time": time(10, 0),
            },
            offline_review_confirmed=True,
        )

        assert event.proposed_date == date(2027, 1, 15)
        assert event.status == "planning"

        assert EventStatusHistory.query.filter_by(
            event_id=event_id,
            new_status="planning",
        ).count() == 1

# Significant changes in confirmed return the event to planning
def test_significant_event_update_on_confirmed_event_is_locked(
    app, organiser, coordinator, make_event
):
    with app.app_context():
        event_id = make_event(
            organiser,
            status="confirmed",
            coordinator_id=coordinator,
            proposed_date=date(2026, 12, 1),
            proposed_time=time(9, 0),
        )
        event = db.session.get(Event, event_id)
        coordinator_user = db.session.get(User, coordinator)

        with pytest.raises(update_service.EventLockedError):
            update_service.update_event_fields(
                event,
                coordinator_user,
                {
                    "proposed_date": date(2027, 1, 15),
                    "proposed_time": time(10, 0),
                },
                offline_review_confirmed=True,
            )

        assert event.status == "confirmed"
        assert event.proposed_date == date(2026, 12, 1)

        assert EventStatusHistory.query.filter_by(
            event_id=event_id,
            new_status="planning",
        ).count() == 0


def test_confirm_after_safety_approval_requires_approved_review_by_safety_officer(
    app, organiser, coordinator, make_event
):
    """Confirmation rejects non-approved decisions and reviews by non-officers."""
    with app.app_context():
        event_id = make_event(organiser, status="safety_approved")
        event = db.session.get(Event, event_id)
        non_safety_reviewer = SimpleNamespace(
            decision="rejected",
            safety_officer=SimpleNamespace(has_role=lambda role: True),
        )
        with pytest.raises(
            status_service.InvalidTransitionError,
            match="Safety check must be approved",
        ):
            status_service.confirm_after_safety_approval(
                event, non_safety_reviewer, coordinator
            )

        reviewer_without_role = SimpleNamespace(
            decision="approved",
            safety_officer=SimpleNamespace(has_role=lambda role: False),
        )
        with pytest.raises(
            status_service.InvalidTransitionError,
            match="Safety review must be performed by a Safety Officer",
        ):
            status_service.confirm_after_safety_approval(
                event, reviewer_without_role, coordinator
            )


def test_current_safety_review_handles_missing_stale_and_non_approval_reviews(
    app, organiser, make_event, monkeypatch
):
    """Only a current approval is returned, and only for displayable statuses."""
    with app.app_context():
        event_id = make_event(organiser, status="planning")
        event = db.session.get(Event, event_id)
        latest = SimpleNamespace(decision="rejected")

        monkeypatch.setattr(status_service, "_latest_safety_review", lambda _event: None)
        assert status_service.approved_safety_review_for_current_check(event) is None
        assert status_service.current_safety_review(event) is None

        monkeypatch.setattr(status_service, "_latest_safety_review", lambda _event: latest)
        monkeypatch.setattr(
            status_service, "_decided_before_current_check", lambda _event, _review: False
        )
        assert status_service.approved_safety_review_for_current_check(event) is None
        assert status_service.current_safety_review(event) is None

        latest.decision = "approved"
        monkeypatch.setattr(
            status_service, "_decided_before_current_check", lambda _event, _review: True
        )
        assert status_service.approved_safety_review_for_current_check(event) is None
        assert status_service.current_safety_review(event) is None

        monkeypatch.setattr(
            status_service, "_decided_before_current_check", lambda _event, _review: False
        )
        assert status_service.approved_safety_review_for_current_check(event) is latest
        assert status_service.current_safety_review(event) is None

        for status in ("safety_approved", "confirmed", "completed"):
            event.status = status
            assert status_service.current_safety_review(event) is latest


def test_arrangement_checks_cover_held_bookings_and_incomplete_equipment(
    app, organiser, make_event
):
    """Held bookings and incomplete equipment block safety-check readiness."""
    with app.app_context():
        event_id = make_event(organiser, status="planning", capacity_needed=100)
        event = db.session.get(Event, event_id)
        _create_venue_booking(event, organiser, status="approved")
        _create_venue_booking(event, organiser, status="held")
        assert status_service.arrangements_are_complete(event) is False

        held_event_id = make_event(organiser, status="planning", capacity_needed=100)
        held_event = db.session.get(Event, held_event_id)
        _create_venue_booking(held_event, organiser, status="held")
        assert status_service.arrangements_are_complete(held_event) is False

        no_requirements_id = make_event(organiser, status="planning")
        no_requirements = db.session.get(Event, no_requirements_id)
        assert status_service.arrangements_are_complete(no_requirements) is True

        equipment_event_id = make_event(organiser, status="planning")
        equipment_event = db.session.get(Event, equipment_event_id)
        requirement = EventEquipmentRequirement(
            equipment_type="Projector",
            quantity=2,
            status="confirmed",
            needs_recheck=True,
        )
        equipment_event.equipment_requirements.append(requirement)
        db.session.commit()
        assert status_service.arrangements_are_complete(equipment_event) is False

        requirement.needs_recheck = False
        db.session.commit()
        assert status_service.arrangements_are_complete(equipment_event) is False


def test_return_reconsider_and_revert_status_helpers_cover_no_op_and_delete_paths(
    app, organiser, coordinator, make_event, monkeypatch
):
    """Status helpers leave unaffected events alone and clear stale assessments."""
    with app.app_context():
        planning_id = make_event(organiser, status="planning")
        planning = db.session.get(Event, planning_id)
        assert status_service.return_to_planning(planning, coordinator, "No change") is planning
        assert status_service.reconsider_event_after_arrangement_loss(
            planning, coordinator, "No change"
        ) is planning

        confirmed_id = make_event(organiser, status="confirmed")
        confirmed = db.session.get(Event, confirmed_id)
        monkeypatch.setattr(status_service, "arrangements_are_complete", lambda _event: True)
        assert status_service.reconsider_event_after_arrangement_loss(
            confirmed, coordinator, "Arrangements remain complete"
        ) is confirmed

        safety_check_id = make_event(organiser, status="safety_check")
        safety_check = db.session.get(Event, safety_check_id)
        assessment = EventSafetyAssessment(
            event_id=safety_check_id,
            safety_officer_id=coordinator,
            factors={},
        )
        db.session.add(assessment)
        db.session.commit()
        assert safety_check.safety_assessment is assessment

        monkeypatch.setattr(status_service, "arrangements_are_complete", lambda _event: False)
        status_service.reconsider_event_after_arrangement_loss(
            safety_check, coordinator, "Arrangements changed"
        )
        assert safety_check.status == "planning"
        assert safety_check.safety_assessment is None

        with pytest.raises(
            status_service.InvalidTransitionError,
            match="Only a confirmed event",
        ):
            status_service.revert_to_planning(planning, coordinator, "Not confirmed")
        assert status_service.revert_to_planning(
            confirmed, coordinator, "Return to planning"
        ) is confirmed
        assert confirmed.status == "planning"


def test_change_status_releases_reservations_and_closes_reassignment_on_terminal_statuses(
    app, organiser, coordinator, make_event, monkeypatch
):
    """Cancellation releases equipment; terminal transitions close reassignment requests."""
    with app.app_context():
        event_id = make_event(organiser, status="planning")
        event = db.session.get(Event, event_id)
        releases = []
        monkeypatch.setattr(
            status_service,
            "release_equipment_reservations",
            lambda changed_event: releases.append(changed_event) or 0,
        )
        status_service.change_status(
            event, "cancelled", coordinator, notify=False
        )
        assert releases == [event]
        assert event.status == "cancelled"

        completed_id = make_event(organiser, status="confirmed")
        completed = db.session.get(Event, completed_id)
        closed_events = []
        monkeypatch.setattr(
            "app.events.services.assignment.close_reassignment_request_for_closed_event",
            lambda closed_event: closed_events.append(closed_event),
        )
        status_service.change_status(
            completed, "completed", coordinator, notify=False
        )
        assert completed.status == "completed"
        assert closed_events == [completed]