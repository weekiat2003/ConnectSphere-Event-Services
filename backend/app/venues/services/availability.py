"""Venue Availability Calendar epic.

Week 7 change #1 (Venue Setup and Turnaround Time): a venue's effective
busy window is no longer just the event's advertised start/end -- it is
padded by the venue's setup_minutes before and turnaround_minutes after.
compute_booking_window() is the single source of truth for this and is
reused by booking.py's conflict detection so the two can never drift apart.

"""
from datetime import datetime, timedelta, time
import re

from app.extensions import db
from app.common.time import utcnow
from app.models.venue import (
    BOOKING_APPROVED,
    BOOKING_HELD,
    Venue,
    VenueAvailabilityFlag,
    VenueBooking,
    VenueUnavailability,
)
_HOURS_PATTERN = re.compile(r"(\d{1,2}):(\d{2})\s*[-\u2013\u2014]\s*(\d{1,2}):(\d{2})")


def parse_operating_hours(venue: Venue):
    """Return (opens, closes) as times, or None when there is no usable restriction."""
    match = _HOURS_PATTERN.fullmatch((getattr(venue, "operating_hours", None) or "").strip())
    if not match:
        return None
    open_h, open_m, close_h, close_m = (int(g) for g in match.groups())
    if open_h > 23 or close_h > 23 or open_m > 59 or close_m > 59:
        return None
    opens, closes = time(open_h, open_m), time(close_h, close_m)
    if closes <= opens:
        return None
    return opens, closes


def fits_operating_hours(venue: Venue, start_time, end_time=None) -> bool:
    hours = parse_operating_hours(venue)
    if hours is None:
        return True
    opens, closes = hours
    if end_time is None:
        return opens <= start_time < closes
    return opens <= start_time and end_time <= closes


def pad_window(start, end, venue: Venue):
    """Pad a start/end by the venue's setup and turnaround time."""
    effective_start = start - timedelta(minutes=venue.setup_minutes or 0)
    effective_end = end + timedelta(minutes=venue.turnaround_minutes or 0)
    return effective_start, effective_end

# WHY COMMENTED OUT: This function is legacy fallback for bookings with no timing, but start_datetime and end_datetime are NOT NULL, so it can never run.

# def compute_effective_window(event, venue: Venue):
#     """Legacy window: an event's advertised 2-hour slot, padded by that
#     venue's setup/turnaround time. E.g. a venue with 30 min setup / 45 min
#     turnaround on a 10:00-12:00 event occupies the venue from 9:30 to 12:45
#     (matches the Week 7 PDF's own example). Used for bookings that have no
#     start_at/end_at of their own."""
#     advertised_start = datetime.combine(event.proposed_date, event.proposed_time or datetime.min.time())
#     advertised_end = advertised_start + timedelta(hours=2)
#     return pad_window(advertised_start, advertised_end, venue)


def compute_booking_window(booking, venue: Venue):
    """Effective busy window of one booking on its venue: the booking's own
    start/end (which may run past midnight), padded by the venue's setup and
    turnaround time. Week 7's example: 10:00-12:00 with 30 min setup and
    45 min turnaround occupies the venue from 09:30 to 12:45."""
    return pad_window(booking.start_datetime, booking.end_datetime, venue)


def add_flag_once(event_id: int, venue_id: int, reason: str):
    """Create an unresolved flag unless an identical one already exists.
    Returns the new flag, or None if it would have been a duplicate."""
    existing = VenueAvailabilityFlag.query.filter_by(
        event_id=event_id, venue_id=venue_id, reason=reason, resolved=False
    ).first()
    if existing:
        return None
    flag = VenueAvailabilityFlag(event_id=event_id, venue_id=venue_id, reason=reason)
    db.session.add(flag)
    return flag


def get_calendar(venue_id: int, start, end):
    """View venue availability: approved bookings and recorded
    unavailability for one venue within [start, end]. Each booking entry
    includes its effective (setup/turnaround-padded) window alongside the
    raw record, so the frontend can render either."""
    venue = Venue.query.get(venue_id)
    if venue is None:
        raise LookupError("Venue not found")

    # Pre-filter in SQL with a buffer for setup/turnaround, then confirm the
    # padded window really overlaps [start, end].
    buffer = timedelta(minutes=(venue.setup_minutes or 0) + (venue.turnaround_minutes or 0))
    bookings = VenueBooking.query.filter(
        VenueBooking.venue_id == venue_id,
        db.or_(
            VenueBooking.status == BOOKING_APPROVED,
            db.and_(VenueBooking.status == BOOKING_HELD, VenueBooking.hold_expires_at > utcnow()),
        ),
        VenueBooking.start_datetime <= end + buffer,
        VenueBooking.end_datetime >= start - buffer,
    ).order_by(VenueBooking.start_datetime.asc()).all()
    booking_dicts = []
    held_dicts = []
    for b in bookings:
        window = compute_booking_window(b, venue)
        if not (window[0] <= end and start <= window[1]):
            continue
        entry = b.to_dict()
        entry["eventName"] = b.event.name if b.event else f"Event #{b.event_id}"
        entry["effectiveStart"] = window[0].isoformat()
        entry["effectiveEnd"] = window[1].isoformat()
        if b.status == BOOKING_HELD:
            held_dicts.append(entry)
        else:
            booking_dicts.append(entry)

    blocks = VenueUnavailability.query.filter(
        VenueUnavailability.venue_id == venue_id,
        VenueUnavailability.end_datetime >= start,
        VenueUnavailability.start_datetime <= end,
    ).all()
    return {
        "confirmedBookings": booking_dicts,
        "heldBookings": held_dicts,
        "unavailability": [u.to_dict() for u in blocks],
    }


