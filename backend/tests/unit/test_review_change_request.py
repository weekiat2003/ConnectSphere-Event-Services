"""Coordinator reviews a requested change (Event Change Requests)."""
from datetime import date, datetime, time, timedelta

import pytest
from werkzeug.security import generate_password_hash

from flask import url_for
from flask_jwt_extended import create_access_token

from app.change_requests.services import (
    get_review_detail,
    list_review_queue,
    request_withdrawal,
    submit_change_request,
)
from app.common.time import utcnow
from app.extensions import db
from app.models.change_request import ChangeRequest
from app.models.event import Event, EventEquipmentRequirement
from app.models.user import Role, User
from app.models.venue import BOOKING_APPROVED, BOOKING_REJECTED, BOOKING_WITHDRAWN, VenueBooking

BASE_DAY = date.today() + timedelta(days=60)
REASON = "The client moved their launch to a later week."


# ---------------------------------------------------------------------
# Helpers (call inside `with app.app_context():`)
# ---------------------------------------------------------------------

def _user(role_name, name):
    user = User(
        name=name,
        email=f"{name.replace(' ', '.').lower()}@review-tests.com",
        password_hash=generate_password_hash("password"),
    )
    user.roles = [Role.query.filter_by(name=role_name).first()]
    db.session.add(user)
    db.session.commit()
    return user.id


def _people():
    """A real organiser and two real coordinators, as ids."""
    return (
        _user("event_organiser", "Olivia Organiser"),
        _user("event_coordinator", "Carlos Coordinator"),
        _user("event_coordinator", "Priya Coordinator"),
    )


def _event(organiser_id, coordinator_id, name="Annual Conference", status="confirmed"):
    event = Event(
        organiser_id=organiser_id,
        coordinator_id=coordinator_id,
        status=status,
        name=name,
        purpose="Networking",
        description="A conference for the team",
        proposed_date=BASE_DAY,
        proposed_time=time(9, 30),
        expected_attendance=80,
    )
    db.session.add(event)
    db.session.commit()
    return event


def _routine(event):
    return submit_change_request(event, event.organiser_id, {"name": "Annual Summit"}, REASON)


def _significant(event, attendance=120):
    return submit_change_request(event, event.organiser_id, {"expected_attendance": attendance}, REASON)


def _booking(event, status=BOOKING_APPROVED):
    booking = VenueBooking(
        event_id=event.id, venue_id=1, requested_by=500, status=status,
        start_datetime=datetime.combine(BASE_DAY, time(9, 30)),
        end_datetime=datetime.combine(BASE_DAY, time(17, 0)),
    )
    db.session.add(booking)
    db.session.commit()
    return booking

def _get(app, endpoint, user_id=None, **values):
    """GET a change_requests endpoint, logged in as `user_id` if given."""
    with app.test_request_context():
        path = url_for(f"change_requests.{endpoint}", **values)
    headers = {}
    if user_id:
        with app.app_context():
            user = db.session.get(User, user_id)
            token = create_access_token(
                identity=str(user_id),
                additional_claims={"roles": user.role_names(), "name": user.name},
            )
        headers = {"Authorization": f"Bearer {token}"}
    return app.test_client().get(path, headers=headers)


def _http_scene(app):
    """An organiser, two coordinators, and a significant then a routine request on the first coordinator's event."""
    with app.app_context():
        organiser, coordinator, other = _people()
        event = _event(organiser, coordinator)
        significant = _significant(event)
        routine = _routine(event)
        return {
            "organiser": organiser, "coordinator": coordinator, "other": other,
            "significant": significant.id, "routine": routine.id,
        }
# ---------------------------------------------------------------------
# 1. The queue
# ---------------------------------------------------------------------

def test_queue_lists_pending_requests_for_my_events_oldest_first(app):
    with app.app_context():
        organiser, coordinator, _ = _people()
        first_event = _event(organiser, coordinator, "First Event")
        second_event = _event(organiser, coordinator, "Second Event")
        first = _significant(first_event)
        second = _routine(second_event)
        third = _significant(first_event, attendance=150)

        assert [item["id"] for item in list_review_queue(coordinator)] == [first.id, second.id, third.id]


def test_queue_rows_show_event_organiser_time_and_marking(app):
    with app.app_context():
        organiser, coordinator, _ = _people()
        event = _event(organiser, coordinator)
        significant = _significant(event)
        routine = _routine(event)

        rows = {item["id"]: item for item in list_review_queue(coordinator)}

        assert rows[significant.id]["eventName"] == "Annual Conference"
        assert rows[significant.id]["organiserName"] == "Olivia Organiser"
        assert rows[significant.id]["createdAt"] is not None
        assert rows[significant.id]["isSignificant"] is True
        assert rows[routine.id]["isSignificant"] is False


@pytest.mark.parametrize("decided_status", ["processed", "rejected", "cannot_accommodate"])
def test_queue_leaves_out_decided_requests(app, decided_status):
    with app.app_context():
        organiser, coordinator, _ = _people()
        event = _event(organiser, coordinator)
        decided = _routine(event)
        decided.status = decided_status
        db.session.commit()
        pending = _significant(event)

        assert [item["id"] for item in list_review_queue(coordinator)] == [pending.id]


