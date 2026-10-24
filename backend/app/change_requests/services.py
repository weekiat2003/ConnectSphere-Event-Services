"""Event Change Requests: an Organiser requests a change to an event."""
from datetime import date, time

from app.common.time import utcnow
from app.common.text_validation import validate_descriptive_text
from app.extensions import db
from app.models.change_request import ChangeRequest, EventChangeHistory, ArrangementFlag
from app.models.event import Event, EventEquipmentRequirement, EventStatusHistory
from app.models.venue import BOOKING_APPROVED, ACTIVE_BOOKING_STATUSES, Venue, VenueBooking
from app.models.user import User
from app.models.equipment import EquipmentReservation
from app.notifications.services import triggers as notifications

REVIEWABLE_STATUSES = ("pending", "re_review")
RECONSIDERATION_REASON = "Needs reconsideration"
CHANGEABLE_STATUSES = ("approved", "planning", "confirmed")
STATUS_MESSAGE = "Changes can only be requested for an event that is approved, planning or confirmed"
DECIDED_STATUSES = ("processed", "rejected")

# Changing these can affect arrangements already made, so the request is
# marked significant. Everything else the organiser may change is routine.
SIGNIFICANT_FIELDS = {
    "proposed_date", "proposed_time", "expected_attendance",
    "capacity_needed", "required_layout", "required_facilities",
    "venue_id", "equipment_requirements",
}


class ChangeRequestError(ValueError):
    """`errors` maps a field name (or "changes" / "reason" / "event") to a message."""

    def __init__(self, errors: dict):
        self.errors = errors
        super().__init__("; ".join(errors.values()))


# ---------------------------------------------------------------------
# Cleaning: raw input -> JSON-friendly value, or ValueError(message)
# ---------------------------------------------------------------------

def _text(label, required):
    def clean(value):
        if not isinstance(value, str):
            raise ValueError(f"{label} must be text")
        value = value.strip()
        if required and not value:
            raise ValueError(f"{label} cannot be blank")
        return value or None
    return clean


def _positive_int(label):
    def clean(value):
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{label} must be a positive whole number")
        return value
    return clean


def _clean_date(value):
    try:
        parsed = value if isinstance(value, date) else date.fromisoformat(value)
    except (TypeError, ValueError):
        raise ValueError("Enter a valid date")
    # local calendar day, the same clock the organiser sees
    if parsed < date.today():
        raise ValueError("Event date cannot be in the past")
    return parsed.isoformat()


def _clean_time(value):
    try:
        parsed = value if isinstance(value, time) else time.fromisoformat(value)
    except (TypeError, ValueError):
        raise ValueError("Enter a valid time")
    return parsed.isoformat()


def _clean_bool(value):
    if not isinstance(value, bool):
        raise ValueError("Must be yes or no")
    return value


def _clean_facilities(value):
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ValueError("Facilities must be a list of text values")
    return [v.strip() for v in value if v.strip()]


def _clean_venue(value):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("Choose a venue from the catalogue")
    venue = db.session.get(Venue, value)
    if venue is None or not venue.is_active:
        raise ValueError("That venue is not available in the catalogue")
    return venue.id


def _valid_equipment_item(item):
    quantity = item.get("quantity") if isinstance(item, dict) else None
    return (
        isinstance(item, dict)
        and str(item.get("type") or "").strip() != ""
        and isinstance(quantity, int)
        and not isinstance(quantity, bool)
        and quantity > 0
    )


def _clean_equipment(value):
    if not isinstance(value, list) or not all(_valid_equipment_item(i) for i in value):
        raise ValueError("Each equipment item needs a type and a positive quantity")
    return value  # stored exactly as given