def get_combined_calendar(start, end):
    """Combined view: every active venue's calendar in one call, so the
    frontend can render a single toggle between 'combined' and 'per-venue'
    without making N separate requests."""
    venues = Venue.query.filter_by(is_active=True).all()
    return [
        {
            "venue": v.to_dict(),
            **get_calendar(v.id, start, end),
        }
        for v in venues
    ]


def _flag_affected_events(venue: Venue, start, end, reason: str):
    """Flag availability changes affecting an upcoming event: any APPROVED
    booking on this venue whose effective (setup/turnaround-padded) window
    overlaps the new unavailable period gets a flag so the Coordinator can
    follow up. Per Week 7 change #2, the event itself is never cancelled
    here -- only flagged."""
    confirmed = VenueBooking.query.filter(
        VenueBooking.venue_id == venue.id,
        VenueBooking.status == BOOKING_APPROVED,
    ).all()

    flagged = []
    for booking in confirmed:
        event = booking.event
        if not event:
            continue
        event_start, event_end = compute_booking_window(booking, venue)
        if event_start < end and start < event_end:
            flag = add_flag_once(
                event.id,
                venue.id,
                reason or "Venue marked unavailable during this event's scheduled time",
            )
            if flag:
                flagged.append(flag)
    return flagged


def flag_timing_conflicts(venue: Venue, reason: str):
    """Week 7 change #1: when a venue's setup_minutes/turnaround_minutes
    changes, two previously non-conflicting approved bookings can now
    effectively overlap. Re-check every pair of this venue's approved
    bookings under the new timing and flag any event involved in a new
    overlap, rather than silently leaving (or removing) the conflict."""
    bookings = VenueBooking.query.filter(
        VenueBooking.venue_id == venue.id,
        VenueBooking.status == BOOKING_APPROVED,
    ).all()

    windows = []
    for b in bookings:
        event = b.event
        if not event:
            continue
        window_start, window_end = compute_booking_window(b, venue)
        windows.append((event, window_start, window_end))

    flagged_event_ids = set()
    flags = []
    for i in range(len(windows)):
        event_a, start_a, end_a = windows[i]
        for j in range(i + 1, len(windows)):
            event_b, start_b, end_b = windows[j]
            if start_a < end_b and start_b < end_a:
                for ev in (event_a, event_b):
                    if ev.id not in flagged_event_ids:
                        flagged_event_ids.add(ev.id)
                        flag = add_flag_once(ev.id, venue.id, reason)
                        if flag:
                            flags.append(flag)
    return flags


def add_unavailability(venue: Venue, user_id: int, start, end, reason: str = None):
    """Venue Staff mark a venue unavailable for operational reasons.
    Returns (block, flags_raised) -- flags_raised is non-empty when this
    block collides with an already-approved booking's effective window."""
    if not isinstance(start, datetime) or not isinstance(end, datetime):
        raise ValueError("start and end must be ISO datetimes")
    if end <= start:
        raise ValueError("End time must be after start time")

    block = VenueUnavailability(
        venue_id=venue.id, start_datetime=start, end_datetime=end, reason=reason, created_by=user_id
    )
    db.session.add(block)

    flags = _flag_affected_events(venue, start, end, reason)

    db.session.commit()
    return block, flags


def remove_unavailability(venue: Venue, block_id: int):
    """Venue Staff remove an unavailable period (e.g. entered by mistake, or
    maintenance finished early). The block must belong to this venue.
    Raises LookupError if it does not exist."""
    block = VenueUnavailability.query.filter_by(id=block_id, venue_id=venue.id).first()
    if block is None:
        raise LookupError("Unavailability period not found")
    db.session.delete(block)
    db.session.commit()


def list_flags_for_event(event_id: int):
    return VenueAvailabilityFlag.query.filter_by(event_id=event_id).order_by(
        VenueAvailabilityFlag.created_at.desc()
    ).all()


def list_unresolved_flags_for_coordinator(coordinator_id: int):
    from app.models.event import Event

    return (
        VenueAvailabilityFlag.query.join(Event, VenueAvailabilityFlag.event_id == Event.id)
        .filter(Event.coordinator_id == coordinator_id, VenueAvailabilityFlag.resolved.is_(False))
        .order_by(VenueAvailabilityFlag.created_at.desc())
        .all()
    )


def resolve_flag(flag: VenueAvailabilityFlag):
    from app.common.time import utcnow

    flag.resolved = True
    flag.resolved_at = utcnow()
    db.session.commit()
    return flag