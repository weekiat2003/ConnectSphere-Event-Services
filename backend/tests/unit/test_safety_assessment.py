"""Safety Officer review list, assessment view and per-factor assessment."""
from datetime import date, datetime, time

import pytest

from app.events.services import safety
from app.extensions import db
from app.models.event import Event, EventEquipmentRequirement, EventSafetyAssessment, EventSafetyReview
from app.models.user import User
from app.models.venue import Venue, VenueBooking
from app.venues.services import catalogue


def _venue(name, capacity=100, layouts=(), restrictions=None):
    venue = Venue(name=name, capacity=capacity, known_restrictions=restrictions)
    for layout in layouts:
        venue.supported_layouts.append(layout)
    db.session.add(venue)
    db.session.commit()
    return venue


def _book(event_id, venue, requested_by, status="approved", hour=9):
    booking = VenueBooking(
        event_id=event_id,
        venue_id=venue.id,
        requested_by=requested_by,
        status=status,
        start_datetime=datetime(2026, 12, 1, hour, 0),
        end_datetime=datetime(2026, 12, 1, hour + 2, 0),
    )
    db.session.add(booking)
    db.session.commit()
    return booking


def _all_satisfactory(**overrides):
    factors = {key: {"outcome": "satisfactory", "notes": None} for key in safety.SAFETY_FACTOR_ORDER}
    factors.update(overrides)
    return factors


# AC1 -----------------------------------------------------------------

def test_review_list_contains_only_events_awaiting_safety_check(app, organiser, make_event):
    with app.app_context():
        waiting_id = make_event(organiser, status="safety_check", name="Waiting")
        for other in ("planning", "confirmed", "approved", "submitted", "cancelled", "draft"):
            make_event(organiser, status=other, name=f"Not {other}")

        entries = safety.list_awaiting_safety_check()

        assert [entry["id"] for entry in entries] == [waiting_id]


def test_review_list_entry_shows_name_date_booked_venues_and_attendance(
    app, organiser, make_event
):
    with app.app_context():
        event_id = make_event(
            organiser,
            status="safety_check",
            name="Tech Fair",
            proposed_date=date(2026, 12, 5),
            proposed_time=time(10, 30),
            expected_attendance=180,
        )
        hall = _venue("Hall A")
        annex = _venue("Annex")
        unused = _venue("Pending Room")
        _book(event_id, hall, organiser, hour=9)
        _book(event_id, annex, organiser, hour=13)
        _book(event_id, unused, organiser, status="pending")

        [entry] = safety.list_awaiting_safety_check()

        assert entry["name"] == "Tech Fair"
        assert entry["proposedDate"] == "2026-12-05"
        assert entry["proposedTime"] == "10:30"
        assert entry["expectedAttendance"] == 180
        assert [v["name"] for v in entry["venues"]] == ["Hall A", "Annex"]


def test_review_list_is_ordered_by_date(app, organiser, make_event):
    with app.app_context():
        later = make_event(organiser, status="safety_check", proposed_date=date(2026, 12, 20))
        sooner = make_event(organiser, status="safety_check", proposed_date=date(2026, 12, 2))

        assert [e["id"] for e in safety.list_awaiting_safety_check()] == [sooner, later]


# AC2 -----------------------------------------------------------------

