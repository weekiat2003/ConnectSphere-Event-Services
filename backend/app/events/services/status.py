"""
Event Status Management
------------------------
Owns the status-transition rules for the Event Status Management epic:
- Display current event status consistently (single source of truth: Event.status)
- Automatic transition to Confirmed once arrangements are complete
- Revert a confirmed event to Planning on major change
- Retain rejected and cancelled requests with final status visible (never deleted)
"""
from sqlalchemy import func

from app.common.time import utcnow
from app.common.text_validation import validate_descriptive_text
from app.extensions import db
from app.models.equipment import EquipmentReservation
from app.models.event import Event, EventSafetyReview, EventStatusHistory
from app.models.venue import (
    BOOKING_APPROVED,
    BOOKING_CANCELLED,
    BOOKING_WITHDRAWN,
    BOOKING_REJECTED,
    VenueBooking,
)
from app.models.change_request import ChangeRequest


ALLOWED_TRANSITIONS = {
    "draft": {"submitted"},
    "submitted": {"under_review", "approved", "rejected", "cancelled"},
    "under_review": {"approved", "rejected", "cancelled"},
    "approved": {"planning", "cancelled"},
    "planning": {"safety_check", "cancelled"},
    "safety_check": {"planning", "cancelled"},
    "confirmed": {"planning", "completed", "cancelled"},
    "completed": set(),
    "cancelled": set(),
    "rejected": set(),
}

CANCELLABLE_STATUSES = (
    "submitted",
    "under_review",
    "approved",
    "planning",
    "confirmed",
)

CANCEL_STATUS_MESSAGE = (
    "Only a submitted, under review, approved, planning or confirmed event "
    "can be cancelled"
)


def can_cancel_event(event: Event, coordinator_id: int) -> bool:
    return (
        event.coordinator_id == coordinator_id
        and event.status in CANCELLABLE_STATUSES
    )


def ensure_not_cancelled(event: Event) -> None:
    if event.status == "cancelled":
        raise PermissionError("A cancelled event cannot be changed")


class InvalidTransitionError(Exception):
    pass


def change_status(event: Event, new_status: str, changed_by_id: int, reason: str = None) -> Event:
    allowed = ALLOWED_TRANSITIONS.get(event.status, set())
    if new_status not in allowed:
        raise InvalidTransitionError(f"Cannot transition event from '{event.status}' to '{new_status}'")

    return _record_status_change(event, new_status, changed_by_id, reason)

def cancel_event(
    event: Event,
    coordinator_id: int,
    reason: str,
    dry_run: bool = False,
) -> Event:
    """Cancel an event, release active arrangements, and close registration.

    The event and its historical records remain visible. This action is final:
    a cancelled event cannot be reopened.
    """
    if event.coordinator_id != coordinator_id:
        raise PermissionError(
            "Only the assigned Coordinator can cancel this event"
        )

    if event.status not in CANCELLABLE_STATUSES:
        raise InvalidTransitionError(CANCEL_STATUS_MESSAGE)

    try:
        validate_descriptive_text(
            reason if isinstance(reason, str) else "",
            "cancellation reason",
        )
    except ValueError as problem:
        raise ValueError(str(problem))

    if dry_run:
        return event

    old_status = event.status
    now = utcnow()

    event.status = "cancelled"
    event.registration_closed_at = now

    db.session.add(
        EventStatusHistory(
            event_id=event.id,
            old_status=old_status,
            new_status="cancelled",
            changed_by=coordinator_id,
            reason=reason.strip(),
            changed_at=now,
        )
    )

    VenueBooking.query.filter(
        VenueBooking.event_id == event.id,
        VenueBooking.status.in_(("pending", "approved")),
    ).update(
        {
            "status": BOOKING_CANCELLED,
            "decided_by": coordinator_id,
            "decision_reason": f"Event cancelled: {reason.strip()}",
            "decided_at": now,
        },
        synchronize_session=False,
    )

    EquipmentReservation.query.filter(
        EquipmentReservation.event_id == event.id,
        EquipmentReservation.status == "reserved",
    ).update(
        {"status": "released"},
        synchronize_session=False,
    )

    ChangeRequest.query.filter(
        ChangeRequest.event_id == event.id,
        ChangeRequest.status.in_(("pending", "re_review")),
    ).update(
        {
            "status": "rejected",
            "coordinator_id": coordinator_id,
            "decision_reason": "Event cancelled",
            "decided_at": now,
        },
        synchronize_session=False,
    )

    db.session.commit()
    return event

