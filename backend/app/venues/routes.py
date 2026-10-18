import re
from datetime import date, datetime, time, timezone

from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required

from app.auth.decorators import roles_required
from app.extensions import db
from app.models.event import Event
from app.models.user import User
from app.models.venue import Venue, VenueBooking
from app.venues.services import availability, booking, booking_requests, catalogue, search, suitability, preparation
from app.venues.services.booking_requests import BookingRequestError

venues_bp = Blueprint("venues", __name__)

def _clean_list(values):
      return list(dict.fromkeys(v.strip() for v in values if v and v.strip()))

def _current_user():
    return User.query.get(int(get_jwt_identity()))


def _parse_dt(text):
    """Parse an ISO datetime. Timezone info is dropped (wall-clock time is kept)
    because the database stores naive datetimes. Raises ValueError/TypeError."""
    return datetime.fromisoformat(text).replace(tzinfo=None)


# Venue catalogue + calendar are for internal users only.
INTERNAL_ROLES = ("venue_staff", "event_coordinator")


# ---------------------------------------------------------------------
# Venue Catalogue
# ---------------------------------------------------------------------

@venues_bp.post("")
@roles_required("venue_staff")
def create_venue():
    user = _current_user()
    try:
        venue = catalogue.create_venue(user.id, request.get_json() or {})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify(venue.to_dict()), 201


@venues_bp.get("")
@roles_required(*INTERNAL_ROLES)
def list_venues():
    return jsonify([v.to_dict() for v in catalogue.list_venues()]), 200


@venues_bp.get("/<int:venue_id>")
@roles_required(*INTERNAL_ROLES)
def get_venue(venue_id):
    venue = catalogue.get_venue(venue_id)
    if not venue:
        return jsonify({"error": "Venue not found"}), 404
    return jsonify(venue.to_dict()), 200


@venues_bp.put("/<int:venue_id>")
@roles_required("venue_staff")
def update_venue(venue_id):
    venue = catalogue.get_venue(venue_id)
    if not venue:
        return jsonify({"error": "Venue not found"}), 404
    try:
        venue, flags = catalogue.update_venue(venue, request.get_json() or {})
    except ValueError as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 400
    return jsonify({
        "venue": venue.to_dict(),
        "flagsRaised": [f.to_dict() for f in flags],
    }), 200


@venues_bp.delete("/<int:venue_id>")
@roles_required("venue_staff")
def deactivate_venue(venue_id):
    venue = catalogue.get_venue(venue_id)
    if not venue:
        return jsonify({"error": "Venue not found"}), 404
    try:
        catalogue.deactivate_venue(venue)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return "", 204


# ---------------------------------------------------------------------
# Venue Availability Calendar
# ---------------------------------------------------------------------

@venues_bp.get("/<int:venue_id>/calendar")
@roles_required(*INTERNAL_ROLES)
def get_calendar(venue_id):
    start = request.args.get("start")
    end = request.args.get("end")
    if not start or not end:
        return jsonify({"error": "start and end query params (ISO datetimes) are required"}), 400
    try:
        start_dt, end_dt = _parse_dt(start), _parse_dt(end)
    except ValueError:
        return jsonify({"error": "start and end must be valid ISO datetimes"}), 400
    if end_dt <= start_dt:
        return jsonify({"error": "End must be after start"}), 400
    try:
        calendar = availability.get_calendar(venue_id, start_dt, end_dt)
    except LookupError:
        return jsonify({"error": "Venue not found"}), 404
    return jsonify(calendar), 200


@venues_bp.get("/calendar")
@roles_required(*INTERNAL_ROLES)
def get_combined_calendar():
    """Combined (all-venues) view -- the other half of the per-venue vs.
    combined toggle, paired with GET /<venue_id>/calendar above."""
    start = request.args.get("start")
    end = request.args.get("end")
    if not start or not end:
        return jsonify({"error": "start and end query params (ISO datetimes) are required"}), 400
    try:
        start_dt, end_dt = _parse_dt(start), _parse_dt(end)
    except ValueError:
        return jsonify({"error": "start and end must be valid ISO datetimes"}), 400
    if end_dt <= start_dt:
        return jsonify({"error": "End must be after start"}), 400
    calendar = availability.get_combined_calendar(start_dt, end_dt)
    return jsonify(calendar), 200


