"""Organiser requests a change to an event (Event Change Requests)."""
from datetime import date, datetime, time, timedelta

import pytest

from flask import url_for
from flask_jwt_extended import create_access_token
from werkzeug.security import generate_password_hash

from app.models.user import Role, User

from app.change_requests.services import (
    ChangeRequestError,
    can_request_change,
    list_change_requests_for_coordinator,
    list_change_requests_for_event,
    submit_change_request,
)
from app.events.services.drafts import update_draft
from app.extensions import db
from app.models.change_request import ChangeRequest
from app.models.event import Event
from app.models.venue import BOOKING_APPROVED, VenueBooking
from app.venues.services.catalogue import create_venue, deactivate_venue

ORGANISER_ID = 100
OTHER_ORGANISER_ID = 101
COORDINATOR_ID = 200
OTHER_COORDINATOR_ID = 201
STAFF_ID = 900
BASE_DAY = date.today() + timedelta(days=60)
NEW_DAY = BASE_DAY + timedelta(days=7)
REASON = "The client moved their launch to a later week."
ALLOWED_STATUSES = ("approved", "planning", "confirmed")
OTHER_STATUSES = ("draft", "submitted", "under_review", "rejected", "completed", "cancelled")


# ---------------------------------------------------------------------
# Helpers (call inside `with app.app_context():`)
# ---------------------------------------------------------------------

def _event(status="confirmed", **overrides):
    values = dict(
        organiser_id=ORGANISER_ID,
        coordinator_id=COORDINATOR_ID,
        status=status,
        name="Annual Conference",
        purpose="Networking",
        description="A conference for the team",
        proposed_date=BASE_DAY,
        proposed_time=time(9, 30),
        expected_attendance=80,
        accessibility_needs="Step-free access",
    )
    values.update(overrides)
    event = Event(**values)
    db.session.add(event)
    db.session.commit()
    return event


def _submit(event, changes, reason=REASON, organiser_id=ORGANISER_ID):
    return submit_change_request(event, organiser_id, changes, reason)


def _venue(name="Main Hall"):
    return create_venue(STAFF_ID, {"name": name, "capacity": 200, "location": "Block A"})


def _expect_error(event, changes, field, reason=REASON):
    """The request is refused, the problem is tied to `field`, and nothing is saved."""
    with pytest.raises(ChangeRequestError) as raised:
        _submit(event, changes, reason=reason)
    assert field in raised.value.errors
    assert ChangeRequest.query.count() == 0
    return raised.value

def _headers(app, role_name):
    """A real user with this role, and a token for them."""
    with app.app_context():
        user = User(
            name=role_name,
            email=f"{role_name}@catalogue-tests.com",
            password_hash=generate_password_hash("password"),
        )
        user.roles = [Role.query.filter_by(name=role_name).first()]
        db.session.add(user)
        db.session.commit()
        token = create_access_token(
            identity=str(user.id),
            additional_claims={"roles": user.role_names(), "name": user.name},
        )
    return {"Authorization": f"Bearer {token}"}


def _get_catalogue(app, role_name=None):
    with app.test_request_context():
        path = url_for("change_requests.catalogue")
    headers = _headers(app, role_name) if role_name else {}
    return app.test_client().get(path, headers=headers)


def _equipment(name, status="active", category="AV"):
    """Inserts into equipment_items. Creates the table first if no model has."""
    db.session.execute(db.text(
        "CREATE TABLE IF NOT EXISTS equipment_items ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, category TEXT, "
        "total_quantity INTEGER NOT NULL DEFAULT 1, status TEXT NOT NULL DEFAULT 'active')"
    ))
    db.session.execute(
        db.text("INSERT INTO equipment_items (name, category, total_quantity, status) VALUES (:n, :c, 5, :s)"),
        {"n": name, "c": category, "s": status},
    )
    db.session.commit()

# ---------------------------------------------------------------------
# 1. Who and when
# ---------------------------------------------------------------------

@pytest.mark.parametrize("status", ALLOWED_STATUSES)
def test_option_is_offered_for_approved_planning_and_confirmed(app, status):
    with app.app_context():
        assert can_request_change(_event(status), ORGANISER_ID) is True


