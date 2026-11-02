import pytest

from app.equipment.services.preparation import (
    EquipmentPreparationError,
    confirm_equipment_suitability,
)
from app.extensions import db
from app.models.event import EventEquipmentRequirement
from app.models.user import User


@pytest.fixture
def setup(app, organiser, make_event, make_user):
    event_id = make_event(organiser, status="approved")

    def _setup(status="confirmed", needs_recheck=True):
        requirement = EventEquipmentRequirement(
            event_id=event_id,
            equipment_type="Projector",
            quantity=2,
            status=status,
            needs_recheck=needs_recheck,
        )
        db.session.add(requirement)
        db.session.commit()
        tech = db.session.get(
            User, make_user("tech@test.com", ["technical_support_staff"])
        )
        return requirement, tech

    return _setup


def test_confirm_equipment_suitability_clears_recheck_flag(setup):
    requirement, tech = setup()

    result = confirm_equipment_suitability(requirement, tech)

    assert result.needs_recheck is False


def test_confirm_suitability_requires_a_reserved_requirement(setup):
    requirement, tech = setup(status="requested")

    with pytest.raises(EquipmentPreparationError, match="Reserved"):
        confirm_equipment_suitability(requirement, tech)

    assert requirement.needs_recheck is True


def test_confirm_suitability_requires_a_recheck_flag(setup):
    requirement, tech = setup(needs_recheck=False)

    with pytest.raises(EquipmentPreparationError, match="not flagged"):
        confirm_equipment_suitability(requirement, tech)


def test_only_technical_support_staff_can_confirm_suitability(setup, make_user):
    requirement, _ = setup()
    coordinator = db.session.get(
        User, make_user("coordinator@test.com", ["event_coordinator"])
    )

    with pytest.raises(PermissionError):
        confirm_equipment_suitability(requirement, coordinator)

    assert requirement.needs_recheck is True
