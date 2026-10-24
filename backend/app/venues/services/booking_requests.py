"""
Submit a venue booking request: one request, one or more venues, each venue
with its own timing and requirements.

Expected input from the route layer (already parsed into date/time objects):

    venue_requests = [
        {
            "venue_id": 10,
            "date": date(2026, 11, 1),
            "start_time": time(20, 0),
            "end_time": time(2, 0),
            "end_date": date(2026, 11, 2),   # optional, defaults to "date"
            "label": "Main auditorium",      # optional
            "equipment": "Projector",        # optional
            "catering": None,                # optional
            "other_requirements": "",        # optional
        },
        ...
    ]

The whole request is all-or-nothing: if any venue has a problem, nothing is saved
and every problem is reported, each tagged with its venue and field.
"""
from datetime import datetime, timedelta

from app.common.time import utcnow
from app.extensions import db
from app.models.event import Event
from app.notifications.services import triggers as notifications
from app.models.venue import BOOKING_APPROVED, Venue, VenueBooking
from app.venues.services.availability import compute_booking_window, pad_window
from app.venues.services.booking import PENDING

ACTIVE_BOOKING_MESSAGE = "this event already has an active booking for this venue"
REQUIRED_FIELDS = ("date", "start_time", "end_time")
FIELD_LABELS = {"date": "event date", "start_time": "start time", "end_time": "end time"}


class BookingRequestError(ValueError):
    """Raised when a request can't be submitted. `errors` is a list of
    {"venue_id", "venue", "field", "message"} so the UI can point at the exact spot."""

    def __init__(self, errors):
        self.errors = errors
        super().__init__("; ".join(e["message"] for e in errors))


def _error(venue_id, venue_label, field, message):
    return {
        "venue_id": venue_id,
        "venue": venue_label,
        "field": field,
        "message": f"{venue_label}: {message}" if venue_label else message,
    }


def _is_blank(value):
    return value is None or (isinstance(value, str) and not value.strip())


def _validate_timing(item, venue_id, venue_label, today):
    """Returns (errors, start_at, end_at). start_at/end_at are None if invalid."""
    errors = []

    missing = [f for f in REQUIRED_FIELDS if _is_blank(item.get(f))]
    for field in missing:
        errors.append(_error(venue_id, venue_label, field, f"{FIELD_LABELS[field]} is missing"))
    if missing:
        return errors, None, None

    event_date = item["date"]
    end_date = item.get("end_date") or event_date
    start_at = datetime.combine(event_date, item["start_time"])
    end_at = datetime.combine(end_date, item["end_time"])

    if event_date < today:
        errors.append(_error(venue_id, venue_label, "date", "event date is in the past"))
    if end_at <= start_at:
        errors.append(
            _error(venue_id, venue_label, "end_time", "end time must be after the start time")
        )
    if errors:
        return errors, None, None
    return [], start_at, end_at


def _has_active_booking(event_id, venue_id):
    return (
        VenueBooking.query.filter(
            VenueBooking.event_id == event_id,
            VenueBooking.venue_id == venue_id,
            db.or_(VenueBooking.status.in_(("pending", "approved")),
                    db.and_(VenueBooking.status == "held", VenueBooking.hold_expires_at > utcnow())),
        ).first()
        is not None
    )

def _find_confirmed_conflict(event_id, venue, start_at, end_at):
    """Return an APPROVED booking for a *different* event whose effective
    (setup/turnaround-padded) window overlaps the requested one, else None."""
    new_start, new_end = pad_window(start_at, end_at, venue)
    buffer = timedelta(minutes=(venue.setup_minutes or 0) + (venue.turnaround_minutes or 0))

    # Cheap SQL pre-filter, then confirm with the exact padded windows.
    candidates = (
        VenueBooking.query.filter(
            VenueBooking.venue_id == venue.id,
            VenueBooking.status == BOOKING_APPROVED,
            VenueBooking.event_id != event_id,
            VenueBooking.start_datetime < new_end + buffer,
            VenueBooking.end_datetime > new_start - buffer,
        )
        .order_by(VenueBooking.start_datetime.asc())
        .all()
    )
    for other in candidates:
        other_start, other_end = compute_booking_window(other, venue)
        if other_start < new_end and new_start < other_end:
            return other
    return None


def _format_period(start: datetime, end: datetime) -> str:
    if start.date() == end.date():
        return f"{start:%Y-%m-%d}, {start:%H:%M} to {end:%H:%M}"
    return f"{start:%Y-%m-%d %H:%M} to {end:%Y-%m-%d %H:%M}"


def _conflict_message(venue, other: VenueBooking) -> str:
    return (
        f"{venue.name} is unavailable. It already has a confirmed booking on "
        f"{_format_period(other.start_datetime, other.end_datetime)}, "
        f"which overlaps your requested time. Choose a different time or venue."
    )

def submit_booking_requests(event: Event, venue_requests: list, user_id: int, today=None):
    """Create one pending VenueBooking per venue, linked to `event`.
    Raises BookingRequestError (and saves nothing) if anything is invalid."""
    today = today or utcnow().date()

    if not venue_requests:
        raise BookingRequestError(
            [_error(None, None, "venues", "add at least one venue to the booking request")]
        )

    errors = []
    valid = []  # (item, venue, start_at, end_at)
    seen_venue_ids = set()

    for index, item in enumerate(venue_requests, start=1):
        venue_id = item.get("venue_id")
        venue = Venue.query.get(venue_id) if venue_id is not None else None
        venue_label = getattr(venue, "name", None) or f"Venue {index}"

        item_errors, start_at, end_at = _validate_timing(item, venue_id, venue_label, today)

        # Check for a confirmed conflict first, so it takes priority over the
        # generic "already has an active booking" message.
        conflict = None
        if venue is not None and start_at and end_at:
            conflict = _find_confirmed_conflict(event.id, venue, start_at, end_at)

        if venue is None:
            problem = "venue not found"
        elif conflict:
            problem = None  # reported below
        elif venue_id in seen_venue_ids or _has_active_booking(event.id, venue_id):
            problem = ACTIVE_BOOKING_MESSAGE
        else:
            problem = None

        if problem:
            item_errors.append(_error(venue_id, venue_label, "venue_id", problem))
        elif conflict:
            item_errors.append(
                {
                    "venue_id": venue_id,
                    "venue": venue_label,
                    "field": "venue_id",
                    "message": _conflict_message(venue, conflict),
                }
            )
        seen_venue_ids.add(venue_id)

        if item_errors:
            errors.extend(item_errors)
        else:
            valid.append((item, venue, start_at, end_at))

    if errors:
        raise BookingRequestError(errors)

    bookings = [
        VenueBooking(
            event_id=event.id,
            venue_id=venue.id,
            requested_by=user_id,
            status=PENDING,
            start_datetime=start_at,
            end_datetime=end_at,
            booking_label=item.get("label"),
            equipment=item.get("equipment"),
            catering=item.get("catering"),
            other_requirements=item.get("other_requirements"),
        )
        for item, venue, start_at, end_at in valid
    ]

    db.session.add_all(bookings)
    db.session.flush()  # booking ids are needed for the notification links
    notifications.notify_venue_staff_of_booking_requests(bookings)
    db.session.commit()
    return bookings