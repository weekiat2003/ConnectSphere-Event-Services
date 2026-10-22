import pytest

from app.equipment.services.preparation import (
    EquipmentPreparationError,
    update_equipment_preparation,
)
from app.extensions import db
from app.models.event import EventEquipmentRequirement
from app.models.user import User


@pytest.fixture
def setup(app, organiser, make_event, make_user):
    event_id = make_event(organiser, status="approved")

    def _setup(status="requested"):
        line = EventEquipmentRequirement(
            event_id=event_id, equipment_type="Projector", quantity=2, status=status)
        db.session.add(line)
        db.session.commit()
        tech = db.session.get(User, make_user("tech@test.com", ["technical_support_staff"]))
        return line, tech
    return _setup


def test_sets_the_testing_status(setup):
    line, tech = setup()
    result = update_equipment_preparation(line, tech, {"testing_status": "in_progress"})
    assert result.testing_status == "in_progress"
    assert result.installation_status == "pending"


def test_sets_both_fields_at_once(setup):
    line, tech = setup()
    update_equipment_preparation(line, tech, {"testing_status": "done", "installation_status": "done"})
    db.session.expire_all()
    saved = db.session.get(EventEquipmentRequirement, line.id)
    assert (saved.testing_status, saved.installation_status) == ("done", "done")


@pytest.mark.parametrize("status", ["requested", "confirmed"])
def test_allowed_while_the_requirement_is_requested_or_reserved(setup, status):
    line, tech = setup(status=status)
    assert update_equipment_preparation(line, tech, {"installation_status": "done"}).installation_status == "done"


@pytest.mark.parametrize("value", ["finished", "", "Done", None, 3])
def test_invalid_status_is_rejected_and_nothing_changes(setup, value):
    line, tech = setup()
    with pytest.raises(EquipmentPreparationError):
        update_equipment_preparation(line, tech, {"testing_status": value})
    db.session.expire_all()
    assert db.session.get(EventEquipmentRequirement, line.id).testing_status == "pending"


def test_unknown_fields_are_rejected(setup):
    line, tech = setup()
    with pytest.raises(EquipmentPreparationError, match="quantity"):
        update_equipment_preparation(line, tech, {"quantity": 9})


@pytest.mark.parametrize("changes", [{}, "done", ["done"]])
def test_an_empty_or_non_object_body_is_rejected(setup, changes):
    line, tech = setup()
    with pytest.raises(EquipmentPreparationError):
        update_equipment_preparation(line, tech, changes)


def test_an_unavailable_requirement_cannot_be_updated(setup):
    line, tech = setup(status="unavailable")
    with pytest.raises(EquipmentPreparationError):
        update_equipment_preparation(line, tech, {"testing_status": "done"})


def test_only_technical_support_staff_can_update(setup, make_user):
    line, _ = setup()
    coordinator = db.session.get(User, make_user("c2@test.com", ["event_coordinator"]))
    with pytest.raises(PermissionError):
        update_equipment_preparation(line, coordinator, {"testing_status": "done"})
    assert line.testing_status == "pending"

def test_the_requirement_reports_its_latest_preparation_status(setup):
    line, tech = setup()
    update_equipment_preparation(line, tech, {"testing_status": "done"})
    assert line.to_dict()["testingStatus"] == "done"