CLEANERS = {
    "name": _text("Event name", True),
    "purpose": _text("Purpose", True),
    "description": _text("Description", True),
    "category": _text("Category", False),
    "accessibility_needs": _text("Accessibility needs", False),
    "required_layout": _text("Required Layout", False),
    "proposed_date": _clean_date,
    "proposed_time": _clean_time,
    "expected_attendance": _positive_int("Expected attendance"),
    "capacity_needed": _positive_int("Capacity Needed"),
    "intended_capacity": _positive_int("Intended capacity"),
    "required_facilities": _clean_facilities,
    "registration_required": _clean_bool,
    "venue_id": _clean_venue,
    "equipment_requirements": _clean_equipment,
}


# ---------------------------------------------------------------------
# Current value and comparison
# ---------------------------------------------------------------------

def _current_value(event: Event, field: str):
    if field == "proposed_date":
        return event.proposed_date.isoformat() if event.proposed_date else None
    if field == "proposed_time":
        return event.proposed_time.isoformat() if event.proposed_time else None
    if field == "required_facilities":
        return list(event.required_facilities or [])
    if field == "registration_required":
        return bool(event.registration_required)
    if field == "venue_id":
        booking = (
            VenueBooking.query.filter_by(event_id=event.id, status=BOOKING_APPROVED)
            .order_by(VenueBooking.start_datetime.asc())
            .first()
        )
        return booking.venue_id if booking else None
    if field == "equipment_requirements":
        return [
            {"type": e.equipment_type, "quantity": e.quantity, "technicalNotes": e.technical_notes}
            for e in event.equipment_requirements
        ]
    return getattr(event, field)


def _equipment_key(items):
    return sorted(
        (str(i["type"]).strip().lower(), i["quantity"], (i.get("technicalNotes") or "").strip())
        for i in items
    )


def _blank(value):
    return value in (None, "", [])


def _same(field, current, proposed):
    if field == "equipment_requirements":
        return _equipment_key(current) == _equipment_key(proposed)
    return current == proposed or (_blank(current) and _blank(proposed))


# ---------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------
def current_venue_id(event: Event):
    """The venue shown as 'current' on the change form (earliest approved booking)."""
    return _current_value(event, "venue_id")

def can_request_change(event: Event, user_id: int) -> bool:
    return event.organiser_id == user_id and event.status in CHANGEABLE_STATUSES


def submit_change_request(event: Event, organiser_id: int, changes: dict, reason: str) -> ChangeRequest:
    if event.organiser_id != organiser_id:
        raise PermissionError("Only the organiser of this event can request a change")
    if event.status not in CHANGEABLE_STATUSES:
        raise ChangeRequestError({"event": STATUS_MESSAGE})

    errors, requested = {}, {}
    for field, raw in (changes or {}).items():
        if field not in CLEANERS:
            errors[field] = f"{field} cannot be changed through a change request"
            continue
        try:
            proposed = CLEANERS[field](raw)
        except ValueError as problem:
            errors[field] = str(problem)
            continue
        current = _current_value(event, field)
        if not _same(field, current, proposed):
            requested[field] = {"from": current, "to": proposed}

    if not errors and not requested:
        errors["changes"] = "Change at least one value before submitting"
    try:
        validate_descriptive_text(reason if isinstance(reason, str) else "", "reason")
    except ValueError as problem:
        errors["reason"] = str(problem)
    if errors:
        raise ChangeRequestError(errors)  # nothing has been added to the session

    change_request = ChangeRequest(
        event_id=event.id,
        organiser_id=organiser_id,
        requested_changes=requested,
        reason=reason.strip(),
        is_significant=any(field in SIGNIFICANT_FIELDS for field in requested),
        status="pending",
    )
    db.session.add(change_request)
    db.session.commit()
    return change_request


def list_change_requests_for_event(event: Event, user_id: int):
    """The organiser's own requests for this event, newest first."""
    if event.organiser_id != user_id:
        raise PermissionError("Only the organiser of this event can view its change requests")
    return (
        ChangeRequest.query.filter_by(event_id=event.id)
        .order_by(ChangeRequest.created_at.desc(), ChangeRequest.id.desc())
        .all()
    )


