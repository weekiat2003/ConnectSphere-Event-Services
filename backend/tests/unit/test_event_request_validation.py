"""
Unit tests for Event Request Creation validation logic.

Tests validate_for_submission() in isolation against directly-constructed
Event objects with proper Python types. No HTTP layer, no realistic
request-body parsing involved here -- see tests/integration for that.
"""
from datetime import date, timedelta


from app.events.services.validators import validate_for_submission
from app.models.event import Event, EventEquipmentRequirement

FUTURE_DATE = date.today() + timedelta(days=7)


def _valid_event(organiser_id):
    """A fully valid Event, built directly with proper Python types."""
    return Event(
        organiser_id=organiser_id,
        status="draft",
        name="Annual Tech Conference",
        purpose="Knowledge sharing",
        description="A conference for the tech community.",
        proposed_date=FUTURE_DATE,
        proposed_time="09:00",
        expected_attendance=100,
        capacity_needed=120,
        required_layout="theatre",
        accessibility_needs="Wheelchair access required",
        registration_required=False,
    )

def test_valid_event_has_no_errors(app, organiser):
    with app.app_context():
        event = _valid_event(organiser)
        assert validate_for_submission(event) == []


def test_missing_name_is_blocked(app, organiser):
    with app.app_context():
        event = _valid_event(organiser)
        event.name = ""
        errors = validate_for_submission(event)
        assert any("name" in e for e in errors)


def test_missing_proposed_time_is_blocked(app, organiser):
    """Regression test: proposed_time was missing from the original
    REQUIRED_FOR_SUBMISSION list even though the AC requires it."""
    with app.app_context():
        event = _valid_event(organiser)
        event.proposed_time = None
        errors = validate_for_submission(event)
        assert any("proposed_time" in e for e in errors)


def test_missing_venue_requirements_is_blocked(app, organiser):
    """Regression test: venue requirements weren't checked at all originally."""
    with app.app_context():
        event = _valid_event(organiser)
        event.capacity_needed = None
        event.required_layout = ""
        event.accessibility_needs = ""
        errors = validate_for_submission(event)
        assert any("capacity_needed" in e for e in errors)
        assert any("required_layout" in e for e in errors)
        assert any("accessibility_needs" in e for e in errors)


def test_category_is_optional(app, organiser):
    with app.app_context():
        event = _valid_event(organiser)
        event.category = None
        assert validate_for_submission(event) == []


def test_registration_without_intended_capacity_is_blocked(app, organiser):
    with app.app_context():
        event = _valid_event(organiser)
        event.registration_required = True
        event.intended_capacity = None
        errors = validate_for_submission(event)
        assert any("Intended capacity" in e for e in errors)


def test_registration_with_intended_capacity_succeeds(app, organiser):
    with app.app_context():
        event = _valid_event(organiser)
        event.registration_required = True
        event.intended_capacity = 50
        assert validate_for_submission(event) == []


def test_negative_expected_attendance_is_blocked(app, organiser):
    with app.app_context():
        event = _valid_event(organiser)
        event.expected_attendance = -5
        errors = validate_for_submission(event)
        assert any("Expected attendance" in e for e in errors)


def test_past_proposed_date_is_blocked(app, organiser):
    with app.app_context():
        event = _valid_event(organiser)
        event.proposed_date = date.today() - timedelta(days=1)
        errors = validate_for_submission(event)
        assert any("past" in e for e in errors)


def test_equipment_item_missing_quantity_is_blocked(app, organiser):
    with app.app_context():
        event = _valid_event(organiser)
        event.equipment_requirements = [
            EventEquipmentRequirement(equipment_type="Projector", quantity=0)
        ]
        errors = validate_for_submission(event)
        assert any("quantity" in e for e in errors)


def test_equipment_item_missing_type_is_blocked(app, organiser):
    with app.app_context():
        event = _valid_event(organiser)
        event.equipment_requirements = [
            EventEquipmentRequirement(equipment_type="", quantity=2)
        ]
        errors = validate_for_submission(event)
        assert any("type" in e for e in errors)

def test_missing_purpose_is_blocked(app, organiser):
    with app.app_context():
        event = _valid_event(organiser)
        event.purpose = ""
        errors = validate_for_submission(event)
        assert any("purpose" in e for e in errors)


def test_missing_description_is_blocked(app, organiser):
    with app.app_context():
        event = _valid_event(organiser)
        event.description = ""
        errors = validate_for_submission(event)
        assert any("description" in e for e in errors)


def test_missing_expected_attendance_is_blocked(app, organiser):
    with app.app_context():
        event = _valid_event(organiser)
        event.expected_attendance = None
        errors = validate_for_submission(event)
        assert any("expected_attendance" in e for e in errors)


def test_zero_expected_attendance_is_blocked(app, organiser):
    """Boundary case: 0 is not a negative number, but it's still invalid."""
    with app.app_context():
        event = _valid_event(organiser)
        event.expected_attendance = 0
        errors = validate_for_submission(event)
        assert any("Expected attendance" in e for e in errors)


def test_zero_capacity_needed_is_blocked(app, organiser):
    with app.app_context():
        event = _valid_event(organiser)
        event.capacity_needed = 0
        errors = validate_for_submission(event)
        assert any("Venue capacity" in e for e in errors)


def test_negative_capacity_needed_is_blocked(app, organiser):
    with app.app_context():
        event = _valid_event(organiser)
        event.capacity_needed = -10
        errors = validate_for_submission(event)
        assert any("Venue capacity" in e for e in errors)


def test_negative_intended_capacity_is_blocked(app, organiser):
    with app.app_context():
        event = _valid_event(organiser)
        event.registration_required = True
        event.intended_capacity = -5
        errors = validate_for_submission(event)
        assert any("Intended capacity" in e for e in errors)


def test_proposed_date_today_is_allowed(app, organiser):
    """Boundary case: today should NOT count as 'in the past'."""
    with app.app_context():
        event = _valid_event(organiser)
        event.proposed_date = date.today()
        errors = validate_for_submission(event)
        assert not any("past" in e for e in errors)


def test_registration_not_required_ignores_leftover_intended_capacity(app, organiser):
    """Edge case: registration_required is False but intended_capacity is
    still set (e.g. left over from toggling the checkbox off) -- shouldn't
    block submission, since the check only applies when registration is on."""
    with app.app_context():
        event = _valid_event(organiser)
        event.registration_required = False
        event.intended_capacity = 30
        assert validate_for_submission(event) == []


def test_multiple_missing_fields_are_all_reported_together(app, organiser):
    """UX case: a request missing several fields at once should surface
    every problem in one pass, not just the first one found."""
    with app.app_context():
        event = _valid_event(organiser)
        event.name = ""
        event.expected_attendance = -1
        event.capacity_needed = None
        errors = validate_for_submission(event)
        assert any("name" in e for e in errors)
        assert any("Expected attendance" in e for e in errors)
        assert any("capacity_needed" in e for e in errors)


def test_empty_equipment_list_is_valid(app, organiser):
    with app.app_context():
        event = _valid_event(organiser)
        event.equipment_requirements = []
        assert validate_for_submission(event) == []


def test_second_equipment_item_is_validated_independently(app, organiser):
    """Edge case: the first item is fine, only the second is broken --
    make sure it still gets caught rather than short-circuiting."""
    with app.app_context():
        event = _valid_event(organiser)
        event.equipment_requirements = [
            EventEquipmentRequirement(equipment_type="Microphone", quantity=2),
            EventEquipmentRequirement(equipment_type="", quantity=1),
        ]
        errors = validate_for_submission(event)
        assert any("Equipment item 2" in e for e in errors)