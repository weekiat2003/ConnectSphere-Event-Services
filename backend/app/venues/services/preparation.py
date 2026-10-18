"""
Venue preparation-progress updates by Venue Staff (US-2). Distinct from
venue booking approval/rejection (app/venues/services/booking.py) and never
subject to the Event Information Management lock (US-4), since it isn't
core event information.
"""
from app.common.time import utcnow
from app.extensions import db
from app.models.venue import VenueBooking

PREPARATION_FIELDS = {"setup_status", "venue_notes"}
ACTIVE_BOOKING_STATUSES = {"approved", "held"}
SETUP_STATUSES = {"pending", "in_progress", "done"}


class PreparationUpdateError(Exception):
    pass


def update_venue_preparation(booking: VenueBooking, user, changes: dict) -> VenueBooking:
    if not isinstance(changes, dict):
        raise PreparationUpdateError("Preparation changes must be an object")
    if not changes:
        raise PreparationUpdateError("At least one preparation field is required")

    if not user.has_role("venue_staff"):
        raise PermissionError("Only Venue Staff can update venue preparation information.")

    if booking.venue.created_by != user.id:
        raise PermissionError("You can only update preparation information for venues you manage.")

    if booking.status not in ACTIVE_BOOKING_STATUSES:
        raise PreparationUpdateError("Venue preparation can only be updated for an approved or held booking.")
    # AC3: a confirmed event's booking stays updatable -- preparation
    # progress is gated by the booking's own status, not the event's status.

    unknown_fields = set(changes) - PREPARATION_FIELDS
    if unknown_fields:
        raise PreparationUpdateError(f"Cannot update fields: {', '.join(sorted(unknown_fields))}")

    if "setup_status" in changes and (
        not isinstance(changes["setup_status"], str) or changes["setup_status"] not in SETUP_STATUSES
    ):
        raise PreparationUpdateError("Setup status must be pending, in_progress, or done.")
    if "venue_notes" in changes and changes["venue_notes"] is not None and not isinstance(changes["venue_notes"], str):
        raise PreparationUpdateError("Venue notes must be text.")

    for field, value in changes.items():
        setattr(booking, field, value)

    booking.updated_at = utcnow()
    db.session.add(booking)
    db.session.commit()
    return booking