@venues_bp.post("/<int:venue_id>/unavailability")
@roles_required("venue_staff")
def add_unavailability(venue_id):
    venue = catalogue.get_venue(venue_id)
    if not venue:
        return jsonify({"error": "Venue not found"}), 404
    user = _current_user()
    data = request.get_json() or {}
    try:
        block, flags = availability.add_unavailability(
            venue,
            user.id,
            _parse_dt(data.get("start")),
            _parse_dt(data.get("end")),
            data.get("reason"),
        )
    except (ValueError, TypeError) as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({
        "unavailability": block.to_dict(),
        "flagsRaised": [f.to_dict() for f in flags],
    }), 201


@venues_bp.delete("/<int:venue_id>/unavailability/<int:block_id>")
@roles_required("venue_staff")
def remove_unavailability(venue_id, block_id):
    venue = catalogue.get_venue(venue_id)
    if not venue:
        return jsonify({"error": "Venue not found"}), 404
    try:
        availability.remove_unavailability(venue, block_id)
    except LookupError:
        return jsonify({"error": "Unavailability period not found"}), 404
    return "", 204


@venues_bp.get("/flags/mine")
@roles_required("event_coordinator")
def my_availability_flags():
    """Coordinator views unresolved availability-change flags for events
    assigned to them."""
    user = _current_user()
    flags = availability.list_unresolved_flags_for_coordinator(user.id)
    return jsonify([f.to_dict() for f in flags]), 200


@venues_bp.post("/flags/<int:flag_id>/resolve")
@roles_required("event_coordinator")
def resolve_availability_flag(flag_id):
    from app.models.venue import VenueAvailabilityFlag

    flag = VenueAvailabilityFlag.query.get(flag_id)
    if not flag:
        return jsonify({"error": "Flag not found"}), 404
    flag = availability.resolve_flag(flag)
    return jsonify(flag.to_dict()), 200


# ---------------------------------------------------------------------
# Venue Search and Filtering / Venue Suitability Checking
# ---------------------------------------------------------------------

@venues_bp.get("/search")
@roles_required("event_coordinator")
def search_venues():
    args = request.args
    errors = {}

    date_text = args.get("date", "").strip()
    start_text = args.get("start_time", "").strip()
    end_text = args.get("end_time", "").strip()
    attendance_text = args.get("attendance", "").strip()

    event_date = None
    if not date_text:
        errors["date"] = "Date is required."
    else:
        try:
            event_date = datetime.strptime(date_text, "%Y-%m-%d").date()
        except ValueError:
            errors["date"] = "Enter a valid date."

    parsed_times = {}
    for field, value in (("start_time", start_text), ("end_time", end_text)):
        if not value:
            errors[field] = f"{field.replace('_', ' ').capitalize()} is required."
            continue
        try:
            parsed_times[field] = datetime.strptime(value, "%H:%M").time()
        except ValueError:
            errors[field] = "Enter a valid time."

    attendance = None
    max_capacity = None
    attendance_exceeds_capacity = False
    if not attendance_text:
        errors["attendance"] = "Expected attendance is required."
    elif not re.fullmatch(r"[0-9]+", attendance_text):
        errors["attendance"] = "Enter a positive whole number."
    else:
        normalized_attendance = attendance_text.lstrip("0") or "0"
        maximum_attendance = str(search.MAX_VENUE_CAPACITY)
        if (
            len(normalized_attendance) > len(maximum_attendance)
            or (
                len(normalized_attendance) == len(maximum_attendance)
                and normalized_attendance > maximum_attendance
            )
        ):
            attendance_exceeds_capacity = True
        else:
            attendance = int(normalized_attendance)
            if attendance < 1:
                errors["attendance"] = "Enter a positive whole number."

    max_capacity_text = args.get("max_capacity", "").strip()
    if max_capacity_text:
        if not re.fullmatch(r"[0-9]+", max_capacity_text):
            errors["max_capacity"] = "Enter a positive whole number."
        else:
            normalized_max_capacity = max_capacity_text.lstrip("0") or "0"
            maximum_capacity = str(search.MAX_VENUE_CAPACITY)
            if (
                len(normalized_max_capacity) > len(maximum_capacity)
                or (
                    len(normalized_max_capacity) == len(maximum_capacity)
                    and normalized_max_capacity > maximum_capacity
                )
            ):
                errors["max_capacity"] = "Maximum capacity is out of range."
            else:
                max_capacity = int(normalized_max_capacity)
                if max_capacity < 1:
                    errors["max_capacity"] = "Enter a positive whole number."
                elif attendance is not None and max_capacity < attendance:
                    errors["max_capacity"] = (
                        "Maximum capacity cannot be lower than expected attendance."
                    )
                elif attendance_exceeds_capacity:
                    errors["max_capacity"] = (
                        "Maximum capacity cannot be lower than expected attendance."
                    )

    if (
        "start_time" not in errors
        and "end_time" not in errors
        and parsed_times["end_time"] <= parsed_times["start_time"]
    ):
        errors["end_time"] = "End time must be after start time."

    if errors:
        return jsonify({"errors": errors}), 400

    if attendance_exceeds_capacity:
        return jsonify([]), 200

    results = search.search_venues(
        date=event_date,
        start_time=parsed_times["start_time"],
        end_time=parsed_times["end_time"],
        expected_attendance=attendance,
        location=args.get("location", "").strip() or None,
        max_capacity=max_capacity,
        accessibility_features=_clean_list(args.getlist("accessibility")),
        required_facilities=_clean_list(args.getlist("facilities")),
        layout=args.get("layout", "").strip() or None,
    )
    return jsonify([v.to_dict() for v in results]), 200