def list_change_requests_for_coordinator(coordinator_id: int):
    """Requests on events this Coordinator is currently assigned to, oldest
    first. Uses the event's current Coordinator, so reassignment is respected."""
    return (
        ChangeRequest.query.join(Event, ChangeRequest.event_id == Event.id)
        .filter(Event.coordinator_id == coordinator_id)
        .order_by(ChangeRequest.created_at.asc(), ChangeRequest.id.asc())
        .all()
    )


WITHDRAWABLE_STATUSES = ("submitted", "under_review", "approved", "planning", "confirmed")
WITHDRAWAL_STATUS_MESSAGE = (
    "Withdrawal can only be requested for an event that is submitted, under review, "
    "approved, planning or confirmed"
)


def _has_pending_withdrawal(event: Event) -> bool:
    return (
        ChangeRequest.query.filter_by(event_id=event.id, request_type="withdrawal", status="pending").first()
        is not None
    )


def can_request_withdrawal(event: Event, user_id: int) -> bool:
    """Offered to the owner while the event is withdrawable and no withdrawal is already pending."""
    return (
        event.organiser_id == user_id
        and event.status in WITHDRAWABLE_STATUSES
        and not _has_pending_withdrawal(event)
    )


def request_withdrawal(event: Event, organiser_id: int, reason: str) -> ChangeRequest:
    if event.organiser_id != organiser_id:
        raise PermissionError("Only the organiser of this event can request its withdrawal")
    if event.status not in WITHDRAWABLE_STATUSES:
        raise ChangeRequestError({"event": WITHDRAWAL_STATUS_MESSAGE})

    errors = {}
    try:
        validate_descriptive_text(reason if isinstance(reason, str) else "", "reason")
    except ValueError as problem:
        errors["reason"] = str(problem)
    if _has_pending_withdrawal(event):
        errors["request"] = "A withdrawal request is already pending for this event"
    if errors:
        raise ChangeRequestError(errors)  # nothing has been added to the session

    withdrawal = ChangeRequest(
        event_id=event.id,
        organiser_id=organiser_id,
        request_type="withdrawal",
        requested_changes={},
        reason=reason.strip(),
        is_significant=False,  # not a field change; the Coordinator handles it through the cancel flow
        status="pending",
    )
    db.session.add(withdrawal)
    db.session.commit()
    return withdrawal

# ---------------------------------------------------------------------
# Coordinator review
# ---------------------------------------------------------------------

def _summary(change_request: ChangeRequest, event: Event) -> dict:
    row = change_request.to_dict()
    row["eventName"] = event.name
    row["organiserName"] = event.organiser.name if event.organiser else None
    return row


def list_review_queue(coordinator_id: int):
    pairs = (
        db.session.query(ChangeRequest, Event)
        .join(Event, ChangeRequest.event_id == Event.id)
        .filter(
            Event.coordinator_id == coordinator_id,
            ChangeRequest.status.in_(REVIEWABLE_STATUSES),
        )
        .order_by(ChangeRequest.created_at.asc(), ChangeRequest.id.asc())
        .all()
    )
    return [_summary(change_request, event) for change_request, event in pairs]


def _affected_arrangements(event: Event) -> list:
    bookings = (
        VenueBooking.query.filter(
            VenueBooking.event_id == event.id,
            VenueBooking.status.in_(ACTIVE_BOOKING_STATUSES),
        )
        .order_by(VenueBooking.start_datetime.asc())
        .all()
    )
    arrangements = [{"kind": "venue_booking", "venueId": b.venue_id, "status": b.status} for b in bookings]
    arrangements += [
        {"kind": "equipment", "type": e.equipment_type, "quantity": e.quantity, "status": e.status}
        for e in event.equipment_requirements
    ]
    return arrangements


def _available_actions(change_request: ChangeRequest) -> list:
    if change_request.status == "pending":
        if change_request.request_type == "withdrawal":
            return ["cancel_event", "reject_change"]

        if change_request.is_significant:
            return ["trigger_re_review", "reject_change"]

        return ["process_change", "reject_change"]

    if change_request.status == "re_review":
        return ["apply_change"]

    return []


