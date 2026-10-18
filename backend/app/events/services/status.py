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


class InvalidTransitionError(Exception):
    pass


def change_status(event: Event, new_status: str, changed_by_id: int, reason: str = None) -> Event:
    allowed = ALLOWED_TRANSITIONS.get(event.status, set())
    if new_status not in allowed:
        raise InvalidTransitionError(f"Cannot transition event from '{event.status}' to '{new_status}'")

    return _record_status_change(event, new_status, changed_by_id, reason)


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
