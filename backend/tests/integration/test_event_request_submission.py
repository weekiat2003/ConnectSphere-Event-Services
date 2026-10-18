"""
Integration tests for Event Request Creation.

Goes through drafts.create_draft() + review.submit_event(), using raw dict
payloads shaped like what the Flask route actually receives from the
frontend (JSON strings, not Python date/time objects) -- this is what
catches type-coercion gaps that pure unit tests would miss.
"""
from datetime import date, timedelta

import pytest

from app.events.services import drafts, review

FUTURE_DATE = date.today() + timedelta(days=7)

VALID_PAYLOAD = {
    "name": "Annual Tech Conference",
    "purpose": "Knowledge sharing",
    "description": "A conference for the tech community.",
    "proposed_date": FUTURE_DATE.isoformat(),  # e.g. "2026-10-01", as JSON would send it
    "proposed_time": "09:00",
    "expected_attendance": 100,
    "capacity_needed": 120,
    "required_layout": "theatre",
    "accessibility_needs": "Wheelchair access required",
    "registration_required": False,
}


def test_create_draft_saves_core_details(app, organiser):
    with app.app_context():
        event = drafts.create_draft(organiser, dict(VALID_PAYLOAD))
        assert event.name == "Annual Tech Conference"
        assert event.purpose == "Knowledge sharing"
        assert event.status == "draft"


def test_full_submission_assigns_coordinator_and_updates_status(app, organiser, coordinator):
    with app.app_context():
        event = drafts.create_draft(organiser, dict(VALID_PAYLOAD))
        event = review.submit_event(event, organiser)
        assert event.status == "under_review"
        assert event.coordinator_id == coordinator
        assert event.submitted_at is not None


def test_submission_blocked_when_venue_requirements_missing(app, organiser):
    with app.app_context():
        payload = dict(VALID_PAYLOAD)
        payload.pop("capacity_needed")
        payload.pop("required_layout")
        payload.pop("accessibility_needs")
        event = drafts.create_draft(organiser, payload)
        with pytest.raises(ValueError):
            review.submit_event(event, organiser)


def test_date_and_time_are_stored_as_proper_types_not_strings(app, organiser):
    """
    This test documents a real gap: _apply_fields() does a plain setattr()
    with no parsing, so a JSON string date/time may be stored as a raw str
    rather than a Python date/time object. If this test fails, proposed_date
    and proposed_time need to be parsed in _apply_fields() before assignment,
    otherwise validate_for_submission()'s date comparison can raise a
    TypeError instead of a clean validation error.
    """
    with app.app_context():
        event = drafts.create_draft(organiser, dict(VALID_PAYLOAD))
        assert isinstance(event.proposed_date, date), (
            f"proposed_date is {type(event.proposed_date)}, expected datetime.date"
        )


def test_time_round_trips_as_hhmm_without_seconds(app, organiser):
    with app.app_context():
        event = drafts.create_draft(organiser, dict(VALID_PAYLOAD))
        payload = event.to_dict()
        assert payload["proposedTime"] == "09:00"

        event2 = drafts.create_draft(organiser, {
            **dict(VALID_PAYLOAD),
            "proposed_time": payload["proposedTime"],
        })
        assert event2.proposed_time.strftime("%H:%M") == "09:00"


def test_equipment_requirements_are_saved(app, organiser):
    with app.app_context():
        payload = dict(VALID_PAYLOAD)
        payload["equipment_requirements"] = [
            {
                "type": "Projector",
                "quantity": 2,
                "technicalNotes": "HDMI connection required",
            }
        ]

        event = drafts.create_draft(organiser, payload)

        assert len(event.equipment_requirements) == 1
        equipment = event.equipment_requirements[0]

        assert equipment.equipment_type == "Projector"
        assert equipment.quantity == 2
        assert equipment.technical_notes == "HDMI connection required"


def test_registration_requirements_are_saved(app, organiser):
    with app.app_context():
        payload = dict(VALID_PAYLOAD)
        payload["registration_required"] = True
        payload["intended_capacity"] = 80

        event = drafts.create_draft(organiser, payload)

        assert event.registration_required is True
        assert event.intended_capacity == 80


def test_required_facilities_are_saved(app, organiser):
    with app.app_context():
        payload = dict(VALID_PAYLOAD)
        payload["required_facilities"] = [
            "Projector",
            "Air Conditioning",
            "Wheelchair Access",
        ]

        event = drafts.create_draft(organiser, payload)

        assert event.required_facilities == [
            "Projector",
            "Air Conditioning",
            "Wheelchair Access",
        ]


def test_submission_blocked_when_expected_attendance_missing(app, organiser):
    with app.app_context():
        payload = dict(VALID_PAYLOAD)
        payload.pop("expected_attendance")

        event = drafts.create_draft(organiser, payload)

        with pytest.raises(ValueError, match="expected_attendance"):
            review.submit_event(event, organiser)