CANCELLABLE_STATUSES = (
    "submitted",
    "under_review",
    "approved",
    "planning",
    "confirmed",
)

CANCEL_STATUS_MESSAGE = (
    "Only a submitted, under review, approved, planning or confirmed event "
    "can be cancelled"
)


def can_cancel_event(event: Event, coordinator_id: int) -> bool:
    return (
        event.coordinator_id == coordinator_id
        and event.status in CANCELLABLE_STATUSES
    )


def ensure_not_cancelled(event: Event) -> None:
    if event.status == "cancelled":
        raise PermissionError("A cancelled event cannot be changed")

def confirm_after_safety_approval(event: Event, review: EventSafetyReview) -> Event:
    if event.status != "safety_check":
        raise InvalidTransitionError("Only an event awaiting a safety check can be confirmed")
    if (
        review.event_id != event.id
        or review.decision != "approved"
        or not review.safety_officer.has_role("safety_officer")
    ):
        raise InvalidTransitionError("A Safety Officer approval is required before confirmation")

    return _record_status_change(
        event,
        "confirmed",
        review.safety_officer.id,
        reason="Safety check approved",
    )


def _record_status_change(event: Event, new_status: str, changed_by_id: int, reason: str = None) -> Event:
    old_status = event.status
    event.status = new_status
    db.session.add(
        EventStatusHistory(
            event_id=event.id,
            old_status=old_status,
            new_status=new_status,
            changed_by=changed_by_id,
            reason=reason,
        )
    )
    db.session.commit()
    return event


def try_advance_to_safety_check(event: Event, changed_by_id: int) -> Event:
    if event.status != "planning":
        return event

    if not arrangements_are_complete(event):
        return event

    return change_status(
        event,
        "safety_check",
        changed_by_id,
        reason="All required venue and equipment arrangements are complete; safety review required",
    )


def arrangements_are_complete(event: Event) -> bool:
    """Check actual venue bookings and equipment reservations, not request fields."""
    venue_required = bool(
        event.capacity_needed
        or event.required_layout
        or event.accessibility_needs
        or event.required_facilities
    )
    venue_bookings = VenueBooking.query.filter_by(event_id=event.id).all()
    if venue_required or venue_bookings:
        if not any(booking.status == BOOKING_APPROVED for booking in venue_bookings):
            return False
        if any(
            booking.status not in (
                BOOKING_APPROVED,
                BOOKING_WITHDRAWN,
                BOOKING_CANCELLED,
                BOOKING_REJECTED
            )
            for booking in venue_bookings
        ):
            return False

    for requirement in event.equipment_requirements:
        reserved_quantity = (
            db.session.query(func.coalesce(func.sum(EquipmentReservation.quantity), 0))
            .filter_by(
                event_id=event.id,
                equipment_requirement_id=requirement.id,
                status="reserved",
            )
            .scalar()
        )
        if reserved_quantity < requirement.quantity:
            return False

    return True


def reconsider_event_after_arrangement_loss(event: Event, changed_by_id: int, reason: str) -> Event:
    """Return an event to planning if a required arrangement is lost."""
    if event.status in ("safety_check", "confirmed") and not arrangements_are_complete(event):
        return change_status(event, "planning", changed_by_id, reason=reason)
    return event


def revert_to_planning(event: Event, changed_by_id: int, reason: str) -> Event:
    if event.status != "confirmed":
        raise InvalidTransitionError("Only a confirmed event can be reverted to planning")
    return change_status(event, "planning", changed_by_id, reason=reason)