def test_assessment_view_includes_every_fact_the_officer_reviews(app, organiser, make_event):
    with app.app_context():
        event_id = make_event(
            organiser,
            status="safety_check",
            expected_attendance=120,
            required_layout="Classroom",
            accessibility_needs="Hearing loop",
        )
        event = db.session.get(Event, event_id)
        event.equipment_requirements.append(
            EventEquipmentRequirement(equipment_type="Projector", quantity=2, technical_notes="Ceiling mount")
        )
        db.session.commit()
        venue = _venue("Studio", capacity=150, layouts=["classroom", "theatre"], restrictions="No open flames")
        _book(event_id, venue, organiser)

        review = safety.build_safety_review(event)

        assert review["expectedAttendance"] == 120
        assert review["requiredLayout"] == "Classroom"
        assert review["accessibilityRequirements"] == "Hearing loop"
        assert review["equipmentRequirements"] == [
            {"id": event.equipment_requirements[0].id, "type": "Projector", "quantity": 2,
             "technicalNotes": "Ceiling mount"}
        ]
        [booked] = review["venues"]
        assert booked["name"] == "Studio"
        assert booked["capacity"] == 150
        assert sorted(layout["name"] for layout in booked["supportedLayouts"]) == ["classroom", "theatre"]
        assert booked["knownRestrictions"] == "No open flames"
        assert [f["key"] for f in review["factors"]] == list(safety.SAFETY_FACTOR_ORDER)
        assert review["canAssess"] is True


def test_assessment_view_returns_missing_values_as_empty_for_not_specified(
    app, organiser, make_event
):
    with app.app_context():
        event_id = make_event(organiser, status="safety_check", expected_attendance=None)
        venue = _venue("Bare Room", layouts=[], restrictions=None)
        _book(event_id, venue, organiser)

        review = safety.build_safety_review(db.session.get(Event, event_id))

        assert review["expectedAttendance"] is None
        assert review["requiredLayout"] is None
        assert review["accessibilityRequirements"] is None
        assert review["equipmentRequirements"] == []
        assert review["venues"][0]["supportedLayouts"] == []
        assert review["venues"][0]["knownRestrictions"] is None


# AC3 -----------------------------------------------------------------

def test_officer_can_record_each_factor_as_satisfactory_or_concern_with_notes(
    app, organiser, make_user, make_event
):
    with app.app_context():
        officer_id = make_user("assess@test.com", ["safety_officer"], name="Officer Lee")
        event_id = make_event(organiser, status="safety_check")
        event = db.session.get(Event, event_id)

        safety.save_assessment(
            event,
            db.session.get(User, officer_id),
            {
                "expected_attendance": {"outcome": "satisfactory", "notes": "  Within limits  "},
                "emergency_access": {"outcome": "concern", "notes": "East exit blocked"},
                "crowd_movement": {"outcome": None, "notes": "Check at site visit"},
                "accessibility": {"outcome": None, "notes": "   "},
            },
        )

        saved = EventSafetyAssessment.query.filter_by(event_id=event_id).one()
        assert saved.factors == {
            "expected_attendance": {"outcome": "satisfactory", "notes": "Within limits"},
            "emergency_access": {"outcome": "concern", "notes": "East exit blocked"},
            "crowd_movement": {"outcome": None, "notes": "Check at site visit"},
        }
        assert saved.to_dict()["safetyOfficerName"] == "Officer Lee"
        assert safety.build_safety_review(event)["assessment"]["factors"] == saved.factors
        assert event.status == "safety_check"


def test_saving_again_replaces_the_previous_assessment(app, organiser, make_user, make_event):
    with app.app_context():
        officer = db.session.get(User, make_user("resave@test.com", ["safety_officer"]))
        event = db.session.get(Event, make_event(organiser, status="safety_check"))

        safety.save_assessment(event, officer, {"emergency_access": {"outcome": "concern"}})
        safety.save_assessment(event, officer, {"emergency_access": {"outcome": "satisfactory"}})

        assert EventSafetyAssessment.query.filter_by(event_id=event.id).count() == 1
        assert event.safety_assessment.factors == {
            "emergency_access": {"outcome": "satisfactory", "notes": None}
        }


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (["emergency_access"], "object keyed by safety factor"),
        ({"fire_drill": {"outcome": "satisfactory"}}, "Unknown safety factor"),
        ({"emergency_access": {"outcome": "fine"}}, "satisfactory or a concern"),
        ({"emergency_access": {"outcome": "concern", "notes": 5}}, "must be text"),
        ({"emergency_access": {"outcome": "concern", "notes": "x" * 2001}}, "cannot exceed"),
    ],
)
def test_invalid_assessment_is_rejected(app, organiser, make_user, make_event, payload, message):
    with app.app_context():
        officer = db.session.get(User, make_user("bad-assess@test.com", ["safety_officer"]))
        event = db.session.get(Event, make_event(organiser, status="safety_check"))

        with pytest.raises(ValueError, match=message):
            safety.save_assessment(event, officer, payload)
        assert EventSafetyAssessment.query.count() == 0