@pytest.mark.parametrize("status", OTHER_STATUSES)
def test_option_is_not_offered_for_any_other_status(app, status):
    with app.app_context():
        assert can_request_change(_event(status), ORGANISER_ID) is False


def test_option_is_not_offered_to_another_organiser(app):
    with app.app_context():
        assert can_request_change(_event(), OTHER_ORGANISER_ID) is False


@pytest.mark.parametrize("status", OTHER_STATUSES)
def test_request_is_refused_for_any_other_status(app, status):
    with app.app_context():
        event = _event(status)
        with pytest.raises(ChangeRequestError, match="approved, planning or confirmed"):
            _submit(event, {"expected_attendance": 120})
        assert ChangeRequest.query.count() == 0


def test_request_is_refused_for_another_organiser(app):
    with app.app_context():
        event = _event()
        with pytest.raises(PermissionError, match="organiser"):
            _submit(event, {"expected_attendance": 120}, organiser_id=OTHER_ORGANISER_ID)
        assert ChangeRequest.query.count() == 0


# ---------------------------------------------------------------------
# 2. What can be changed
# ---------------------------------------------------------------------

CHANGEABLE = [
    pytest.param("proposed_date", NEW_DAY, BASE_DAY.isoformat(), NEW_DAY.isoformat(), id="date"),
    pytest.param("proposed_time", time(14, 0), "09:30:00", "14:00:00", id="time"),
    pytest.param("expected_attendance", 120, 80, 120, id="attendance"),
    pytest.param("name", "Annual Summit", "Annual Conference", "Annual Summit", id="name"),
    pytest.param("description", "A bigger event", "A conference for the team", "A bigger event", id="description"),
    pytest.param("accessibility_needs", "Hearing loop", "Step-free access", "Hearing loop", id="accessibility"),
]


@pytest.mark.parametrize("field, new_value, shown_from, shown_to", CHANGEABLE)
def test_each_permitted_field_can_be_changed_and_keeps_current_and_proposed(
    app, field, new_value, shown_from, shown_to
):
    with app.app_context():
        saved = _submit(_event(), {field: new_value})
        assert saved.requested_changes == {field: {"from": shown_from, "to": shown_to}}


def test_a_new_venue_from_the_catalogue_can_be_requested(app):
    with app.app_context():
        venue = _venue()
        saved = _submit(_event(), {"venue_id": venue.id})
        assert saved.requested_changes == {"venue_id": {"from": None, "to": venue.id}}


def test_new_equipment_can_be_requested(app):
    with app.app_context():
        equipment = [{"type": "Projector", "quantity": 2}]
        saved = _submit(_event(), {"equipment_requirements": equipment})
        assert saved.requested_changes == {"equipment_requirements": {"from": [], "to": equipment}}


def test_several_fields_can_be_changed_in_one_request(app):
    with app.app_context():
        saved = _submit(_event(), {"proposed_date": NEW_DAY, "expected_attendance": 120})
        assert set(saved.requested_changes) == {"proposed_date", "expected_attendance"}


@pytest.mark.parametrize("field, value", [("status", "cancelled"), ("organiser_id", 5), ("coordinator_id", 5)])
def test_fields_that_are_not_permitted_are_refused(app, field, value):
    with app.app_context():
        _expect_error(_event(), {field: value}, field)


def test_venue_must_exist_in_the_catalogue(app):
    with app.app_context():
        _expect_error(_event(), {"venue_id": 999999}, "venue_id")


def test_venue_must_still_be_active_in_the_catalogue(app):
    with app.app_context():
        venue = _venue()
        deactivate_venue(venue)
        _expect_error(_event(), {"venue_id": venue.id}, "venue_id")


# ---------------------------------------------------------------------
# 3. Validation
# ---------------------------------------------------------------------

@pytest.mark.parametrize(
    "changes",
    [{}, {"expected_attendance": 80}, {"proposed_date": BASE_DAY}, {"proposed_time": time(9, 30)}],
    ids=["empty", "same-attendance", "same-date", "same-time"],
)
def test_at_least_one_value_must_actually_change(app, changes):
    with app.app_context():
        _expect_error(_event(), changes, "changes")


