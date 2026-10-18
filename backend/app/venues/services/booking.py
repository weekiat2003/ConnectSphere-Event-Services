"""
Venue Booking Request / Venue Booking Approval / Booking Conflict Detection.

Only APPROVED bookings block a venue due to a booking conflict.
Pending conflicts are resolved outside the system by default.

An event can request multiple different venues, but it cannot have more than
one active (pending or approved) booking for the same venue.

Each booking carries its own start_datetime/end_datetime, so conflicts are
checked booking-against-booking, not event-against-event.
"""

from app.common.time import utcnow
from app.extensions import db
from app.models.event import Event
from app.models.venue import (
    ACTIVE_BOOKING_STATUSES as ACTIVE_STATUSES,
    BOOKING_APPROVED as APPROVED,
    BOOKING_CANCELLED as CANCELLED,
    BOOKING_PENDING as PENDING,
    BOOKING_REJECTED as REJECTED,
    BOOKING_WITHDRAWN as WITHDRAWN,
    BOOKING_HELD as HELD,
    BOOKING_EXPIRED as EXPIRED,
    BOOKING_RELEASED as RELEASED,
    Venue,
    VenueBooking,
)
from app.venues.services.availability import compute_booking_window


def submit_booking_request(
    event: Event,
    venue: Venue,
    user_id: int,
) -> VenueBooking:
    """
    Submit a booking request for a venue.

    An event may have more than one venue booking, but it cannot
    have another active booking for the same venue.
    """

    existing = VenueBooking.query.filter(
        VenueBooking.event_id == event.id,
        VenueBooking.venue_id == venue.id,
        VenueBooking.status.in_(ACTIVE_STATUSES),
    ).first()

    if existing:
        raise ValueError(
            "This event already has an active booking for this venue; "
            "withdraw it before requesting it again"
        )

    booking = VenueBooking(
        event_id=event.id,
        venue_id=venue.id,
        requested_by=user_id,
        status=PENDING,
    )

    db.session.add(booking)
    db.session.commit()

    return booking



def withdraw_booking_request(
    booking: VenueBooking,
    user_id: int,
) -> VenueBooking:
    """Withdraw a pending booking request owned by this coordinator."""

    # AC6: Only the coordinator who submitted the request
    # can withdraw it.
    if booking.requested_by != user_id:
        raise ValueError(
            "You are not authorised to withdraw this booking request"
        )

    # AC3 & AC4: Only pending bookings can be withdrawn.
    # Use a conditional database update to prevent a stale status
    # check from overwriting a staff decision.
    try:
        updated = (
            VenueBooking.query
            .filter(
                VenueBooking.id == booking.id,
                VenueBooking.requested_by == user_id,
                VenueBooking.status == PENDING,
            )
            .update(
                {
                    VenueBooking.status: WITHDRAWN,
                    VenueBooking.decided_by: user_id,
                    VenueBooking.decided_at: utcnow(),
                },
                synchronize_session=False,
            )
        )

        if updated == 0:
            db.session.rollback()
            raise ValueError(
                "This booking request has already been decided "
                "or is no longer pending"
            )

        db.session.commit()

        db.session.refresh(booking)
        return booking

    except ValueError:
        raise

    except Exception:
        db.session.rollback()
        raise


def cancel_booking(
    booking: VenueBooking,
    decided_by: int,
    reason: str = None,
) -> VenueBooking:
    """Cancel an approved booking and reconsider its event arrangements."""
    if reason is not None and not isinstance(reason, str):
        raise ValueError("Reason must be text")
    if reason is not None and len(reason) > 500:
        raise ValueError("Reason must not exceed 500 characters")

    reason = reason.strip() or None if reason is not None else None

    try:
        # Serialize cancellation with approvals for this venue and reload the
        # booking so a stale request cannot overwrite a newer decision.
        venue = (
            db.session.query(Venue)
            .filter(Venue.id == booking.venue_id)
            .with_for_update()
            .first()
        )
        if venue is None:
            raise ValueError("Venue not found")

        if venue.created_by != decided_by:
            raise PermissionError("You cannot cancel bookings for another staff member's venue")

        current = (
            db.session.query(VenueBooking)
            .populate_existing()
            .filter(VenueBooking.id == booking.id)
            .first()
        )
        if current is None:
            raise ValueError("Booking not found")
        if current.status != APPROVED:
            raise ValueError("Only approved bookings can be cancelled")

        updated = (
            VenueBooking.query
            .filter(
                VenueBooking.id == current.id,
                VenueBooking.status == APPROVED,
            )
            .update(
                {
                    VenueBooking.status: CANCELLED,
                    VenueBooking.decided_by: decided_by,
                    VenueBooking.decision_reason: reason,
                    VenueBooking.decided_at: utcnow(),
                },
                synchronize_session="fetch",
            )
        )
        if updated != 1:
            raise ValueError("This booking is no longer approved")

        event = db.session.get(Event, current.event_id)
        if event is not None:
            from app.events.services.status import (
                reconsider_event_after_arrangement_loss,
            )

            change_reason = f"Venue booking #{current.id} was cancelled"
            if reason:
                change_reason += f": {reason}"
            reconsider_event_after_arrangement_loss(
                event,
                changed_by_id=decided_by,
                reason=change_reason,
            )

        db.session.commit()
        db.session.refresh(current)
        return current
    except Exception:
        db.session.rollback()
        raise