def test_submission_blocked_when_proposed_date_missing(app, organiser):
    with app.app_context():
        payload = dict(VALID_PAYLOAD)
        payload.pop("proposed_date")

        event = drafts.create_draft(organiser, payload)

        with pytest.raises(ValueError, match="proposed_date"):
            review.submit_event(event, organiser)


def test_submitted_event_cannot_be_updated_as_draft(app, organiser, coordinator):
    with app.app_context():
        event = drafts.create_draft(organiser, dict(VALID_PAYLOAD))

        review.submit_event(event, organiser)

        with pytest.raises(ValueError, match="Only a draft request can be edited"):
            drafts.update_draft(
                event,
                {"name": "Changed Event Name"}
            )

def test_submission_blocked_when_name_missing(app, organiser):
    with app.app_context():
        payload = dict(VALID_PAYLOAD)
        payload.pop("name")
        event = drafts.create_draft(organiser, payload)
        with pytest.raises(ValueError, match="name"):
            review.submit_event(event, organiser)


def test_submission_blocked_when_required_layout_missing(app, organiser):
    with app.app_context():
        payload = dict(VALID_PAYLOAD)
        payload.pop("required_layout")
        event = drafts.create_draft(organiser, payload)
        with pytest.raises(ValueError, match="required_layout"):
            review.submit_event(event, organiser)


def test_submission_blocked_when_accessibility_needs_missing(app, organiser):
    with app.app_context():
        payload = dict(VALID_PAYLOAD)
        payload.pop("accessibility_needs")
        event = drafts.create_draft(organiser, payload)
        with pytest.raises(ValueError, match="accessibility_needs"):
            review.submit_event(event, organiser)


def test_submission_succeeds_without_category(app, organiser, coordinator):
    """category is the one genuinely optional core-details field."""
    with app.app_context():
        payload = dict(VALID_PAYLOAD)
        payload.pop("category", None)
        event = drafts.create_draft(organiser, payload)
        event = review.submit_event(event, organiser)
        assert event.status == "under_review"


def test_submission_succeeds_with_empty_equipment_list(app, organiser, coordinator):
    with app.app_context():
        payload = dict(VALID_PAYLOAD)
        payload["equipment_requirements"] = []
        event = drafts.create_draft(organiser, payload)
        event = review.submit_event(event, organiser)
        assert event.status == "under_review"
        assert event.equipment_requirements == []


def test_draft_can_be_saved_completely_empty(app, organiser):
    """Drafts shouldn't be validated the same way submissions are --
    an Organiser should be able to save a blank draft and fill it in later."""
    with app.app_context():
        event = drafts.create_draft(organiser, {})
        assert event.status == "draft"
        assert event.id is not None


def test_draft_completed_incrementally_then_submitted(app, organiser, coordinator):
    """Full realistic lifecycle: start a draft with almost nothing, fill
    it in over a couple of edits, then submit successfully."""
    with app.app_context():
        event = drafts.create_draft(organiser, {"name": "Draft Event"})
        assert event.status == "draft"

        event = drafts.update_draft(event, {
            "purpose": "Testing incremental completion",
            "description": "Filled in over multiple edits.",
            "proposed_date": FUTURE_DATE.isoformat(),
            "proposed_time": "14:00",
            "expected_attendance": 40,
            "capacity_needed": 50,
            "required_layout": "boardroom",
            "accessibility_needs": "None",
        })

        event = review.submit_event(event, organiser)
        assert event.status == "under_review"


def test_cannot_submit_already_submitted_event(app, organiser, coordinator):
    """Negative case: submitting twice should be rejected, not silently
    reassign a new coordinator or duplicate anything."""
    from app.events.services.status import InvalidTransitionError

    with app.app_context():
        event = drafts.create_draft(organiser, dict(VALID_PAYLOAD))
        review.submit_event(event, organiser)

        with pytest.raises(InvalidTransitionError):
            review.submit_event(event, organiser)


def test_organiser_cannot_submit_someone_elses_event(app, organiser):
    """Security-relevant negative case: submit_event checks organiser_id
    ownership -- make sure a different Organiser can't submit on someone
    else's behalf."""
    from app.extensions import db
    from app.models.user import Organisation, Role, User
    from werkzeug.security import generate_password_hash

    with app.app_context():
        other_org = Organisation(name="Other Org")
        db.session.add(other_org)
        db.session.commit()
        other_user = User(
            name="Other Organiser",
            email="other_organiser@test.com",
            password_hash=generate_password_hash("password"),
            organisation_id=other_org.id,
        )
        other_user.roles = [Role.query.filter_by(name="event_organiser").first()]
        db.session.add(other_user)
        db.session.commit()

        event = drafts.create_draft(organiser, dict(VALID_PAYLOAD))

        with pytest.raises(PermissionError):
            review.submit_event(event, other_user.id)