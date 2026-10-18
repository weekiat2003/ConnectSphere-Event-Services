"""
Validation for Event Request Creation submission.

Runs against an already-populated Event object (after _apply_fields has run),
so it doesn't need to know about raw request-body key names.
"""
from datetime import date

REQUIRED_FOR_SUBMISSION = [
    "name",
    "purpose",
    "description",
    "proposed_date",
    "proposed_time",
    "expected_attendance",
    "capacity_needed",
    "required_layout",
    "accessibility_needs",
]


def validate_for_submission(event) -> list[str]:
    """Returns a list of human-readable error strings. Empty list = valid."""
    errors = []

    missing = [f for f in REQUIRED_FOR_SUBMISSION if getattr(event, f) in (None, "")]
    if missing:
        errors.append(f"Missing required field(s): {', '.join(missing)}")

    if event.expected_attendance is not None and event.expected_attendance <= 0:
        errors.append("Expected attendance must be greater than zero")

    if event.capacity_needed is not None and event.capacity_needed <= 0:
        errors.append("Venue capacity requirement must be greater than zero")

    if event.proposed_date is not None and event.proposed_date < date.today():
        errors.append("Proposed date cannot be in the past")

    if event.registration_required and not event.intended_capacity:
        errors.append("Intended capacity is required when registration is enabled")

    if event.intended_capacity is not None and event.intended_capacity <= 0:
        errors.append("Intended capacity must be greater than zero")

    for idx, item in enumerate(event.equipment_requirements):
        if not item.equipment_type:
            errors.append(f"Equipment item {idx + 1}: type is required")
        if not item.quantity or item.quantity <= 0:
            errors.append(f"Equipment item {idx + 1}: quantity must be greater than zero")

    return errors