def _decision(change_request: ChangeRequest):
    if change_request.status not in DECIDED_STATUSES:
        return None

    decider = (
        db.session.get(User, change_request.coordinator_id)
        if change_request.coordinator_id
        else None
    )

    return {
        "status": change_request.status,
        "decidedBy": decider.name if decider else None,
        "decidedAt": (
            change_request.decided_at.isoformat()
            if change_request.decided_at
            else None
        ),
        "reason": change_request.decision_reason,
    }


def get_review_detail(request_id: int, coordinator_id: int) -> dict:
    """Everything the review screen needs. Read-only: nothing is written."""
    change_request = db.session.get(ChangeRequest, request_id)
    if change_request is None:
        raise LookupError("Change request not found")
    event = db.session.get(Event, change_request.event_id)
    if event is None or event.coordinator_id != coordinator_id:
        raise PermissionError("Only the Coordinator assigned to this event can review its change requests")

    shows_arrangements = change_request.request_type == "change" and change_request.is_significant
    return {
        "request": change_request.to_dict(),
        "event": {
            "id": event.id,
            "name": event.name,
            "status": event.status,
            "organiserName": event.organiser.name if event.organiser else None,
        },
        "changes": [
            {"field": field, "current": values["from"], "proposed": values["to"]}
            for field, values in (change_request.requested_changes or {}).items()
        ],
        "affectedArrangements": _affected_arrangements(event) if shows_arrangements else [],
        "availableActions": _available_actions(change_request),
        "decision": _decision(change_request),
        "reReview": _re_review_record(change_request, event),
    }

# ---------------------------------------------------------------------
# Coordinator processes a routine change
# ---------------------------------------------------------------------

# For these, a stored None means "clear the value" and is allowed.
CLEARABLE_FIELDS = {"category", "accessibility_needs"}
PROCESS_STATUS_MESSAGE = "A change can only be processed while the event is approved, planning or confirmed"


def _revalidate(requested: dict):
    """Run every stored proposed value through the same checks as submission.
    Returns ({field: cleaned value}, {field: error message})."""
    cleaned, errors = {}, {}
    for field, values in requested.items():
        proposed = values.get("to") if isinstance(values, dict) else None
        if field not in CLEANERS:
            errors[field] = f"{field} cannot be changed through a change request"
        elif proposed is None and field in CLEARABLE_FIELDS:
            cleaned[field] = None
        else:
            try:
                cleaned[field] = CLEANERS[field](proposed)
            except ValueError as problem:
                errors[field] = str(problem)
    return cleaned, errors


def process_routine_change(request_id: int, coordinator_id: int, dry_run: bool = False) -> ChangeRequest:
    """Apply a pending routine change to the event, all or nothing.
    dry_run runs every check and writes nothing."""
    # Locking read: of two simultaneous attempts, the second waits and then sees "processed".
    change_request = db.session.query(ChangeRequest).filter_by(id=request_id).with_for_update().first()
    if change_request is None:
        raise LookupError("Change request not found")
    event = db.session.get(Event, change_request.event_id)
    if event is None or event.coordinator_id != coordinator_id:
        raise PermissionError("Only the Coordinator assigned to this event can process its change requests")

    requested = change_request.requested_changes or {}
    if change_request.status != "pending":
        raise ChangeRequestError({"request": "This change request has already been decided"})
    if change_request.request_type == "withdrawal":
        raise ChangeRequestError(
            {"request": "A withdrawal request is handled by cancelling the event, not by processing a change"}
        )
    if change_request.is_significant or any(field in SIGNIFICANT_FIELDS for field in requested):
        raise ChangeRequestError(
            {"request": "A significant change needs re-review and cannot be processed directly"}
        )
    if event.status not in CHANGEABLE_STATUSES:
        raise ChangeRequestError({"event": PROCESS_STATUS_MESSAGE})

    cleaned, errors = _revalidate(requested)
    if errors:
        raise ChangeRequestError(errors)  # nothing has been written
    if dry_run:
        return change_request

    before = notifications.schedule_snapshot(event)
    for field, proposed in cleaned.items():
        current = _current_value(event, field)  # the live value being replaced
        if _same(field, current, proposed):
            continue
        db.session.add(
            EventChangeHistory(
                event_id=event.id,
                change_request_id=change_request.id,
                field=field,
                old_value=current,
                new_value=proposed,
                changed_by=coordinator_id,
            )
        )
        setattr(event, field, proposed)

    change_request.status = "processed"
    change_request.coordinator_id = coordinator_id
    change_request.decided_at = utcnow()
    notifications.notify_organiser_of_change_request(event, change_request, "processed")
    notifications.notify_event_details_changed(event, before)
    db.session.commit()
    return change_request