def test_queue_only_contains_events_assigned_to_this_coordinator(app):
    with app.app_context():
        organiser, coordinator, other = _people()
        mine = _significant(_event(organiser, coordinator, "My Event"))
        theirs = _significant(_event(organiser, other, "Their Event"))

        assert [item["id"] for item in list_review_queue(coordinator)] == [mine.id]
        assert [item["id"] for item in list_review_queue(other)] == [theirs.id]


def test_queue_follows_a_reassignment(app):
    with app.app_context():
        organiser, coordinator, other = _people()
        event = _event(organiser, coordinator)
        change = _significant(event)

        event.coordinator_id = other
        db.session.commit()

        assert list_review_queue(coordinator) == []
        assert [item["id"] for item in list_review_queue(other)] == [change.id]


# ---------------------------------------------------------------------
# 2. Details
# ---------------------------------------------------------------------

def test_details_show_each_change_with_current_and_proposed_values(app):
    with app.app_context():
        organiser, coordinator, _ = _people()
        event = _event(organiser, coordinator)
        change = submit_change_request(
            event, organiser, {"expected_attendance": 120, "name": "Annual Summit"}, REASON
        )

        detail = get_review_detail(change.id, coordinator)

        assert sorted(detail["changes"], key=lambda c: c["field"]) == [
            {"field": "expected_attendance", "current": 80, "proposed": 120},
            {"field": "name", "current": "Annual Conference", "proposed": "Annual Summit"},
        ]
        assert detail["request"]["reason"] == REASON
        assert detail["request"]["createdAt"] is not None
        assert detail["event"]["name"] == "Annual Conference"
        assert detail["event"]["organiserName"] == "Olivia Organiser"


# ---------------------------------------------------------------------
# 3. Affected arrangements
# ---------------------------------------------------------------------

def test_significant_request_lists_only_live_arrangements_with_their_status(app):
    with app.app_context():
        organiser, coordinator, _ = _people()
        event = _event(organiser, coordinator)
        _booking(event, BOOKING_APPROVED)
        _booking(event, BOOKING_REJECTED)   # not an arrangement
        _booking(event, BOOKING_WITHDRAWN)  # not an arrangement
        event.equipment_requirements.append(
            EventEquipmentRequirement(equipment_type="Projector", quantity=2, status="confirmed")
        )
        db.session.commit()
        change = _significant(event)

        arrangements = get_review_detail(change.id, coordinator)["affectedArrangements"]

        assert sorted(arrangements, key=lambda a: a["kind"]) == [
            {"kind": "equipment", "type": "Projector", "quantity": 2, "status": "confirmed"},
            {"kind": "venue_booking", "venueId": 1, "status": "approved"},
        ]



def test_routine_request_lists_no_arrangements(app):
    with app.app_context():
        organiser, coordinator, _ = _people()
        event = _event(organiser, coordinator)
        _booking(event)
        change = _routine(event)

        assert get_review_detail(change.id, coordinator)["affectedArrangements"] == []


# ---------------------------------------------------------------------
# 4. Read-only
# ---------------------------------------------------------------------

def test_reviewing_changes_nothing(app):
    with app.app_context():
        organiser, coordinator, _ = _people()
        event = _event(organiser, coordinator)
        change = _significant(event)
        request_before = change.to_dict()
        event_before = (event.name, event.proposed_date, event.expected_attendance, event.status)
        rows_before = ChangeRequest.query.count()

        get_review_detail(change.id, coordinator)
        get_review_detail(change.id, coordinator)

        db.session.refresh(change)
        db.session.refresh(event)
        assert change.to_dict() == request_before
        assert (event.name, event.proposed_date, event.expected_attendance, event.status) == event_before
        assert ChangeRequest.query.count() == rows_before


# ---------------------------------------------------------------------
# 5. Available actions and decisions
# ---------------------------------------------------------------------

def test_pending_routine_request_offers_process_and_cannot_accommodate(app):
    with app.app_context():
        organiser, coordinator, _ = _people()
        change = _routine(_event(organiser, coordinator))

        detail = get_review_detail(change.id, coordinator)

        assert detail["availableActions"] == ["process_change", "cannot_accommodate"]
        assert detail["decision"] is None


def test_pending_significant_request_offers_re_review_and_cannot_accommodate(app):
    with app.app_context():
        organiser, coordinator, _ = _people()
        change = _significant(_event(organiser, coordinator))

        detail = get_review_detail(change.id, coordinator)

        assert detail["availableActions"] == ["trigger_re_review", "cannot_accommodate"]


def test_pending_withdrawal_appears_in_the_queue_and_offers_cancel(app):
    with app.app_context():
        organiser, coordinator, _ = _people()
        withdrawal = request_withdrawal(_event(organiser, coordinator), organiser, REASON)

        row = list_review_queue(coordinator)[0]
        detail = get_review_detail(withdrawal.id, coordinator)

        assert (row["id"], row["requestType"]) == (withdrawal.id, "withdrawal")
        assert detail["availableActions"] == ["cancel_event", "cannot_accommodate"]
        assert detail["changes"] == []


