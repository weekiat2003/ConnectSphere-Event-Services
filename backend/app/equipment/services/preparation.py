"""Equipment suitability re-checks by Technical Support Staff."""
from app.common.time import utcnow
from app.extensions import db
from app.models.event import EventEquipmentRequirement
from app.notifications.services import triggers as notifications


class EquipmentPreparationError(Exception):
    pass


def confirm_equipment_suitability(
    requirement: EventEquipmentRequirement, user
) -> EventEquipmentRequirement:
    if not user.has_role("technical_support_staff"):
        raise PermissionError("Only Technical Support Staff can confirm equipment suitability.")
    if requirement.status != "confirmed":
        raise EquipmentPreparationError(
            "Suitability can only be confirmed when the equipment requirement is Reserved."
        )
    if not requirement.needs_recheck:
        raise EquipmentPreparationError(
            "This equipment requirement is not flagged for a suitability re-check."
        )

    requirement.needs_recheck = False
    requirement.updated_at = utcnow()
    db.session.add(requirement)
    notifications.notify_coordinator_of_equipment_recheck(
        requirement, "suitability_confirmed"
    )
    db.session.commit()

    return requirement