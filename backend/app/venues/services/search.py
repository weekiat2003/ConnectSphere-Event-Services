"""Venue Search and Filtering epic: Stories 1 and 2."""
from datetime import datetime, timedelta

from sqlalchemy import and_, func, or_  # `and_` is only used by Story 3

from app.common.time import utcnow
from app.models.venue import (
    BOOKING_APPROVED,
    BOOKING_HELD,
    Venue,
    VenueAccessibilityFeature,
    VenueBooking,
    VenueFacility,
    VenueLayout,  # STORY 3
    VenueUnavailability,
)
from app.venues.services.availability import (
    compute_booking_window,
    fits_operating_hours,
    pad_window,
)

# Venue capacity is INT UNSIGNED in database/schema.sql.
MAX_VENUE_CAPACITY = (1 << 32) - 1


def _is_available(venue: Venue, start: datetime, end: datetime) -> bool:
    """A venue is free if the requested window, padded by the venue's own
    setup/turnaround time (Week 7 change #1), overlaps no APPROVED booking
    (also padded) and no recorded unavailability. Pending, rejected and
    withdrawn bookings never block. Windows that only touch do not overlap."""
    requested_start, requested_end = pad_window(start, end, venue)
    prefilter_buffer = timedelta(
        minutes=(venue.setup_minutes or 0) + (venue.turnaround_minutes or 0)
    )

    blocking = VenueBooking.query.filter(
        VenueBooking.venue_id == venue.id,
        or_(
            VenueBooking.status == BOOKING_APPROVED,
            and_(VenueBooking.status == BOOKING_HELD, VenueBooking.hold_expires_at > utcnow()),
        ),
        VenueBooking.start_datetime < requested_end + prefilter_buffer,
        VenueBooking.end_datetime > requested_start - prefilter_buffer,
    ).all()
    for booking in blocking:
        busy_start, busy_end = compute_booking_window(booking, venue)
        if busy_start < requested_end and requested_start < busy_end:
            return False

    closure = VenueUnavailability.query.filter(
        VenueUnavailability.venue_id == venue.id,
        VenueUnavailability.start_datetime < requested_end,
        VenueUnavailability.end_datetime > requested_start,
    ).first()
    return closure is None


def search_venues(
    date,
    start_time,
    end_time,
    expected_attendance,
    location=None,
    max_capacity=None,
    accessibility_features=None,
    required_facilities=None,
    layout=None,  # STORY 3
):
    """Active venues with capacity >= expected_attendance that are free for
    the whole window, narrowed by any catalogue filters, sorted by name."""
    if max_capacity is not None and max_capacity < expected_attendance:
        raise ValueError("Maximum capacity cannot be lower than expected attendance.")
    if expected_attendance > MAX_VENUE_CAPACITY:
        return []

    start = datetime.combine(date, start_time)
    end = datetime.combine(date, end_time)

    query = Venue.query.filter(
        Venue.is_active.is_(True),
        Venue.capacity >= expected_attendance,
    )
    if location:
        query = query.filter(func.lower(Venue.location) == location.lower())
    if max_capacity is not None:
        query = query.filter(Venue.capacity <= max_capacity)
    for feature in accessibility_features or []:
        query = query.filter(
            Venue.accessibility_entries.any(
                func.lower(VenueAccessibilityFeature.feature_name) == feature.lower()
            )
        )
    for facility in required_facilities or []:
        query = query.filter(
            Venue.facility_entries.any(
                func.lower(VenueFacility.facility_name) == facility.lower()
            )
        )
    if layout:  # STORY 3 (whole block, down to the blank line)
        # Supported layout AND (if the catalogue records a per-layout
        # capacity) able to hold the expected attendance.
        query = query.filter(
            Venue.layout_entries.any(
                and_(
                    func.lower(VenueLayout.layout_name) == layout.lower(),
                    or_(
                        VenueLayout.max_capacity.is_(None),
                        VenueLayout.max_capacity >= expected_attendance,
                    ),
                )
            )
        )

    venues = query.all()
    available = [
        venue
        for venue in venues
        if fits_operating_hours(venue, start_time, end_time)
        and _is_available(venue, start, end)
    ]
    return sorted(available, key=lambda venue: venue.name.casefold())


def get_filter_options():
    """Return selectable filter values represented in the active catalogue."""
    active_venues = Venue.query.filter(
        Venue.is_active.is_(True),
        Venue.location.isnot(None),
        Venue.location != "",
    )
    locations = (
        active_venues.with_entities(Venue.location)
        .distinct()
        .order_by(Venue.location)
        .all()
    )
    facilities = (
        VenueFacility.query.join(Venue)
        .filter(Venue.is_active.is_(True))
        .with_entities(VenueFacility.facility_name)
        .distinct()
        .order_by(VenueFacility.facility_name)
        .all()
    )
    accessibility_features = (
        VenueAccessibilityFeature.query.join(Venue)
        .filter(Venue.is_active.is_(True))
        .with_entities(VenueAccessibilityFeature.feature_name)
        .distinct()
        .order_by(VenueAccessibilityFeature.feature_name)
        .all()
    )
    # STORY 3 (layout_rows block through the `layouts.append(name)` line)
    layout_rows = (
        VenueLayout.query.join(Venue)
        .filter(Venue.is_active.is_(True))
        .with_entities(VenueLayout.layout_name)
        .distinct()
        .order_by(VenueLayout.layout_name)
        .all()
    )
    layouts, seen = [], set()
    for (name,) in layout_rows:  # layouts are case-insensitive: list each once
        if name.lower() not in seen:
            seen.add(name.lower())
            layouts.append(name)
    return {
        "layouts": layouts,  # STORY 3
        "locations": [value for (value,) in locations],
        "facilities": [value for (value,) in facilities],
        "accessibilityFeatures": [value for (value,) in accessibility_features],
    }