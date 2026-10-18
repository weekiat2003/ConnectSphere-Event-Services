"""
Event Information Management
-----------------------------
US-1: core-field edits by the assigned Event Coordinator during planning.
US-4: confirmed-event lock (checked first -- it overrides everything else,
including who is making the attempt).

Preparation-progress updates by Venue Staff / Technical Support Staff are
NOT handled here -- see app/venues/services/preparation.py and
app/equipment/services/preparation.py. They aren't core event information
and are never subject to the lock below.
"""
from datetime import date, datetime, time

from app.extensions import db
from app.common.text_validation import validate_descriptive_text
from app.models.event import Event, EventEquipmentRequirement, EventFieldEditLog

ORDINARY_FIELDS = {"name", "purpose", "description", "category", "registration_required", "intended_capacity"}
SIGNIFICANT_FIELDS = {
    "proposed_date", "proposed_time", "expected_attendance",
    "capacity_needed", "required_layout", "accessibility_needs", "required_facilities",
    "equipment_requirements",
}
EDITABLE_FIELDS = ORDINARY_FIELDS | SIGNIFICANT_FIELDS

# US-1 AC1: Under Review, Approved, or Planning only -- not Safety Check
# (a review may be in progress) and not Confirmed (that's the US-4 lock).
EDITABLE_STATUSES = {"under_review", "approved", "planning"}


class EventUpdateError(Exception):
    pass


class EventLockedError(EventUpdateError):
    pass


class EventNotEditableStatusError(EventUpdateError):
    pass


class OfflineReviewNotConfirmedError(ValueError):
    pass


class EventValidationError(ValueError):
    def __init__(self, field_errors: dict):
        self.field_errors = field_errors
        super().__init__("Validation failed: " + ", ".join(field_errors))


def update_event_fields(event: Event, user, changes: dict, offline_review_confirmed: bool = False) -> Event:
    """
    `changes` is {field_name: new_value}, restricted to EDITABLE_FIELDS.
    Raises:
      EventLockedError              -- event is confirmed (map to 423)
      PermissionError                -- not the assigned Coordinator (403)
      EventNotEditableStatusError    -- status outside EDITABLE_STATUSES (409)
      OfflineReviewNotConfirmedError -- significant fields w/o confirmation (400)
      EventValidationError           -- bad field values, .field_errors dict (400)
    """
    if not isinstance(changes, dict):
        raise EventValidationError({"fields": "Expected an object of fields to update"})

    if event.status == "confirmed":
        _log_edit(
            event, user, list(changes), {}, was_rejected=True,
            rejection_reason="Event is confirmed; use an Event Change Request",
        )
        raise EventLockedError(
            "This event is confirmed. Core fields can only be changed through an Event Change Request."
        )

    if event.coordinator_id != getattr(user, "id", None):
        raise PermissionError("Only the assigned Event Coordinator can edit this event.")

    if event.status not in EDITABLE_STATUSES:
        raise EventNotEditableStatusError(f"Event information cannot be edited while status is '{event.status}'.")

    unknown_fields = set(changes) - EDITABLE_FIELDS
    if unknown_fields:
        raise EventValidationError({f: "This field cannot be edited here" for f in unknown_fields})

    changes = _normalize_changes(changes)
    significant_fields = set(changes) & SIGNIFICANT_FIELDS
    if significant_fields and not offline_review_confirmed:
        raise OfflineReviewNotConfirmedError(
            "Changing date, time, attendance, venue, or equipment requirements requires "
            "confirming the offline review has been done first."
        )

    field_errors = _validate_changes(event, changes)
    if field_errors:
        raise EventValidationError(field_errors)

    old_values = {f: _json_value(_current_field_value(event, f)) for f in changes}
    for field, value in changes.items():
        if field == "equipment_requirements":
            _update_equipment_requirements(event, value)
        else:
            setattr(event, field, value)

    if significant_fields:
        _flag_arrangements_needs_reconsideration(event)

    _log_edit(
        event, user, list(changes), old_values,
        {field: _json_value(value) for field, value in changes.items()},
        was_significant=bool(significant_fields),
    )
    db.session.commit()
    return event


def _normalize_changes(changes: dict) -> dict:
    normalized = dict(changes)
    for field, parser in (("proposed_date", date.fromisoformat), ("proposed_time", time.fromisoformat)):
        value = normalized.get(field)
        if field not in normalized or value is None:
            continue
        if isinstance(value, (date, time)):
            continue
        if not isinstance(value, str):
            continue
        try:
            normalized[field] = parser(value)
        except ValueError:
            pass
    return normalized