@venues_bp.get("/search/options")
@roles_required("event_coordinator")
def venue_search_options():
    return jsonify(search.get_filter_options()), 200


@venues_bp.get("/<int:venue_id>/suitability/<int:event_id>")
@roles_required("event_coordinator")
def check_suitability(venue_id, event_id):
    venue = catalogue.get_venue(venue_id)
    event = Event.query.get(event_id)
    if not venue or not event:
        return jsonify({"error": "Venue or event not found"}), 404
    flags = suitability.check_suitability(event, venue)
    return jsonify({"suitable": len(flags) == 0, "flags": flags}), 200


# ---------------------------------------------------------------------
# Venue Booking Request / Venue Booking Approval / Booking Conflict Detection
# ---------------------------------------------------------------------

_DATE_TIME_FIELDS = (
    # (json key, parsed key, parser, human label)
    ("date", "date", date.fromisoformat, "event date"),
    ("endDate", "end_date", date.fromisoformat, "end date"),
    ("startTime", "start_time", time.fromisoformat, "start time"),
    ("endTime", "end_time", time.fromisoformat, "end time"),
)
 
 
def _parse_venue_request(raw, index):
    """Turn one venue's JSON into the dict the service expects.
    Returns (parsed, errors); errors are for values that are present but
    not valid ISO dates/times (missing values are reported by the service)."""
    if not isinstance(raw, dict):
        return {}, [{
            "venue_id": None,
            "venue": f"Venue {index}",
            "field": "venue",
            "message": f"Venue {index}: invalid venue entry",
        }]
 
    parsed = {
    "venue_id": raw.get("venueId"),
    }
    
    errors = []
    for json_key, field, parser, label in _DATE_TIME_FIELDS:
        value = raw.get(json_key)
        if value in (None, ""):
            parsed[field] = None
            continue
        try:
            parsed[field] = parser(value)
        except (ValueError, TypeError):
            parsed[field] = None
            errors.append({
                "venue_id": raw.get("venueId"),
                "venue": f"Venue {index}",
                "field": field,
                "message": f"Venue {index}: {label} is not a valid value",
            })
    for json_key, field in (
        ("label", "label"),
        ("equipment", "equipment"),
        ("catering", "catering"),
        ("otherRequirements", "other_requirements"),
    ):
        value = raw.get(json_key)
        if value is not None and not isinstance(value, str):
            errors.append({
                "venue_id": raw.get("venueId"),
                "venue": f"Venue {index}",
                "field": field,
                "message": f"Venue {index}: {json_key} must be text",
            })
        parsed[field] = value.strip() or None if isinstance(value, str) else None
    return parsed, errors