def reject_change_request(
    request_id: int, coordinator_id: int, reason, dry_run: bool = False
) -> ChangeRequest:
    """Reject a pending change request. Nothing on the event, its venue
    bookings or its equipment is touched. dry_run runs every check and
    writes nothing."""
    change_request = _get_locked_request(request_id)
    _assert_assigned_coordinator(change_request, coordinator_id)  # PermissionError otherwise

    if change_request.status != "pending":
        raise ChangeRequestError({"request": "Only a pending change request can be rejected"})

    try:
        validate_descriptive_text(reason if isinstance(reason, str) else "", "reason")
    except ValueError as problem:
        raise ChangeRequestError({"reason": str(problem)})

    if dry_run:
        return change_request

    change_request.status = "rejected"
    change_request.coordinator_id = coordinator_id
    change_request.decision_reason = reason.strip()
    change_request.decided_at = utcnow()
    event = db.session.get(Event, change_request.event_id)
    notifications.notify_organiser_of_change_request(event, change_request, "rejected")
    db.session.commit()
    return change_request

def _python_value(field: str, value):
    """Change-request JSON stores dates/times as ISO strings, but the Event
    model columns need Python date/time objects."""
    if field == "proposed_date" and isinstance(value, str):
        return date.fromisoformat(value)

    if field == "proposed_time" and isinstance(value, str):
        return time.fromisoformat(value)

    return value

# ---------------------------------------------------------------------
# Coordinator processes a significant change
# ---------------------------------------------------------------------

REVIEWABLE_STATUSES = ("pending", "re_review")
RECONSIDERATION_REASON = "Needs reconsideration"


def _get_locked_request(request_id: int) -> ChangeRequest:
    change_request = (
        db.session.query(ChangeRequest)
        .filter_by(id=request_id)
        .with_for_update()
        .first()
    )
    if change_request is None:
        raise LookupError("Change request not found")
    return change_request


def _assert_assigned_coordinator(change_request: ChangeRequest, coordinator_id: int) -> Event:
    event = db.session.get(Event, change_request.event_id)
    if event is None or event.coordinator_id != coordinator_id:
        raise PermissionError(
            "Only the Coordinator assigned to this event can review its change requests"
        )
    return event


def _live_arrangements(event: Event) -> list[dict]:
    """Arrangements that still need attention: pending, approved and held
    venue bookings, plus the event's equipment requirement lines."""
    bookings = (
        VenueBooking.query.filter(
            VenueBooking.event_id == event.id,
            VenueBooking.status.in_(ACTIVE_BOOKING_STATUSES),
        )
        .order_by(VenueBooking.start_datetime.asc())
        .all()
    )

    arrangements = [
        {"kind": "venue_booking", "target_id": booking.id, "booking": booking}
        for booking in bookings
    ]
    arrangements += [
        {"kind": "equipment", "target_id": requirement.id, "requirement": requirement}
        for requirement in event.equipment_requirements
    ]
    return arrangements