def _validate_changes(event: Event, changes: dict) -> dict:
    errors = {}

    for field in ("name", "purpose", "description", "accessibility_needs", "required_layout"):
        if field in changes:
            if not isinstance(changes[field], str) or not changes[field].strip():
                errors[field] = f"{field.replace('_', ' ').capitalize()} is required"
            elif field in {"name", "purpose", "description"}:
                try:
                    validate_descriptive_text(changes[field], field)
                except ValueError as exc:
                    errors[field] = str(exc)

    for field, expected_type in (("proposed_date", date), ("proposed_time", time)):
        if field in changes:
            value = changes[field]
            if value is None or value == "":
                errors[field] = f"{field.replace('_', ' ').capitalize()} is required"
            elif not isinstance(value, expected_type):
                errors[field] = f"{field.replace('_', ' ').capitalize()} must be a valid ISO value"

    if "proposed_date" in changes or "proposed_time" in changes:
        proposed_date = changes.get("proposed_date", event.proposed_date)
        proposed_time = changes.get("proposed_time", event.proposed_time)
        if proposed_date is None:
            errors["proposed_date"] = "Proposed date is required"
        if proposed_time is None:
            errors["proposed_time"] = "Proposed time is required"

    expected_attendance = changes.get("expected_attendance", event.expected_attendance)
    if "expected_attendance" in changes:
        if (
            isinstance(expected_attendance, bool)
            or not isinstance(expected_attendance, int)
            or expected_attendance <= 0
        ):
            errors["expected_attendance"] = "Expected attendance must be a positive number"

    capacity_needed = changes.get("capacity_needed", event.capacity_needed)
    if "capacity_needed" in changes:
        if (
            isinstance(capacity_needed, bool)
            or not isinstance(capacity_needed, int)
            or capacity_needed <= 0
        ):
            errors["capacity_needed"] = "Capacity needed must be a positive number"

    if (
        ("capacity_needed" in changes or "expected_attendance" in changes)
        and isinstance(capacity_needed, int) and not isinstance(capacity_needed, bool)
        and isinstance(expected_attendance, int) and not isinstance(expected_attendance, bool)
        and capacity_needed < expected_attendance
    ):
        errors.setdefault("capacity_needed", "Capacity needed cannot be less than expected attendance")

    if "proposed_date" in changes and changes["proposed_date"] is None:
        errors["proposed_date"] = "Proposed date is required"

    if "required_facilities" in changes and not isinstance(changes["required_facilities"], list):
        errors["required_facilities"] = "Required facilities must be a list"

    if "registration_required" in changes and not isinstance(changes["registration_required"], bool):
        errors["registration_required"] = "Registration required must be true or false"
    registration_required = changes.get("registration_required", event.registration_required)
    intended_capacity = changes.get("intended_capacity", event.intended_capacity)
    if registration_required and ("registration_required" in changes or "intended_capacity" in changes):
        if isinstance(intended_capacity, bool) or not isinstance(intended_capacity, int) or intended_capacity <= 0:
            errors["intended_capacity"] = "Intended capacity must be a positive number when registration is required"
    elif "intended_capacity" in changes and intended_capacity is not None and (
        isinstance(intended_capacity, bool) or not isinstance(intended_capacity, int) or intended_capacity <= 0
    ):
        errors["intended_capacity"] = "Intended capacity must be a positive number"

    if "equipment_requirements" in changes:
        requirements = changes["equipment_requirements"]
        if not isinstance(requirements, list) or not requirements:
            errors["equipment_requirements"] = "At least one equipment requirement is required"
        else:
            for index, requirement in enumerate(requirements):
                field = f"equipment_requirements[{index}]"
                if not isinstance(requirement, dict):
                    errors[field] = "Each equipment requirement must be an object"
                    continue
                equipment_type = requirement.get("type", requirement.get("equipment_type"))
                quantity = requirement.get("quantity")
                if not isinstance(equipment_type, str) or not equipment_type.strip():
                    errors[f"{field}.type"] = "Equipment type is required"
                if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
                    errors[f"{field}.quantity"] = "Equipment quantity must be a positive number"
                requirement_id = requirement.get("id")
                if requirement_id is not None:
                    existing_ids = {item.id for item in event.equipment_requirements}
                    if requirement_id not in existing_ids:
                        errors[f"{field}.id"] = "Equipment requirement does not belong to this event"

    return errors


def _current_field_value(event: Event, field: str):
    if field == "equipment_requirements":
        return [
            {"id": item.id, "type": item.equipment_type, "quantity": item.quantity,
             "technicalNotes": item.technical_notes}
            for item in event.equipment_requirements
        ]
    return getattr(event, field)


def _update_equipment_requirements(event: Event, requirements: list):
    existing = {item.id: item for item in event.equipment_requirements}
    current_items = list(event.equipment_requirements)
    for index, values in enumerate(requirements):
        requirement_id = values.get("id")
        if requirement_id is not None:
            item = existing[requirement_id]
        elif index < len(current_items):
            item = current_items[index]
        else:
            item = EventEquipmentRequirement(event_id=event.id)
            event.equipment_requirements.append(item)
        item.equipment_type = values.get("type", values.get("equipment_type"))
        item.quantity = values["quantity"]
        if "technicalNotes" in values:
            item.technical_notes = values["technicalNotes"]
        elif "technical_notes" in values:
            item.technical_notes = values["technical_notes"]
        db.session.add(item)


def _json_value(value):
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _flag_arrangements_needs_reconsideration(event: Event):
    from app.models.venue import VenueBooking, BOOKING_APPROVED, BOOKING_HELD  # local import avoids a circular import
    bookings = VenueBooking.query.filter(
        VenueBooking.event_id == event.id,
        VenueBooking.status.in_((BOOKING_APPROVED, BOOKING_HELD)),
    ).all()
    for b in bookings:
        b.needs_reconsideration = True
        db.session.add(b)

    for requirement in event.equipment_requirements:
        requirement.needs_recheck = True
        db.session.add(requirement)
def _log_edit(event, user, fields_changed, old_values, new_values=None,
              was_significant=False, was_rejected=False, rejection_reason=None):
    db.session.add(EventFieldEditLog(
        event_id=event.id,
        changed_by=getattr(user, "id", None),
        fields_changed=fields_changed,
        old_values=old_values,
        new_values=new_values or {},
        was_significant=was_significant,
        was_rejected=was_rejected,
        rejection_reason=rejection_reason,
    ))
    if was_rejected:
        db.session.commit()