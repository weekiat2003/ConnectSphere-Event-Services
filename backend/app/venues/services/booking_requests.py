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
from datetime import datetime

from app.common.time import utcnow
from app.extensions import db
from app.models.event import Event
from app.models.venue import Venue, VenueBooking
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

        problem = (
            "venue not found"
            if venue is None
            else ACTIVE_BOOKING_MESSAGE
            if venue_id in seen_venue_ids or _has_active_booking(event.id, venue_id)
            else None
        )
        if problem:
            item_errors.append(_error(venue_id, venue_label, "venue_id", problem))
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
    db.session.commit()
    return bookings