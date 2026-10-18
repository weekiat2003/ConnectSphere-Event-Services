"""Venue Catalogue epic."""
from app.extensions import db
from app.models.venue import (
    ACTIVE_BOOKING_STATUSES,
    BOOKING_APPROVED,
    Venue,
    VenueBooking,
)
SUITABILITY_FIELDS = {"capacity", "supported_layouts", "accessibility_features", "operating_hours"}
TIMING_FIELDS = {"setup_minutes", "turnaround_minutes"}  # Week 7 change #1
LIST_FIELDS = {"supported_layouts", "facilities", "accessibility_features"}


_LIST_FIELDS = ("supportedLayouts", "facilities", "accessibilityFeatures")


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _validate(data: dict, *, partial: bool) -> dict:
    """Validate venue input and return cleaned values (keyed like `data`).
    partial=True (updates) only checks keys that are present; partial=False
    (create) additionally requires name and capacity. Raises ValueError."""
    clean = {}

    if not partial or "name" in data:
        name = data.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Venue name is required")
        clean["name"] = name.strip()

    if not partial or "capacity" in data:
        capacity = data.get("capacity")
        if capacity is None or capacity == "":
            raise ValueError("Venue capacity is required")
        if not _is_int(capacity):
            raise ValueError("Venue capacity must be a whole number")
        if capacity <= 0:
            raise ValueError("Venue capacity must be greater than zero")
        clean["capacity"] = capacity

    for key, label in (("setupMinutes", "Setup time"), ("turnaroundMinutes", "Turnaround time")):
        if key in data or not partial:
            value = data.get(key, 0)
            if value is None:
                value = 0
            if not _is_int(value):
                raise ValueError(f"{label} must be a whole number of minutes")
            if value < 0:
                raise ValueError(f"{label} cannot be negative")
            clean[key] = value

    for key in _LIST_FIELDS:
        if key in data or not partial:
            value = data.get(key)
            if value is None:
                value = []
            if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
                raise ValueError(f"{key} must be a list of text values")
            cleaned, seen = [], set()
            for item in value:
                text = item.strip()
                if key == "supportedLayouts":
                    text = text.lower()  # layouts are matched case-insensitively
                if text and text.lower() not in seen:  # the DB unique keys ignore case
                    seen.add(text.lower())
                    cleaned.append(text)
            clean[key] = cleaned

    return clean


def _sync_names(collection, names):
    """Make a table-backed list (facilities, layouts, accessibility features) hold
    exactly `names`, adding and removing only the difference. Replacing the whole
    list would delete and re-insert unchanged rows in one flush and hit the
    UNIQUE (venue_id, name) key."""
    wanted = {n.lower() for n in names}
    for existing in list(collection):
        if existing.lower() not in wanted:
            collection.remove(existing)
    have = {e.lower() for e in collection}
    for name in names:
        if name.lower() not in have:
            collection.append(name)
            have.add(name.lower())


def create_venue(user_id: int, data: dict) -> Venue:
    clean = _validate(data, partial=False)
    venue = Venue(
        name=clean["name"],
        location=data.get("location"),
        capacity=clean["capacity"],
        description=data.get("description"),
        operating_hours=data.get("operatingHours"),
        setup_minutes=clean["setupMinutes"],
        turnaround_minutes=clean["turnaroundMinutes"],
        created_by=user_id,
        is_active=True,  # always active on creation, whatever the client sends
    )
    _sync_names(venue.supported_layouts, clean["supportedLayouts"])
    _sync_names(venue.facilities, clean["facilities"])
    _sync_names(venue.accessibility_features, clean["accessibilityFeatures"])
    db.session.add(venue)
    db.session.commit()
    return venue


def _flag_suitability_change(venue: Venue, reason: str):
    """Re-checks every confirmed booking on this venue against the venue's
    (now-updated) capacity/layout/accessibility and raises a flag for any
    event that no longer fits."""
    from app.venues.services.availability import add_flag_once
    from app.venues.services.suitability import check_suitability

    confirmed = VenueBooking.query.filter(
        VenueBooking.venue_id == venue.id, VenueBooking.status == BOOKING_APPROVED
    ).all()

    flags = []
    for booking in confirmed:
        event = booking.event
        if not event:
            continue
        issues = check_suitability(event, venue)
        if issues:
            flag = add_flag_once(event.id, venue.id, f"{reason}: {'; '.join(issues)}")
            if flag:
                flags.append(flag)
    return flags


def update_venue(venue: Venue, data: dict):
    """Edit an existing venue record. Returns (venue, flags_raised).
    flags_raised can come from two independent checks: a capacity/layout/
    accessibility change that no longer suits an existing confirmed
    booking, or (Week 7 change #1) a setup/turnaround time change that
    makes two existing confirmed bookings newly overlap."""
    clean = _validate(data, partial=True)  # raises ValueError before anything is changed
    data = {**data, **clean}
    changed_fields = set()

    for field, key in (
        ("name", "name"),
        ("location", "location"),
        ("capacity", "capacity"),
        ("description", "description"),
        ("supported_layouts", "supportedLayouts"),
        ("facilities", "facilities"),
        ("accessibility_features", "accessibilityFeatures"),
        ("operating_hours", "operatingHours"),
        ("setup_minutes", "setupMinutes"),
        ("turnaround_minutes", "turnaroundMinutes"),
    ):
        if key not in data:
            continue
        if field in LIST_FIELDS:
            current = list(getattr(venue, field))
            if {n.lower() for n in data[key]} != {n.lower() for n in current}:
                _sync_names(getattr(venue, field), data[key])
                changed_fields.add(field)
        elif data[key] != getattr(venue, field):
            setattr(venue, field, data[key])
            changed_fields.add(field)

    flags = []
    if changed_fields & SUITABILITY_FIELDS:
        flags += _flag_suitability_change(venue, "Venue details changed after booking was confirmed")
    if changed_fields & TIMING_FIELDS:
        from app.venues.services.availability import flag_timing_conflicts

        flags += flag_timing_conflicts(
            venue, "Venue setup/turnaround time changed, creating a new scheduling conflict"
        )

    db.session.commit()
    return venue, flags


def deactivate_venue(venue: Venue) -> Venue:
    """Delete/deactivate a venue record. Per the AC, this is only permitted
    when the venue has no active (pending or confirmed) bookings -- a venue
    mid-use should not be silently pulled out from under an event."""
    active_booking = VenueBooking.query.filter(
        VenueBooking.venue_id == venue.id,
        VenueBooking.status.in_(ACTIVE_BOOKING_STATUSES),
    ).first()
    if active_booking:
        raise ValueError(
            "Cannot deactivate a venue with active bookings. "
            "Cancel or reassign them first."
        )

    venue.is_active = False
    db.session.commit()
    return venue


def list_venues(active_only: bool = True):
    query = Venue.query
    if active_only:
        query = query.filter_by(is_active=True)
    return query.order_by(Venue.name.asc()).all()


def get_venue(venue_id: int):
    return Venue.query.get(venue_id)