def _create_reconsideration_flags(
    change_request: ChangeRequest, event: Event
) -> list[ArrangementFlag]:
    flags = []
    for arrangement in _live_arrangements(event):
        flag = ArrangementFlag(
            event_id=event.id,
            change_request_id=change_request.id,
            kind=arrangement["kind"],
            target_id=arrangement["target_id"],
            reason=RECONSIDERATION_REASON,
        )
        db.session.add(flag)
        flags.append(flag)
    return flags

def trigger_re_review(
    request_id: int, coordinator_id: int, dry_run: bool = False
) -> ChangeRequest:
    """Send a pending significant change for re-review.

    The proposed change is not applied. Live arrangements are flagged as
    needing reconsideration, but no booking, hold or equipment arrangement is
    cancelled, released or otherwise changed.
    """
    change_request = _get_locked_request(request_id)
    event = _assert_assigned_coordinator(change_request, coordinator_id)

    if change_request.request_type == "withdrawal":
        raise ChangeRequestError(
            {"request": "A withdrawal request cannot be sent for re-review"}
        )

    if not change_request.is_significant:
        raise ChangeRequestError(
            {"request": "Only a significant change can be sent for re-review"}
        )

    if change_request.status != "pending":
        raise ChangeRequestError(
            {"request": "This change request has already been decided or sent for re-review"}
        )

    if event.status not in CHANGEABLE_STATUSES:
        raise ChangeRequestError({"event": STATUS_MESSAGE})

    if dry_run:
        return change_request

    change_request.status = "re_review"
    change_request.re_review_by = coordinator_id
    change_request.re_review_at = utcnow()

    # Still unresolved: these remain unset until the coordinator records the
    # final outcome.
    change_request.coordinator_id = None
    change_request.decided_at = None
    change_request.decision_reason = None

    _create_reconsideration_flags(change_request, event)

    notifications.notify_organiser_of_change_request(event, change_request, "re_review")
    if event.status == "confirmed":
        old_status = event.status
        event.status = "planning"
        db.session.add(
            EventStatusHistory(
                event_id=event.id,
                old_status=old_status,
                new_status=event.status,
                changed_by=coordinator_id,
                reason="Significant change sent for re-review",
            )
        )

    db.session.commit()
    return change_request

def _re_review_record(change_request: ChangeRequest, event: Event) -> dict | None:
    if change_request.re_review_at is None:
        return None

    triggerer = (
        db.session.get(User, change_request.re_review_by)
        if change_request.re_review_by
        else None
    )

    flags = {
        (flag.kind, flag.target_id): flag
        for flag in ArrangementFlag.query.filter_by(
            change_request_id=change_request.id
        ).all()
    }

    flagged = []
    for arrangement in _live_arrangements(event):
        flag = flags.get((arrangement["kind"], arrangement["target_id"]))
        needs_reconsideration = bool(flag and flag.cleared_at is None)

        if arrangement["kind"] == "venue_booking":
            booking = arrangement["booking"]
            flagged.append({
                "kind": "venue_booking",
                "venueId": booking.venue_id,
                "status": booking.status,
                "needsReconsideration": needs_reconsideration,
            })
        else:
            requirement = arrangement["requirement"]
            flagged.append({
                "kind": "equipment",
                "type": requirement.equipment_type,
                "quantity": requirement.quantity,
                "status": requirement.status,
                "needsReconsideration": needs_reconsideration,
            })

    return {
        "triggeredBy": triggerer.name if triggerer else None,
        "triggeredAt": (
            change_request.re_review_at.isoformat()
            if change_request.re_review_at
            else None
        ),
        "flaggedArrangements": flagged,
    }