def test_date_in_the_past_is_refused(app):
    with app.app_context():
        _expect_error(_event(), {"proposed_date": date.today() - timedelta(days=1)}, "proposed_date")


@pytest.mark.parametrize("attendance", [0, -5])
def test_attendance_must_be_positive(app, attendance):
    with app.app_context():
        _expect_error(_event(), {"expected_attendance": attendance}, "expected_attendance")


@pytest.mark.parametrize("reason", ["", "   ", "!!!", "12345"])
def test_reason_must_contain_real_words(app, reason):
    with app.app_context():
        _expect_error(_event(), {"expected_attendance": 120}, "reason", reason=reason)


def test_every_problem_is_reported_together(app):
    with app.app_context():
        error = _expect_error(
            _event(),
            {"proposed_date": date.today() - timedelta(days=1), "expected_attendance": 0},
            "proposed_date",
            reason="!!!",
        )
        assert {"proposed_date", "expected_attendance", "reason"} <= set(error.errors)


# ---------------------------------------------------------------------
# 4. Submission
# ---------------------------------------------------------------------

def test_valid_request_is_saved_as_pending_and_linked_to_the_event(app):
    with app.app_context():
        event = _event()
        saved = _submit(event, {"expected_attendance": 120})

        stored = db.session.get(ChangeRequest, saved.id)
        assert stored.status == "pending"
        assert stored.event_id == event.id
        assert stored.organiser_id == ORGANISER_ID
        assert stored.reason == REASON


def test_pending_request_is_available_to_the_assigned_coordinator_only(app):
    with app.app_context():
        saved = _submit(_event(), {"expected_attendance": 120})

        assert [r.id for r in list_change_requests_for_coordinator(COORDINATOR_ID)] == [saved.id]
        assert list_change_requests_for_coordinator(OTHER_COORDINATOR_ID) == []


def test_event_and_bookings_are_untouched_until_the_coordinator_decides(app):
    with app.app_context():
        event = _event()
        venue = _venue()
        start, end = datetime.combine(BASE_DAY, time(9, 30)), datetime.combine(BASE_DAY, time(17, 0))
        booking = VenueBooking(
            event_id=event.id, venue_id=venue.id, requested_by=500,
            status=BOOKING_APPROVED, start_datetime=start, end_datetime=end,
        )
        db.session.add(booking)
        db.session.commit()

        _submit(event, {"proposed_date": NEW_DAY, "expected_attendance": 120})

        db.session.refresh(event)
        db.session.refresh(booking)
        assert (event.proposed_date, event.expected_attendance, event.status) == (BASE_DAY, 80, "confirmed")
        assert (booking.status, booking.start_datetime, booking.end_datetime) == (BOOKING_APPROVED, start, end)


def test_organiser_cannot_edit_the_event_directly_while_a_request_is_pending(app):
    with app.app_context():
        event = _event()
        _submit(event, {"expected_attendance": 120})

        with pytest.raises(ValueError, match="draft"):
            update_draft(event, {"name": "Edited directly"})
        assert event.name == "Annual Conference"


# ---------------------------------------------------------------------
# 5. Significant or routine
# ---------------------------------------------------------------------

@pytest.mark.parametrize(
    "field, new_value",
    [
        ("proposed_date", NEW_DAY),
        ("proposed_time", time(14, 0)),
        ("expected_attendance", 120),
        ("equipment_requirements", [{"type": "Projector", "quantity": 2}]),
    ],
)
def test_changes_to_date_time_attendance_or_equipment_are_significant(app, field, new_value):
    with app.app_context():
        assert _submit(_event(), {field: new_value}).is_significant is True


def test_a_venue_change_is_significant(app):
    with app.app_context():
        assert _submit(_event(), {"venue_id": _venue().id}).is_significant is True


@pytest.mark.parametrize(
    "field, new_value",
    [("name", "Annual Summit"), ("description", "A bigger event"), ("accessibility_needs", "Hearing loop")],
)
def test_changes_to_other_details_are_routine(app, field, new_value):
    with app.app_context():
        assert _submit(_event(), {field: new_value}).is_significant is False