def has_confirmed_conflict(
    venue_id: int,
    candidate: VenueBooking,
    exclude_booking_id: int = None,
) -> bool:
    """
    Return True if approving the candidate would double-book
    the venue against another APPROVED booking.

    The function name is kept as has_confirmed_conflict for
    compatibility with existing code.
    """

    venue = Venue.query.get(venue_id)

    if not venue:
        return False

    window = compute_booking_window(
        candidate,
        venue,
    )

    if window is None:
        return False

    start, end = compute_booking_window(
        candidate,
        venue,
    )
    
    approved_bookings = VenueBooking.query.filter(
        VenueBooking.venue_id == venue_id,
        db.or_(VenueBooking.status == APPROVED, db.and_(VenueBooking.status == HELD, VenueBooking.hold_expires_at > utcnow())),
    )

    if exclude_booking_id:
        approved_bookings = approved_bookings.filter(
            VenueBooking.id != exclude_booking_id
        )

    for other in approved_bookings.all():
        other_start, other_end = compute_booking_window(
            other,
            venue,
        )

        if other_start < end and start < other_end:
            return True

    return False



def approve_booking(booking: VenueBooking, decided_by: int) -> VenueBooking:
    """Approve under a venue-row lock to serialize approvals for this venue."""
    try:
        # MySQL/InnoDB: competing approvals for the same venue wait here.
        venue = (
            db.session.query(Venue)
            .filter(Venue.id == booking.venue_id)
            .with_for_update()
            .first()
        )

        if venue is None:
            raise ValueError("Venue not found")

        if venue.created_by != decided_by:
            raise PermissionError(
                "You cannot approve requests for another staff member's venue"
            )

        # Re-read after acquiring the lock.
        current = (
            db.session.query(VenueBooking)
            .populate_existing()
            .filter(VenueBooking.id == booking.id)
            .first()
        )

        if current is None:
            raise ValueError("Booking not found")

        if current.status not in (PENDING, HELD):
            raise ValueError("This booking request has already been decided")

        if current.status == HELD and (
            not current.hold_expires_at
            or current.hold_expires_at <= utcnow()
        ):
            raise ValueError("This hold has expired")

        start, end = compute_booking_window(current, venue)
        now = utcnow()

        # Check approved bookings and active tentative holds.
        conflicting_bookings = (
            VenueBooking.query
            .filter(
                VenueBooking.venue_id == venue.id,
                VenueBooking.id != current.id,
                db.or_(
                    VenueBooking.status == APPROVED,
                    db.and_(
                        VenueBooking.status == HELD,
                        VenueBooking.hold_expires_at > now
                    )
                )
            )
            .all()
        )

        for other in conflicting_bookings:
            other_start, other_end = compute_booking_window(other, venue)

            if other_start < end and start < other_end:
                event_name = (
                    other.event.name
                    if other.event
                    else f"Event #{other.event_id}"
                )

                raise ValueError(
                    f"Conflicts with booking #{other.id} ({event_name}), "
                    f"{other.start_datetime.isoformat()} to "
                    f"{other.end_datetime.isoformat()}"
                )

        # Conditional update protects against stale decisions.
        updated = (
            VenueBooking.query
            .filter(
                VenueBooking.id == current.id,
                VenueBooking.status.in_((PENDING, HELD))
            )
            .update(
                {
                    VenueBooking.status: APPROVED,
                    VenueBooking.decided_by: decided_by,
                    VenueBooking.decided_at: utcnow()
                },
                synchronize_session="fetch"
            )
        )

        if updated != 1:
            raise ValueError(
                "This booking request has already been decided"
            )

        event = db.session.get(Event, current.event_id)

        if event is not None:
            from app.events.services.status import try_advance_to_safety_check

            try_advance_to_safety_check(
                event,
                changed_by_id=decided_by
            )

        db.session.commit()
        db.session.refresh(current)

        return current

    except Exception:
        db.session.rollback()
        raise