def _replace_equipment_requirements(event: Event, items: list[dict]) -> None:
    old_types = {
        requirement.id: (requirement.equipment_type or "").strip().lower()
        for requirement in event.equipment_requirements
    }
    reserved = [
        (reservation, reservation.equipment_requirement_id)
        for reservation in EquipmentReservation.query.filter_by(
            event_id=event.id, status="reserved"
        ).all()
    ]

    event.equipment_requirements.clear()

    new_by_type = {}
    for item in items:
        requirement = EventEquipmentRequirement(
            equipment_type=str(item["type"]).strip(),
            quantity=item["quantity"],
            technical_notes=item.get("technicalNotes"),
            status="requested",
        )
        event.equipment_requirements.append(requirement)
        new_by_type.setdefault(requirement.equipment_type.lower(), requirement)

    db.session.flush()  # gives the new requirements their ids

    # A reservation follows the new requirement of the same equipment type;
    # if that type was removed, its reservation is released.
    for reservation, old_requirement_id in reserved:
        target = new_by_type.get(old_types.get(old_requirement_id))
        if target is not None:
            reservation.equipment_requirement_id = target.id
        else:
            reservation.status = "released"


def _apply_cleaned_change(
    event: Event,
    change_request: ChangeRequest,
    field: str,
    current,
    proposed,
    coordinator_id: int,
) -> None:
    db.session.add(
        EventChangeHistory(
            event_id=event.id,
            change_request_id=change_request.id,
            field=field,
            old_value=current,
            new_value=proposed,
            changed_by=coordinator_id,
        )
    )

    if field == "equipment_requirements":
        _replace_equipment_requirements(event, proposed)
        return

    if field == "venue_id":
        # The event's displayed current venue comes from its approved booking.
        # A venue change is a coordinator/staff decision recorded here; it does
        # not move, cancel or release an existing booking.
        return

    setattr(event, field, proposed)



def _planned_updates(
    event: Event, requested: dict
) -> list[tuple[str, object, object]]:
    """Validate and read every current value before changing anything."""
    cleaned, errors = _revalidate(requested)
    if errors:
        raise ChangeRequestError(errors)

    planned = []
    with db.session.no_autoflush:
        for field, proposed in cleaned.items():
            current = _current_value(event, field)
            if not _same(field, current, proposed):
                planned.append((field, current, proposed))

    return planned


def apply_re_reviewed_change(
    request_id: int, coordinator_id: int, dry_run: bool = False
) -> ChangeRequest:
    """Record that a significant change under re-review is going ahead."""
    change_request = _get_locked_request(request_id)
    event = _assert_assigned_coordinator(change_request, coordinator_id)

    if change_request.status != "re_review":
        raise ChangeRequestError(
            {"request": "Only a request under re-review can be marked as going ahead"}
        )

    if event.status not in CHANGEABLE_STATUSES:
        raise ChangeRequestError({"event": PROCESS_STATUS_MESSAGE})

    planned = _planned_updates(
        event, change_request.requested_changes or {}
    )

    if dry_run:
        return change_request

    before = notifications.schedule_snapshot(event)
    for field, current, proposed in planned:
        db.session.add(
            EventChangeHistory(
                event_id=event.id,
                change_request_id=change_request.id,
                field=field,
                old_value=current,
                new_value=proposed,
                changed_by=coordinator_id,
            )
        )

        if field == "equipment_requirements":
            _replace_equipment_requirements(event, proposed)
        elif field == "venue_id":
            # The current venue is derived from the approved booking.
            # Record the coordinator's decision without changing bookings.
            continue
        else:
            setattr(event, field, _python_value(field, proposed))

    # Make the event/history writes explicit before the flag update queries
    # ArrangementFlag. This avoids an unexpected query-invoked autoflush.
    db.session.flush()

    now = utcnow()

    ArrangementFlag.query.filter_by(
        change_request_id=change_request.id
    ).update(
        {"cleared_at": now},
        synchronize_session=False,
    )

    change_request.status = "processed"
    change_request.coordinator_id = coordinator_id
    change_request.decided_at = now

    notifications.notify_organiser_of_change_request(event, change_request, "applied")
    notifications.notify_event_details_changed(event, before)
    db.session.commit()
    return change_request