@venues_bp.post("/bookings")
@roles_required("event_coordinator")
def submit_booking():
    """One request, one or more venues, each with its own timing/requirements.
 
    Body:
    {
      "eventId": 5,
      "venues": [
        {"venueId": 10, "date": "2026-11-01", "startTime": "20:00",
         "endTime": "02:00", "endDate": "2026-11-02",
         "label": "Main hall", "equipment": "Projector",
         "catering": null, "otherRequirements": null}
      ]
    }
    """
    user = _current_user()
    data = request.get_json() or {}
    event = Event.query.get(data.get("eventId"))
    if not event:
        return jsonify({"error": "Event not found"}), 404
    if event.coordinator_id != user.id:
        return jsonify({"error": "Only the assigned Coordinator can request a venue for this event"}), 403
 
    raw_venues = data.get("venues")
    if not isinstance(raw_venues, list):
        raw_venues = []
 
    venue_requests, parse_errors = [], []
    for index, raw in enumerate(raw_venues, start=1):
        parsed, errors = _parse_venue_request(raw, index)
        venue_requests.append(parsed)
        parse_errors.extend(errors)
    if parse_errors:
        return jsonify({"error": "Booking request could not be submitted", "errors": parse_errors}), 400
 
    try:
        results = booking_requests.submit_booking_requests(event, venue_requests, user.id)
    except BookingRequestError as e:
        return jsonify({"error": "Booking request could not be submitted", "errors": e.errors}), 400
    return jsonify([b.to_dict() for b in results]), 201


@venues_bp.get("/events/<int:event_id>/bookings")
@jwt_required()
def list_event_bookings(event_id):
    """Week 7 change #3: an event can have several venue bookings (e.g. a
    main auditorium plus breakout rooms) -- this lists all of them,
    independent of their individual statuses, so the UI can show the full
    multi-venue picture for one event."""
    user = _current_user()
    event = Event.query.get(event_id)
    if not event:
        return jsonify({"error": "Event not found"}), 404

    is_owner = event.organiser_id == user.id
    is_internal = any(
        user.has_role(role)
        for role in ("event_coordinator", "venue_staff", "technical_support_staff", "safety_officer")
    )
    if not (is_owner or is_internal):
        return jsonify({"error": "Event not found"}), 404  # 404, not 403 — don't reveal existence

    bookings_query = VenueBooking.query.filter_by(event_id=event_id)
    if user.has_role("venue_staff"):
        bookings_query = bookings_query.join(
            Venue, VenueBooking.venue_id == Venue.id
        ).filter(Venue.created_by == user.id)
    bookings = bookings_query.order_by(VenueBooking.created_at.asc()).all()
    return jsonify([b.to_dict() for b in bookings]), 200


@venues_bp.post("/bookings/<int:booking_id>/withdraw")
@roles_required("event_coordinator")
def withdraw_booking(booking_id):
    user = _current_user()
    record = VenueBooking.query.get(booking_id)
    if not record:
        return jsonify({"error": "Booking not found"}), 404
    try:
        result = booking.withdraw_booking_request(record, user.id)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify(result.to_dict()), 200


@venues_bp.post("/bookings/<int:booking_id>/cancel")
@roles_required("venue_staff")
def cancel_booking(booking_id):
    user = _current_user()
    record = VenueBooking.query.get(booking_id)
    if not record:
        return jsonify({"error": "Booking not found"}), 404
    data = request.get_json() or {}
    try:
        result = booking.cancel_booking(record, user.id, data.get("reason"))
    except PermissionError as e:
        return jsonify({"error": str(e)}), 403
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify(result.to_dict()), 200


