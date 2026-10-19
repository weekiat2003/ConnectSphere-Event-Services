"""Advisory warnings for overlapping venue booking requests.

Computed on demand (never stored) so it always reflects the current situation.
Only returns counts and a period, never other events' names or organisers.
"""
from datetime import timedelta

from app.models.venue import BOOKING_APPROVED, BOOKING_PENDING, VenueBooking
from app.venues.services.availability import compute_booking_window

POSSIBLE_CONFLICT = "possible_conflict"
VENUE_CONFIRMED = "venue_confirmed"


def _overlaps(booking, venue, status):
    """Overlap intervals (padded for setup/turnaround, as in conflict detection)
    between `booking` and other-event bookings of the given status."""
    start, end = compute_booking_window(booking, venue)
    buffer = timedelta(minutes=(venue.setup_minutes or 0) + (venue.turnaround_minutes or 0))
    candidates = VenueBooking.query.filter(
        VenueBooking.venue_id == venue.id,
        VenueBooking.status == status,
        VenueBooking.event_id != booking.event_id,   # same event never counts
        VenueBooking.id != booking.id,
        VenueBooking.start_datetime < end + buffer,  # cheap SQL pre-filter
        VenueBooking.end_datetime > start - buffer,
    ).all()

    hits = []
    for other in candidates:
        o_start, o_end = compute_booking_window(other, venue)
        lo, hi = max(start, o_start), min(end, o_end)
        if lo < hi:
            hits.append((lo, hi))
    return hits


def _period(hits):
    lo = min(h[0] for h in hits)
    hi = max(h[1] for h in hits)
    if lo.date() == hi.date():
        return f"{lo:%Y-%m-%d}, {lo:%H:%M} to {hi:%H:%M}"
    return f"{lo:%Y-%m-%d %H:%M} to {hi:%Y-%m-%d %H:%M}"


def get_advisory(booking):
    """Advisory for a PENDING booking, else None.

    - another event is now confirmed for an overlapping period -> VENUE_CONFIRMED
      (replaces the pending-overlap warning; the request can no longer be approved)
    - other events' pending requests overlap -> POSSIBLE_CONFLICT
    - otherwise None. Rejected/withdrawn/cancelled/same-event bookings never count.
    """
    if booking.status != BOOKING_PENDING:
        return None
    venue = booking.venue
    if venue is None:
        return None

    confirmed = _overlaps(booking, venue, BOOKING_APPROVED)
    if confirmed:
        period = _period(confirmed)
        return {
            "type": VENUE_CONFIRMED,
            "venue": venue.name,
            "period": period,
            "canApprove": False,
            "message": (
                f"{venue.name} is now confirmed for another event for {period}. "
                f"This request can no longer be approved."
            ),
        }

    pending = _overlaps(booking, venue, BOOKING_PENDING)
    if pending:
        period = _period(pending)
        count = len(pending)
        noun = "request" if count == 1 else "requests"
        return {
            "type": POSSIBLE_CONFLICT,
            "venue": venue.name,
            "period": period,
            "overlapCount": count,
            "canApprove": True,
            "message": (
                f"Possible conflict: {venue.name} has {count} other pending {noun} "
                f"overlapping {period}. Approval is not guaranteed. "
                f"This request stays pending and can still be reviewed or withdrawn."
            ),
        }
    return None