@pytest.mark.parametrize("decided_status", ["processed", "rejected", "cannot_accommodate"])
def test_decided_request_is_read_only_and_shows_the_decision(app, decided_status):
    with app.app_context():
        organiser, coordinator, _ = _people()
        change = _routine(_event(organiser, coordinator))
        change.status = decided_status
        change.coordinator_id = coordinator
        change.decision_reason = "The venue is fully booked."
        change.decided_at = utcnow()
        db.session.commit()

        detail = get_review_detail(change.id, coordinator)

        assert detail["availableActions"] == []
        assert detail["decision"]["status"] == decided_status
        assert detail["decision"]["decidedBy"] == "Carlos Coordinator"
        assert detail["decision"]["reason"] == "The venue is fully booked."
        datetime.fromisoformat(detail["decision"]["decidedAt"])


# ---------------------------------------------------------------------
# 6. Access
# ---------------------------------------------------------------------

def test_another_coordinator_cannot_review_the_request(app):
    with app.app_context():
        organiser, coordinator, other = _people()
        change = _significant(_event(organiser, coordinator))

        with pytest.raises(PermissionError, match="assigned"):
            get_review_detail(change.id, other)



def test_review_rights_move_with_a_reassignment(app):
    with app.app_context():
        organiser, coordinator, other = _people()
        event = _event(organiser, coordinator)
        change = _significant(event)

        event.coordinator_id = other
        db.session.commit()

        assert get_review_detail(change.id, other)["request"]["id"] == change.id
        with pytest.raises(PermissionError, match="assigned"):
            get_review_detail(change.id, coordinator)


def test_an_unknown_request_is_not_found(app):
    with app.app_context():
        _, coordinator, _ = _people()
        with pytest.raises(LookupError):
            get_review_detail(999999, coordinator)

# ---------------------------------------------------------------------
# HTTP: review queue and review detail
# ---------------------------------------------------------------------

def test_queue_endpoint_lists_my_pending_requests_oldest_first(app):
    scene = _http_scene(app)

    response = _get(app, "review_queue", scene["coordinator"])

    assert response.status_code == 200
    rows = response.get_json()
    assert [row["id"] for row in rows] == [scene["significant"], scene["routine"]]
    assert rows[0]["eventName"] == "Annual Conference"
    assert rows[0]["organiserName"] == "Olivia Organiser"


def test_queue_endpoint_only_shows_the_logged_in_coordinators_events(app):
    scene = _http_scene(app)

    assert _get(app, "review_queue", scene["other"]).get_json() == []


def test_queue_endpoint_is_for_coordinators_only(app):
    scene = _http_scene(app)

    assert _get(app, "review_queue", scene["organiser"]).status_code == 403
    assert _get(app, "review_queue").status_code == 401


def test_detail_endpoint_returns_the_full_review_payload(app):
    scene = _http_scene(app)

    response = _get(app, "review_detail", scene["coordinator"], request_id=scene["significant"])

    assert response.status_code == 200
    body = response.get_json()
    assert set(body) == {"request", "event", "changes", "affectedArrangements", "availableActions", "decision", "reReview"}
    assert body["changes"] == [{"field": "expected_attendance", "current": 80, "proposed": 120}]
    assert body["availableActions"] == ["trigger_re_review", "cannot_accommodate"]
    assert body["decision"] is None


def test_detail_endpoint_shows_a_decided_requests_decision(app):
    scene = _http_scene(app)
    with app.app_context():
        change = db.session.get(ChangeRequest, scene["routine"])
        change.status = "rejected"
        change.coordinator_id = scene["coordinator"]
        change.decision_reason = "The venue is fully booked."
        change.decided_at = utcnow()
        db.session.commit()

    body = _get(app, "review_detail", scene["coordinator"], request_id=scene["routine"]).get_json()

    assert body["availableActions"] == []
    assert body["decision"]["decidedBy"] == "Carlos Coordinator"
    assert body["decision"]["reason"] == "The venue is fully booked."


def test_detail_endpoint_refuses_a_coordinator_who_is_not_assigned(app):
    scene = _http_scene(app)

    response = _get(app, "review_detail", scene["other"], request_id=scene["significant"])

    assert response.status_code == 403
    assert "assigned" in response.get_json()["error"]
    assert "changes" not in response.get_json()  # nothing leaks


def test_detail_endpoint_unknown_request_is_not_found(app):
    scene = _http_scene(app)

    assert _get(app, "review_detail", scene["coordinator"], request_id=999999).status_code == 404


def test_detail_endpoint_is_for_coordinators_only(app):
    scene = _http_scene(app)

    assert _get(app, "review_detail", scene["organiser"], request_id=scene["significant"]).status_code == 403
    assert _get(app, "review_detail", request_id=scene["significant"]).status_code == 401