@venues_bp.get("/bookings/my")
@roles_required("event_coordinator")
def get_my_booking_requests():
    user = _current_user()

    bookings = (
        VenueBooking.query
        .filter_by(requested_by=user.id)
        .order_by(VenueBooking.created_at.desc())
        .all()
    )

    results = []

    for booking_row in bookings:
        event = db.session.get(Event, booking_row.event_id)
        venue = db.session.get(Venue, booking_row.venue_id)

        results.append({
            "id": booking_row.id,
            "eventId": booking_row.event_id,
            "eventName": event.name if event else None,
            "venueId": booking_row.venue_id,
            "venueName": venue.name if venue else None,
            "status": booking_row.to_dict()["status"],
            "holdExpiresAt": booking_row.hold_expires_at.isoformat() if booking_row.hold_expires_at else None,
            "startDatetime": booking_row.start_datetime.isoformat(),
            "endDatetime": booking_row.end_datetime.isoformat(),
            "createdAt": (
                booking_row.created_at.isoformat()
                if booking_row.created_at else None
            ),
            "decisionReason": booking_row.decision_reason,
            "alternativeSuggestion": booking_row.alternative_suggestion,
            "label": booking_row.booking_label,
            "equipment": booking_row.equipment,
            "catering": booking_row.catering,
            "otherRequirements": booking_row.other_requirements,
        })

    return jsonify(results), 200


@venues_bp.get("/bookings/confirmation-notices")
@roles_required("event_coordinator")
def booking_confirmation_notices():
    """Simple in-app notices, derived from approved bookings (no new table)."""
    user = _current_user()
    approved = (VenueBooking.query
                .join(Event, VenueBooking.event_id == Event.id)
                .filter(Event.coordinator_id == user.id,
                        VenueBooking.status == "approved")
                .order_by(VenueBooking.decided_at.desc()).all())
    return jsonify([{
        "bookingId": b.id,
        "eventId": b.event_id,
        "message": f"Venue confirmed: {b.venue.name if b.venue else 'Venue'} "
                   f"for {b.event.name if b.event else 'your event'}.",
        "confirmedAt": b.decided_at.isoformat() if b.decided_at else None,
    } for b in approved]), 200

@venues_bp.get("/bookings/rejection-notices")
@roles_required("event_coordinator")
def booking_rejection_notices():
    user = _current_user()
    rejected = (VenueBooking.query
                .join(Event, VenueBooking.event_id == Event.id)
                .filter(Event.coordinator_id == user.id,
                        VenueBooking.status == "rejected")
                .order_by(VenueBooking.decided_at.desc()).all())
    return jsonify([{
        "bookingId": b.id,
        "eventId": b.event_id,
        "message": f"Venue booking rejected: {b.venue.name if b.venue else 'Venue'} "
                   f"for {b.event.name if b.event else 'your event'}.",
        "reason": b.decision_reason,
        "alternativeSuggestion": b.alternative_suggestion,
        "rejectedAt": b.decided_at.isoformat() if b.decided_at else None,
    } for b in rejected]), 200


@venues_bp.get("/bookings/pending")
@roles_required("venue_staff")
def list_pending_bookings():
    user = _current_user()

    pending = (
        VenueBooking.query
        .join(Venue, VenueBooking.venue_id == Venue.id)
        .filter(
            VenueBooking.status.in_(("pending", "held")),
            Venue.created_by == user.id,
        )
        .order_by(
            VenueBooking.start_datetime.asc(),
            VenueBooking.id.asc(),
        )
        .all()
    )

    results = []

    for booking_row in pending:
        data = booking_row.to_dict()

        event = booking_row.event
        venue = booking_row.venue

        data.update({
            "eventName": event.name if event else None,
            "eventDescription": event.description if event else None,
            "expectedAttendance": (
                event.expected_attendance if event else None
            ),
            "venueName": venue.name if venue else None,
            "venueLocation": venue.location if venue else None,
        })

        results.append(data)

    return jsonify(results), 200

@venues_bp.get("/bookings/approved")
@roles_required("venue_staff")
def get_approved_bookings():
    user = _current_user()

    approved_bookings = (
        db.session.query(VenueBooking)
        .join(Venue, VenueBooking.venue_id == Venue.id)
        .filter(
            VenueBooking.status == "approved",
            Venue.created_by == user.id,
        )
        .order_by(VenueBooking.start_datetime.asc())
        .all()
    )

    return jsonify([
        {
            **booking.to_dict(),
            "venueName": booking.venue.name,
            "eventName": booking.event.name if booking.event else None,
        }
        for booking in approved_bookings
    ]), 200

