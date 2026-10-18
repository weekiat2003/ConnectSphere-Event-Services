"""
Equipment preparation-progress updates by Technical Support Staff (US-3).
"""
from app.common.time import utcnow
from app.extensions import db
from app.models.event import EventEquipmentRequirement

PREPARATION_FIELDS = {"testing_status", "installation_status"}
ACTIVE_REQUIREMENT_STATUSES = {"requested", "confirmed"}
PREPARATION_STATUSES = {"pending", "in_progress", "done"}


class EquipmentPreparationError(Exception):
    pass


def update_equipment_preparation(requirement: EventEquipmentRequirement, user, changes: dict) -> EventEquipmentRequirement:
    if not isinstance(changes, dict):
        raise EquipmentPreparationError("Preparation changes must be an object")
    if not changes:
        raise EquipmentPreparationError("At least one preparation field is required")

    if not user.has_role("technical_support_staff"):
        raise PermissionError("Only Technical Support Staff can update equipment preparation information.")

    if requirement.status not in ACTIVE_REQUIREMENT_STATUSES:
        raise EquipmentPreparationError(
            "Equipment preparation can only be updated while the requirement is requested or confirmed."
        )

    unknown_fields = set(changes) - PREPARATION_FIELDS
    if unknown_fields:
        raise EquipmentPreparationError(f"Cannot update fields: {', '.join(sorted(unknown_fields))}")

    for field, value in changes.items():
        if not isinstance(value, str) or value not in PREPARATION_STATUSES:
            raise EquipmentPreparationError(
                f"{field.replace('_', ' ').capitalize()} must be pending, in_progress, or done."
            )

    for field, value in changes.items():
        setattr(requirement, field, value)

    requirement.updated_at = utcnow()
    db.session.add(requirement)
    db.session.commit()
    return requirement