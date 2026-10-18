"""Unit tests for Event Status Management: Stories 1-4.

Story 1: Consistent status display
Story 2: Organiser views status of all their requests (HTTP-only story --
         every AC needs a real request, so it has no tests in this file;
         see the integration test file)
Story 3: Automatic transition to safety_check, then confirmed, as
         arrangements complete and a Safety Officer reviews
Story 4: Retain rejected and cancelled requests with final status visible

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
    EventSafetyReview,
    EventStatusHistory,
    STATUS_LABELS,
    UNKNOWN_STATUS_LABEL,
)
from app.models.user import User
from app.models.venue import Venue, VenueBooking
from app.venues.services import booking as venue_booking

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
#
# Acceptance criteria:
# 1. Coordinator approval moves the request to planning.
# 2. Complete venue/equipment arrangements move planning to safety_check,
#    never directly to confirmed.
# 3. Only a Safety Officer can approve, reject, or request changes;
#    approval confirms, while rejection/changes return to planning.
# 4. Arrangement loss returns safety_check/confirmed events to planning,
#    and repeated checks do not duplicate transitions.
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


def test_approval_moves_event_to_planning(app, organiser, coordinator, make_event):
    # AC1: approve_event() chains straight through to "planning".
    with app.app_context():
        event_id = make_event(organiser, status="under_review", coordinator_id=coordinator)
        event = db.session.get(Event, event_id)

        review.approve_event(event, coordinator)

        assert event.status == "planning"
        assert [entry.new_status for entry in event.status_history] == ["approved", "planning"]


def test_pending_venue_keeps_event_in_planning(app, organiser, make_event):
    # AC2: an unapproved venue booking is not a complete arrangement.
    with app.app_context():
        event_id = make_event(organiser, status="planning", capacity_needed=100)
        event = db.session.get(Event, event_id)
        _create_venue_booking(event, organiser)

        status_service.try_advance_to_safety_check(event, changed_by_id=organiser)

        assert event.status == "planning"


def test_venue_approval_moves_event_to_safety_check_without_equipment(
    app, organiser, make_user, make_event
):
    # AC2: with no equipment requested, an approved venue alone is enough
    # to complete arrangements and move to safety_check (never confirmed).
    with app.app_context():
        venue_staff_id = make_user(
            "status-venue-staff@test.com",
            ["venue_staff"],
        )
        event_id = make_event(organiser, status="planning", capacity_needed=100)
        event = db.session.get(Event, event_id)
        booking = _create_venue_booking(
            event,
            organiser,
            venue_owner_id=venue_staff_id,
        )

        venue_booking.approve_booking(booking, decided_by=venue_staff_id)

        assert event.status == "safety_check"
        assert EventStatusHistory.query.filter_by(
            event_id=event_id, new_status="safety_check"
        ).count() == 1


def test_pending_equipment_prevents_safety_check_after_venue_approval(
    app, organiser, make_user, make_event
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


def test_last_equipment_reservation_moves_event_to_safety_check(
    app, organiser, coordinator, make_event
):
    # AC2: reserving the last outstanding equipment requirement is what
    # finally completes arrangements and triggers the move.
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

        assert event.status == "safety_check"


def test_only_safety_officer_approval_confirms_event(app, organiser, make_user, make_event):
    # AC3: a Safety Officer's "approved" decision is the only way to
    # reach "confirmed".
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

        assert event.status == "confirmed"
        review_record = EventSafetyReview.query.filter_by(event_id=event_id).one()
        assert review_record.decision == "approved"
        assert review_record.safety_officer_id == officer_id
        assert event.to_dict()["safetyReviews"][0]["comments"] == "Egress and access reviewed"


@pytest.mark.parametrize("decision", ["rejected", "changes_requested"])
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


def test_rechecking_ready_event_does_not_duplicate_safety_transition_history(
    app, organiser, make_event
):
    # AC4: calling the "try advance" check twice on an already-advanced
    # event must not create a second safety_check history row.
    with app.app_context():
        event_id = make_event(organiser, status="planning")
        event = db.session.get(Event, event_id)

        status_service.try_advance_to_safety_check(event, changed_by_id=organiser)
        status_service.try_advance_to_safety_check(event, changed_by_id=organiser)

        assert event.status == "safety_check"
        assert EventStatusHistory.query.filter_by(
            event_id=event_id, new_status="safety_check"
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

        status_service.try_advance_to_safety_check(event, changed_by_id=organiser)

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

        assert event.status == "safety_check"


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


def test_safety_approval_records_officer_in_status_history(app, organiser, make_user, make_event):
    # AC3 regression: the status-history row for safety_check -> confirmed
    # must record the deciding Safety Officer, not NULL.
    with app.app_context():
        officer_id = make_user("audit-safety@test.com", ["safety_officer"])
        officer = db.session.get(User, officer_id)
        event_id = make_event(organiser, status="safety_check")
        event = db.session.get(Event, event_id)

        safety.review_safety_check(
            event, officer, "approved", "Checked",
            assessed_factors=sorted(safety.SAFETY_FACTORS),
        )

        confirm_entry = EventStatusHistory.query.filter_by(
            event_id=event_id, new_status="confirmed"
        ).one()
        assert confirm_entry.changed_by == officer_id


# =====================================================================
# Story 4: Retain rejected and cancelled requests with final status visible
# =====================================================================

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