def test_one_significant_field_makes_the_whole_request_significant(app):
    with app.app_context():
        saved = _submit(_event(), {"name": "Annual Summit", "expected_attendance": 120})
        assert saved.is_significant is True


def test_the_marking_is_visible_in_the_request_details(app):
    with app.app_context():
        significant = _submit(_event(), {"expected_attendance": 120})
        routine = _submit(_event(), {"name": "Annual Summit"})
        assert significant.to_dict()["isSignificant"] is True
        assert routine.to_dict()["isSignificant"] is False


# ---------------------------------------------------------------------
# 6. Tracking
# ---------------------------------------------------------------------

def test_organiser_sees_their_requests_newest_first(app):
    with app.app_context():
        event = _event()
        first = _submit(event, {"expected_attendance": 120})
        second = _submit(event, {"expected_attendance": 150})

        listed = list_change_requests_for_event(event, ORGANISER_ID)

        assert [r.id for r in listed] == [second.id, first.id]


def test_each_request_shows_changes_reason_time_and_status(app):
    with app.app_context():
        event = _event()
        _submit(event, {"expected_attendance": 120})

        details = list_change_requests_for_event(event, ORGANISER_ID)[0].to_dict()

        assert {"requestedChanges", "reason", "createdAt", "status", "decisionReason"} <= set(details)
        assert details["status"] == "pending"
        assert details["reason"] == REASON
        assert details["decisionReason"] is None


def test_the_coordinators_decision_reason_is_shown(app):
    with app.app_context():
        event = _event()
        saved = _submit(event, {"expected_attendance": 120})
        saved.status = "rejected"
        saved.decision_reason = "The venue is fully booked."
        db.session.commit()

        details = list_change_requests_for_event(event, ORGANISER_ID)[0].to_dict()

        assert details["status"] == "rejected"
        assert details["decisionReason"] == "The venue is fully booked."


def test_another_organiser_cannot_list_the_requests(app):
    with app.app_context():
        event = _event()
        _submit(event, {"expected_attendance": 120})
        with pytest.raises(PermissionError):
            list_change_requests_for_event(event, OTHER_ORGANISER_ID)

# ---------------------------------------------------------------------
# Catalogue endpoint for organisers: GET /api/change-requests/catalogue
# ---------------------------------------------------------------------

@pytest.mark.parametrize("role", ["event_organiser", "event_coordinator"])
def test_organisers_and_coordinators_can_read_the_catalogue(app, role):
    with app.app_context():
        _equipment("Projector")  # makes sure the equipment table exists
    response = _get_catalogue(app, role)
    assert response.status_code == 200
    assert set(response.get_json()) == {"venues", "equipment"}


@pytest.mark.parametrize("role", ["venue_staff", "attendee", "technical_support_staff"])
def test_other_roles_are_refused(app, role):
    assert _get_catalogue(app, role).status_code == 403


def test_anonymous_users_are_refused(app):
    assert _get_catalogue(app).status_code == 401


def test_venues_are_active_only_in_name_order_and_trimmed(app):
    with app.app_context():
        _equipment("Projector")
        _venue("Zebra Room")
        _venue("Atrium")
        deactivate_venue(_venue("Closed Hall"))

    venues = _get_catalogue(app, "event_organiser").get_json()["venues"]

    assert [v["name"] for v in venues] == ["Atrium", "Zebra Room"]
    assert set(venues[0]) == {
        "id", "name", "location", "capacity", "facilities", "supportedLayouts", "accessibilityFeatures",
    }  # no setup/turnaround minutes, operating hours or description


def test_only_active_equipment_is_offered_in_name_order_without_quantities(app):
    with app.app_context():
        _equipment("Projector")
        _equipment("Microphone")
        _equipment("Old Mixer", status="maintenance")
        _equipment("Broken Screen", status="retired")

    equipment = _get_catalogue(app, "event_organiser").get_json()["equipment"]

    assert [e["name"] for e in equipment] == ["Microphone", "Projector"]
    assert set(equipment[0]) == {"id", "name", "category"}