def reject_booking(
    booking: VenueBooking,
    decided_by: int,
    reason: str = None,
    alternative: str = None,
) -> VenueBooking:
    """Reject a pending booking, with optional reason and alternative."""
    for label, value in (("Reason", reason), ("Alternative suggestion", alternative)):
        if value is not None and not isinstance(value, str):
            raise ValueError(f"{label} must be text")
        if value is not None and len(value) > 500:
            raise ValueError(f"{label} must not exceed 500 characters")

    reason = reason.strip() or None if reason is not None else None
    alternative = alternative.strip() or None if alternative is not None else None

    try:
        venue = (db.session.query(Venue)
                 .filter(Venue.id == booking.venue_id)
                 .with_for_update().first())
        if venue is None:
            raise ValueError("Venue not found")
        if venue.created_by != decided_by:
            raise PermissionError("You cannot reject requests for another staff member's venue")

        current = (db.session.query(VenueBooking)
                   .populate_existing()
                   .filter(VenueBooking.id == booking.id).first())
        if current is None:
            raise ValueError("Booking not found")
        if current.status != PENDING:
            raise ValueError("This booking request has already been decided")

        updated = (VenueBooking.query
                   .filter(VenueBooking.id == current.id, VenueBooking.status == PENDING)
                   .update({VenueBooking.status: REJECTED,
                            VenueBooking.decided_by: decided_by,
                            VenueBooking.decision_reason: reason,
                            VenueBooking.alternative_suggestion: alternative,
                            VenueBooking.decided_at: utcnow()},
                           synchronize_session=False))
        if updated != 1:
            raise ValueError("This booking request has already been decided")
        db.session.commit()
        db.session.refresh(current)
        return current
    except Exception:
        db.session.rollback()
        raise


# Tentative holds use UTC-naive datetimes, consistent with app.common.time.utcnow.
def manage_hold(booking_id, staff_id, action, expiry=None):
    """Place, extend or release a hold under the venue row lock."""
    try:
        current = db.session.get(VenueBooking, booking_id)
        if current is None:
            raise LookupError("Booking not found")
        venue = db.session.query(Venue).filter_by(id=current.venue_id).with_for_update().first()
        if venue is None:
            raise LookupError("Venue not found")
        if venue.created_by != staff_id:
            raise PermissionError("You cannot manage another staff member's hold")
        db.session.refresh(current)
        now = utcnow()
        if action in ("place", "extend"):
            if not isinstance(expiry, __import__('datetime').datetime) or expiry <= now:
                raise ValueError("Hold expiry must be a future date and time")
            if (action == "place" and current.status != PENDING) or (action == "extend" and (current.status != HELD or current.hold_expires_at <= now)):
                raise ValueError("Booking is not eligible for this hold action")
            if has_confirmed_conflict(venue.id, current, exclude_booking_id=current.id):
                raise ValueError("Venue conflicts with an existing confirmed booking or active hold")
            current.status = HELD
            current.hold_expires_at = expiry
            current.hold_warning_sent_at = None
            current.hold_expired_notified_at = None
        elif action == "release":
            if current.status != HELD or not current.hold_expires_at or current.hold_expires_at <= now:
                raise ValueError("Only an active hold can be released")
            current.status = RELEASED
            current.hold_released_at = now
        else:
            raise ValueError("Invalid hold action")
        db.session.commit()
        db.session.refresh(current)
        return current
    except Exception:
        db.session.rollback()
        raise

def expire_due_holds(now=None):
    """Persist expired holds; call from a scheduled job, not as a prerequisite for availability."""
    now = now or utcnow()
    due = VenueBooking.query.filter(VenueBooking.status == HELD, VenueBooking.hold_expires_at <= now).all()
    for item in due:
        item.status = EXPIRED
    db.session.commit()
    return len(due)