def test_assessment_only_while_awaiting_safety_check(app, organiser, make_user, make_event):
    with app.app_context():
        officer = db.session.get(User, make_user("late@test.com", ["safety_officer"]))
        event = db.session.get(Event, make_event(organiser, status="planning"))

        with pytest.raises(safety.SafetyReviewConflictError):
            safety.save_assessment(event, officer, {"emergency_access": {"outcome": "concern"}})


def test_decision_records_factor_outcomes_and_notes_then_clears_draft(
    app, organiser, make_user, make_event
):
    with app.app_context():
        officer = db.session.get(User, make_user("decide@test.com", ["safety_officer"]))
        event = db.session.get(Event, make_event(organiser, status="safety_check"))
        factors = _all_satisfactory(
            emergency_access={"outcome": "concern", "notes": "East exit blocked by stage"},
            crowd_movement={"outcome": "satisfactory", "notes": "Two-way flow is fine"},
        )
        safety.save_assessment(event, officer, factors)

        safety.review_safety_check(
            event,
            officer,
            "changes_requested",
            "Move the stage away from the east exit",
            affected_arrangements=["venue"],
            factor_assessments=factors,
        )

        review = EventSafetyReview.query.filter_by(event_id=event.id).one()
        assert review.assessed_factors == list(safety.SAFETY_FACTOR_ORDER)
        assert review.concern_factors == ["emergency_access"]
        assert review.factor_notes == {
            "emergency_access": "East exit blocked by stage",
            "crowd_movement": "Two-way flow is fine",
        }
        assert event.status == "planning"
        assert EventSafetyAssessment.query.filter_by(event_id=event.id).count() == 0


def test_approval_with_factor_assessments_requires_every_factor(
    app, organiser, make_user, make_event
):
    with app.app_context():
        officer = db.session.get(User, make_user("partial@test.com", ["safety_officer"]))
        event = db.session.get(Event, make_event(organiser, status="safety_check"))
        factors = _all_satisfactory()
        del factors["crowd_movement"]

        with pytest.raises(ValueError, match="All safety factors"):
            safety.review_safety_check(event, officer, "approved", factor_assessments=factors)

        safety.review_safety_check(event, officer, "approved", factor_assessments=_all_satisfactory())
        assert event.status == "confirmed"


# AC4 -----------------------------------------------------------------

def test_non_safety_officer_cannot_save_an_assessment(app, organiser, coordinator, make_event):
    with app.app_context():
        event = db.session.get(Event, make_event(organiser, status="safety_check"))

        with pytest.raises(PermissionError):
            safety.save_assessment(
                event, db.session.get(User, coordinator), {"emergency_access": {"outcome": "concern"}}
            )


# Venue known restrictions (needed for AC2) ----------------------------

def test_venue_staff_can_record_and_clear_known_restrictions(app, make_user):
    with app.app_context():
        staff_id = make_user("venue-staff@test.com", ["venue_staff"])
        venue = catalogue.create_venue(
            staff_id, {"name": "Hall", "capacity": 50, "knownRestrictions": "  No candles  "}
        )
        assert venue.known_restrictions == "No candles"
        assert venue.to_dict()["knownRestrictions"] == "No candles"

        catalogue.update_venue(venue, {"knownRestrictions": "   "})
        assert venue.known_restrictions is None

        with pytest.raises(ValueError, match="must be text"):
            catalogue.update_venue(venue, {"knownRestrictions": ["No candles"]})