@venues_bp.post("/bookings/<int:booking_id>/approve")
@roles_required("venue_staff")
def approve_booking(booking_id):
    user = _current_user()
    record = db.session.get(VenueBooking, booking_id)
    if not record:
        return jsonify({"error": "Booking not found"}), 404
    try:
        result = booking.approve_booking(record, user.id)
    except PermissionError as e:
        return jsonify({"error": str(e)}), 403
    except ValueError as e:
        return jsonify({"error": str(e)}), 409
    return jsonify(result.to_dict()), 200


@venues_bp.post("/bookings/<int:booking_id>/reject")
@roles_required("venue_staff")
def reject_booking(booking_id):
    user = _current_user()
    record = VenueBooking.query.get(booking_id)
    if not record:
        return jsonify({"error": "Booking not found"}), 404
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        return jsonify({"error": "Request body must be a JSON object"}), 400
    try:
        result = booking.reject_booking(
            record,
            user.id,
            reason=data.get("reason"),
            alternative=data.get("alternativeSuggestion"),
        )
    except PermissionError as e:
        return jsonify({"error": str(e)}), 403
    except ValueError as e:
        message = str(e)
        status = 409 if "already been decided" in message else 400
        return jsonify({"error": message}), status
    return jsonify(result.to_dict()), 200


@venues_bp.post("/bookings/<int:booking_id>/hold")
@roles_required("venue_staff")
def place_booking_hold(booking_id):
    return _manage_booking_hold(booking_id, "place")

@venues_bp.post("/bookings/<int:booking_id>/hold/extend")
@roles_required("venue_staff")
def extend_booking_hold(booking_id):
    return _manage_booking_hold(booking_id, "extend")

@venues_bp.post("/bookings/<int:booking_id>/hold/release")
@roles_required("venue_staff")
def release_booking_hold(booking_id):
    return _manage_booking_hold(booking_id, "release")

def _manage_booking_hold(booking_id, action):
    data = request.get_json(silent=True) or {}
    expiry = None
    if action != "release":
        try:
            raw = data.get("expiresAt")
            if not isinstance(raw, str):
                raise ValueError()
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                raise ValueError("Expiry must include a timezone offset")
            expiry = parsed.astimezone(timezone.utc).replace(tzinfo=None)
        except (TypeError, ValueError):
            return jsonify({"error": "expiresAt must be an ISO datetime with a timezone offset"}), 400
    try:
        result = booking.manage_hold(booking_id, _current_user().id, action, expiry)
    except LookupError as exc:
        return jsonify({"error": str(exc)}), 404
    except PermissionError as exc:
        return jsonify({"error": str(exc)}), 403
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 409 if "conflict" in str(exc).lower() else 400
    return jsonify(result.to_dict()), 200

@venues_bp.get("/bookings/hold-notices")
@roles_required("event_coordinator")
def hold_notices():
    """In-app notifications on request; a background worker is needed for push alerts."""
    from datetime import timedelta
    from app.common.time import utcnow
    now = utcnow()
    records = VenueBooking.query.filter(
        VenueBooking.requested_by == _current_user().id,
        VenueBooking.hold_expires_at.isnot(None),
        VenueBooking.status.in_(("held", "expired")),
    ).all()
    notices = []
    for b in records:
        if b.hold_expires_at <= now:
            kind = "expired"
            message = "Your tentative venue hold has expired."
        elif b.hold_expires_at <= now + timedelta(hours=24):
            kind = "expiring"
            message = "Your tentative venue hold expires within 24 hours."
        else:
            continue
        notices.append({"bookingId": b.id, "eventId": b.event_id, "type": kind,
                        "message": message, "expiresAt": b.hold_expires_at.isoformat()})
    return jsonify(notices), 200


@venues_bp.put("/bookings/<int:booking_id>/preparation")
@roles_required("venue_staff")
def update_booking_preparation(booking_id):
    user = _current_user()
    record = VenueBooking.query.get(booking_id)
    if not record:
        return jsonify({"error": "Booking not found"}), 404
    data = request.get_json() or {}
    try:
        result = preparation.update_venue_preparation(record, user, data)
    except PermissionError as e:
        return jsonify({"error": str(e)}), 403
    except preparation.PreparationUpdateError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify(result.to_dict()), 200
