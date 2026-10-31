"""
Event Status Management
------------------------
"""
from sqlalchemy import func

from app.common.text_validation import validate_descriptive_text
from app.common.time import utcnow
from app.extensions import db
from app.models.equipment import EquipmentReservation
from app.notifications.services import triggers as notifications
from app.models.event import Event, EventSafetyReview, EventStatusHistory
from app.models.venue import (
    BOOKING_APPROVED,
    VenueBooking,
    ACTIVE_BOOKING_STATUSES,
    BOOKING_HELD,
    BOOKING_RELEASED,
    BOOKING_PENDING
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

CLOSED_STATUSES = ("cancelled", "rejected", "completed")
CANCELLABLE_STATUSES = ("approved", "planning", "confirmed", "safety_check")
CANCEL_STATUS_MESSAGE = "An event can only be cancelled while it is approved, planning or in safety check"


class InvalidTransitionError(Exception):
    pass


def change_status(event: Event, new_status: str, changed_by_id: int, reason: str = None,
                  notify: bool = True) -> Event:
    """notify=False lets a caller that sends its own, more detailed notification
    (e.g. a safety decision) skip the generic one for this transition."""
    allowed = ALLOWED_TRANSITIONS.get(event.status, set())
    if new_status == "safety_check" and not arrangements_are_complete(event):
        raise InvalidTransitionError(
            "Cannot enter the safety check until all venue and equipment arrangements are approved"
        )
    if new_status not in allowed:
        raise InvalidTransitionError(f"Cannot transition event from '{event.status}' to '{new_status}'")

    if new_status == "cancelled":
        release_equipment_reservations(event)

    return _record_status_change(event, new_status, changed_by_id, reason, notify=notify)

# Coordinator confirms an event after a safety officer has approved it.
def confirm_after_safety_approval(event: Event, review: EventSafetyReview, changed_by_id: int) -> Event:
    if event.status != "safety_check":
        raise InvalidTransitionError("Only an event awaiting safety check can be confirmed")
    if review.decision != "approved":
        raise InvalidTransitionError("Safety check must be approved before the event can be confirmed")
    if not review.safety_officer.has_role("safety_officer"):
        raise InvalidTransitionError("Safety review must be performed by a Safety Officer")
    return _record_status_change(event, "confirmed", changed_by_id, reason="Confirmed by Coordinator after safety approval")

# Takes the latest review, and if it is an approval made after the most recent entry into Safety Check, it counts. 
# If it was made before, it is a leftover from an earlier check and is ignored.
def approved_safety_review_for_current_check(event: Event):
    """Return the approval for the current safety check, or None if undecided."""

    # Count how many times this event entered the safety-check stage.
    safety_check_entries = (
        EventStatusHistory.query
        .filter_by(event_id=event.id, new_status="safety_check")
        .count()
    )

    # Count how many safety reviews have been submitted.
    safety_reviews = (
        EventSafetyReview.query
        .filter_by(event_id=event.id)
        .count()
    )

    # Fewer reviews than entries means the latest check has no decision yet.
    if safety_reviews < safety_check_entries:
        return None

    latest = (
        EventSafetyReview.query
        .filter_by(event_id=event.id)
        .order_by(EventSafetyReview.id.desc())
        .first()
    )

    if latest is None or latest.decision != "approved":
        return None

    return latest


def _record_status_change(event: Event, new_status: str, changed_by_id: int, reason: str = None,
                          notify: bool = True) -> Event:
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
    # Notification System: every recorded transition goes through here, so this
    # one hook covers organiser, Lead, Safety Officer, Tech Support and Attendee
    # notifications. Saved in the same commit as the status change.
    if notify:
        notifications.on_event_status_changed(event, old_status, new_status, changed_by_id, reason)
    if new_status in CLOSED_STATUSES:
        # Imported here: assignment imports this module.
        from app.events.services.assignment import close_reassignment_request_for_closed_event
        close_reassignment_request_for_closed_event(event)
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
        # Pending or held booking still blocks. Expired and released holds no longer block.
        if any(b.status in (BOOKING_PENDING, BOOKING_HELD) for b in venue_bookings):
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


class EventActionError(ValueError):
    """`errors` maps a field name ("reason" / "event") to a message."""

    def __init__(self, errors: dict):
        self.errors = errors
        super().__init__("; ".join(errors.values()))


def validate_cancellation_reason(reason) -> str:
    """Same rules as clarification comments."""
    try:
        validate_descriptive_text(reason if isinstance(reason, str) else "", "reason")
    except ValueError as problem:
        raise EventActionError({"reason": str(problem)})
    return reason.strip()


def release_equipment_reservations(event: Event) -> int:
    """Releases the event's reserved equipment. Does not commit; the caller does."""
    reservations = EquipmentReservation.query.filter_by(
        event_id=event.id, status="reserved"
    ).all()
    for reservation in reservations:
        reservation.status = "released"
    return len(reservations)


def _release_arrangements(event: Event, coordinator_id: int, reason: str, now):
    """Release the cancelled event's live venue bookings (pending, approved,
    held) and equipment reservations. Does not commit; the caller does."""
    bookings = VenueBooking.query.filter(
        VenueBooking.event_id == event.id,
        VenueBooking.status.in_(ACTIVE_BOOKING_STATUSES),
    ).all()
    for booking in bookings:
        if booking.status == BOOKING_HELD:
            booking.hold_released_at = now
        booking.status = BOOKING_RELEASED
        booking.decided_by = coordinator_id
        booking.decided_at = now
        booking.decision_reason = f"Event cancelled: {reason}"

    released_equipment = release_equipment_reservations(event)

    return len(bookings), released_equipment


def cancel_event(event_id: int, coordinator_id: int, reason, dry_run: bool = False) -> Event:
    """Cancel an event. A reason is required. dry_run runs every check and writes nothing."""
    query = db.session.query(Event).filter_by(id=event_id)
    if not dry_run:
        query = query.with_for_update()  # of two simultaneous cancels, the second sees "cancelled"
    event = query.first()

    if event is None:
        raise LookupError("Event not found")
    if event.coordinator_id != coordinator_id:
        raise PermissionError("Only the Coordinator assigned to this event can cancel it")
    if event.status not in CANCELLABLE_STATUSES:
        raise EventActionError({"event": CANCEL_STATUS_MESSAGE})

    reason = validate_cancellation_reason(reason)
    if dry_run:
        return event

    old_status = event.status
    now = utcnow()
    event.status = "cancelled"
    db.session.add(EventStatusHistory(
        event_id=event.id,
        old_status=old_status,
        new_status="cancelled",
        changed_by=coordinator_id,
        reason=reason,
        changed_at=now,
    ))
    _release_arrangements(event, coordinator_id, reason, now)
    notifications.on_event_status_changed(event, old_status, "cancelled", coordinator_id, reason)
    from app.events.services.assignment import close_reassignment_request_for_closed_event
    close_reassignment_request_for_closed_event(event)
    db.session.commit()
    return event