"""Coordinator triggers re-review for a significant change (Event Change Requests)."""
from datetime import date, datetime, time, timedelta

import pytest
from flask import url_for
from flask_jwt_extended import create_access_token
from werkzeug.security import generate_password_hash

from app.change_requests.services import (
    ChangeRequestError,
    apply_re_reviewed_change,
    get_review_detail,
    list_review_queue,
    process_routine_change,
    request_withdrawal,
    submit_change_request,
    trigger_re_review,
)
from app.common.time import utcnow
from app.extensions import db
from app.models.change_request import ArrangementFlag, ChangeRequest, EventChangeHistory
from app.models.event import Event, EventEquipmentRequirement, EventStatusHistory
from app.models.user import Role, User
from app.models.venue import (
    BOOKING_APPROVED,
    BOOKING_PENDING,
    BOOKING_REJECTED,
    BOOKING_WITHDRAWN,
    VenueBooking,
)
from app.venues.services.booking import approve_booking
from app.venues.services.catalogue import create_venue

BASE_DAY = date.today() + timedelta(days=60)
NEW_DAY = BASE_DAY + timedelta(days=7)
STAFF_ID = 900
REASON = "The client moved their launch to a later week."
RECONSIDER = "Needs reconsideration"


# ---------------------------------------------------------------------
# Helpers (call inside `with app.app_context():`)
# ---------------------------------------------------------------------

def _user(role_name, name):
    user = User(
        name=name,
        email=f"{name.replace(' ', '.').lower()}@re-review-tests.com",
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


def _event(organiser_id, coordinator_id, status="confirmed", name="Annual Conference"):
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


def _venue(name="Main Hall"):
    return create_venue(STAFF_ID, {"name": name, "capacity": 200, "location": "Block A"})


def _booking(event, venue, status=BOOKING_APPROVED, start=(9, 30), end=(17, 0)):
    booking = VenueBooking(
        event_id=event.id, venue_id=venue.id, requested_by=500, status=status,
        start_datetime=datetime.combine(BASE_DAY, time(*start)),
        end_datetime=datetime.combine(BASE_DAY, time(*end)),
    )
    db.session.add(booking)
    db.session.commit()
    return booking


def _equipment(event, name="Projector", quantity=2, status="confirmed"):
    line = EventEquipmentRequirement(equipment_type=name, quantity=quantity, status=status)
    event.equipment_requirements.append(line)
    db.session.commit()
    return line


def _arranged_event(organiser_id, coordinator_id, status="confirmed"):
    """An event with one approved venue booking and one equipment line."""
    event = _event(organiser_id, coordinator_id, status)
    venue = _venue()
    return event, venue, _booking(event, venue), _equipment(event)


def _significant(event, changes=None):
    return submit_change_request(event, event.organiser_id, changes or {"expected_attendance": 120}, REASON)


def _routine(event):
    return submit_change_request(event, event.organiser_id, {"name": "Annual Summit"}, REASON)


def _flags(request_id):
    return ArrangementFlag.query.filter_by(change_request_id=request_id).order_by(ArrangementFlag.id).all()


def _stored_re_review(event, coordinator_id, requested_changes):
    """A request already under re-review, written straight to the table, for
    values that could no longer be submitted through the normal checks."""
    row = ChangeRequest(
        event_id=event.id, organiser_id=event.organiser_id, request_type="change",
        requested_changes=requested_changes, reason=REASON, is_significant=True,
        status="re_review", re_review_by=coordinator_id, re_review_at=utcnow(),
    )
    db.session.add(row)
    db.session.commit()
    return row


# ---------------------------------------------------------------------
# 1. Eligibility
# ---------------------------------------------------------------------

def test_a_routine_request_cannot_trigger_re_review(app):
    with app.app_context():
        organiser, coordinator, _ = _people()
        event = _event(organiser, coordinator)
        change = _routine(event)

        with pytest.raises(ChangeRequestError, match="significant"):
            trigger_re_review(change.id, coordinator)

        db.session.refresh(change)
        db.session.refresh(event)
        assert (change.status, event.status) == ("pending", "confirmed")
        assert ArrangementFlag.query.count() == 0


def test_a_withdrawal_request_cannot_trigger_re_review(app):
    with app.app_context():
        organiser, coordinator, _ = _people()
        withdrawal = request_withdrawal(_event(organiser, coordinator), organiser, REASON)

        with pytest.raises(ChangeRequestError, match="withdrawal"):
            trigger_re_review(withdrawal.id, coordinator)

        db.session.refresh(withdrawal)
        assert withdrawal.status == "pending"


@pytest.mark.parametrize("status", ["re_review", "processed", "rejected"])
def test_only_a_pending_request_can_trigger_re_review(app, status):
    with app.app_context():
        organiser, coordinator, _ = _people()
        change = _significant(_event(organiser, coordinator))
        change.status = status
        db.session.commit()

        with pytest.raises(ChangeRequestError, match="already"):
            trigger_re_review(change.id, coordinator)

        assert ArrangementFlag.query.count() == 0


def test_a_request_on_an_event_that_is_no_longer_changeable_is_refused(app):
    with app.app_context():
        organiser, coordinator, _ = _people()
        event = _event(organiser, coordinator)
        change = _significant(event)
        event.status = "cancelled"
        db.session.commit()

        with pytest.raises(ChangeRequestError, match="approved, planning or confirmed"):
            trigger_re_review(change.id, coordinator)

        db.session.refresh(change)
        assert change.status == "pending"


def test_only_the_assigned_coordinator_can_trigger_re_review(app):
    with app.app_context():
        organiser, coordinator, other = _people()
        change = _significant(_event(organiser, coordinator))

        for user_id in (other, organiser):
            with pytest.raises(PermissionError, match="assigned"):
                trigger_re_review(change.id, user_id)

        db.session.refresh(change)
        assert change.status == "pending"


def test_an_unknown_request_is_not_found(app):
    with app.app_context():
        _, coordinator, _ = _people()
        with pytest.raises(LookupError):
            trigger_re_review(999999, coordinator)


def test_a_dry_run_checks_everything_but_writes_nothing(app):
    with app.app_context():
        organiser, coordinator, _ = _people()
        event = _arranged_event(organiser, coordinator)[0]
        change = _significant(event)

        checked = trigger_re_review(change.id, coordinator, dry_run=True)

        db.session.refresh(change)
        db.session.refresh(event)
        assert checked.id == change.id
        assert (change.status, change.re_review_at, event.status) == ("pending", None, "confirmed")
        assert ArrangementFlag.query.count() == 0


# ---------------------------------------------------------------------
# 2. Stays open
# ---------------------------------------------------------------------

def test_triggering_puts_the_request_under_re_review_and_leaves_it_unresolved(app):
    with app.app_context():
        organiser, coordinator, _ = _people()
        change = _significant(_event(organiser, coordinator))

        result = trigger_re_review(change.id, coordinator)

        db.session.refresh(change)
        assert result.id == change.id
        assert change.status == "re_review"
        assert (change.coordinator_id, change.decided_at, change.decision_reason) == (None, None, None)
        assert change.re_review_by == coordinator
        assert change.re_review_at is not None


def test_a_request_under_re_review_stays_in_the_review_queue(app):
    with app.app_context():
        organiser, coordinator, _ = _people()
        change = _significant(_event(organiser, coordinator))
        trigger_re_review(change.id, coordinator)

        rows = list_review_queue(coordinator)

        assert [(row["id"], row["status"]) for row in rows] == [(change.id, "re_review")]


def test_a_request_under_re_review_cannot_be_processed_as_a_routine_change(app):
    with app.app_context():
        organiser, coordinator, _ = _people()
        event = _event(organiser, coordinator)
        change = _significant(event)
        trigger_re_review(change.id, coordinator)

        with pytest.raises(ChangeRequestError):
            process_routine_change(change.id, coordinator)

        db.session.refresh(event)
        assert event.expected_attendance == 80


# ---------------------------------------------------------------------
# 3. Event unchanged
# ---------------------------------------------------------------------

def test_the_event_keeps_showing_its_current_values(app):
    with app.app_context():
        organiser, coordinator, _ = _people()
        event = _event(organiser, coordinator)
        change = submit_change_request(
            event, organiser,
            {"proposed_date": NEW_DAY, "expected_attendance": 120, "name": "Annual Summit"}, REASON,
        )

        trigger_re_review(change.id, coordinator)

        db.session.refresh(event)
        shown = event.to_dict()
        assert (shown["proposedDate"], shown["expectedAttendance"], shown["name"]) == (
            BASE_DAY.isoformat(), 80, "Annual Conference",
        )


# ---------------------------------------------------------------------
# 4. Arrangements flagged
# ---------------------------------------------------------------------

def test_every_live_arrangement_is_flagged_needs_reconsideration(app):
    with app.app_context():
        organiser, coordinator, other = _people()
        event, venue, approved, line = _arranged_event(organiser, coordinator)
        pending = _booking(event, _venue("Breakout Room"), BOOKING_PENDING, (10, 0), (12, 0))
        _booking(event, venue, BOOKING_REJECTED)   # not live
        _booking(event, venue, BOOKING_WITHDRAWN)  # not live
        unrelated = _event(organiser, other, name="Other Event")
        _booking(unrelated, venue, BOOKING_APPROVED, (18, 0), (20, 0))  # another event's
        change = _significant(event)

        trigger_re_review(change.id, coordinator)

        flags = _flags(change.id)
        assert {(f.kind, f.target_id) for f in flags} == {
            ("venue_booking", approved.id),
            ("venue_booking", pending.id),
            ("equipment", line.id),
        }
        assert all(f.reason == RECONSIDER and f.cleared_at is None and f.event_id == event.id for f in flags)


def test_nothing_is_cancelled_or_released(app):
    with app.app_context():
        organiser, coordinator, _ = _people()
        event, venue, booking, line = _arranged_event(organiser, coordinator)
        pending = _booking(event, _venue("Breakout Room"), BOOKING_PENDING, (10, 0), (12, 0))
        start, end = booking.start_datetime, booking.end_datetime
        change = _significant(event)

        trigger_re_review(change.id, coordinator)

        db.session.refresh(booking)
        db.session.refresh(pending)
        db.session.refresh(line)
        assert (booking.status, booking.start_datetime, booking.end_datetime) == (BOOKING_APPROVED, start, end)
        assert pending.status == BOOKING_PENDING
        assert (line.equipment_type, line.quantity, line.status) == ("Projector", 2, "confirmed")


def test_an_approved_booking_keeps_blocking_its_venue(app):
    with app.app_context():
        organiser, coordinator, other = _people()
        event, venue, _, _ = _arranged_event(organiser, coordinator)
        rival = _booking(_event(organiser, other, name="Rival Event"), venue, BOOKING_PENDING, (10, 0), (12, 0))
        change = _significant(event)

        trigger_re_review(change.id, coordinator)

        with pytest.raises(ValueError):
            approve_booking(rival, STAFF_ID)
        db.session.refresh(rival)
        assert rival.status == BOOKING_PENDING


def test_an_event_with_no_arrangements_still_goes_under_re_review(app):
    with app.app_context():
        organiser, coordinator, _ = _people()
        change = _significant(_event(organiser, coordinator))

        trigger_re_review(change.id, coordinator)

        db.session.refresh(change)
        assert change.status == "re_review"
        assert _flags(change.id) == []


# ---------------------------------------------------------------------
# 5. Status
# ---------------------------------------------------------------------

def test_a_confirmed_event_goes_back_to_planning(app):
    with app.app_context():
        organiser, coordinator, _ = _people()
        event = _event(organiser, coordinator, status="confirmed")
        change = _significant(event)

        trigger_re_review(change.id, coordinator)

        db.session.refresh(event)
        assert event.status == "planning"
        row = EventStatusHistory.query.filter_by(event_id=event.id).one()
        assert (row.old_status, row.new_status, row.changed_by) == ("confirmed", "planning", coordinator)


@pytest.mark.parametrize("status", ["approved", "planning"])
def test_an_approved_or_planning_event_keeps_its_status(app, status):
    with app.app_context():
        organiser, coordinator, _ = _people()
        event = _event(organiser, coordinator, status=status)
        change = _significant(event)

        trigger_re_review(change.id, coordinator)

        db.session.refresh(event)
        assert event.status == status
        assert EventStatusHistory.query.filter_by(event_id=event.id).count() == 0


# ---------------------------------------------------------------------
# 6. Record
# ---------------------------------------------------------------------

def test_a_request_that_was_never_re_reviewed_has_no_re_review_record(app):
    with app.app_context():
        organiser, coordinator, _ = _people()
        change = _significant(_event(organiser, coordinator))

        assert get_review_detail(change.id, coordinator)["reReview"] is None


def test_the_review_screen_shows_who_triggered_it_when_and_what_was_flagged(app):
    with app.app_context():
        organiser, coordinator, _ = _people()
        event, venue, _, _ = _arranged_event(organiser, coordinator)
        change = _significant(event)
        trigger_re_review(change.id, coordinator)

        record = get_review_detail(change.id, coordinator)["reReview"]

        assert record["triggeredBy"] == "Carlos Coordinator"
        datetime.fromisoformat(record["triggeredAt"])
        assert sorted(record["flaggedArrangements"], key=lambda a: a["kind"]) == [
            {"kind": "equipment", "type": "Projector", "quantity": 2, "status": "confirmed",
             "needsReconsideration": True},
            {"kind": "venue_booking", "venueId": venue.id, "status": "approved",
             "needsReconsideration": True},
        ]


def test_a_request_under_re_review_offers_only_the_go_ahead_action(app):
    with app.app_context():
        organiser, coordinator, _ = _people()
        change = _significant(_event(organiser, coordinator))
        trigger_re_review(change.id, coordinator)

        detail = get_review_detail(change.id, coordinator)

        assert detail["availableActions"] == ["apply_change"]
        assert detail["decision"] is None  # still unresolved


# ---------------------------------------------------------------------
# 7. Outcome: the change is going ahead
# ---------------------------------------------------------------------

def test_going_ahead_updates_the_event_and_marks_the_request_processed(app):
    with app.app_context():
        organiser, coordinator, _ = _people()
        event = _event(organiser, coordinator)
        change = submit_change_request(
            event, organiser,
            {"proposed_date": NEW_DAY, "proposed_time": time(14, 0), "expected_attendance": 120,
             "name": "Annual Summit"},
            REASON,
        )
        trigger_re_review(change.id, coordinator)

        processed = apply_re_reviewed_change(change.id, coordinator)

        db.session.refresh(event)
        assert (event.proposed_date, event.proposed_time, event.expected_attendance, event.name) == (
            NEW_DAY, time(14, 0), 120, "Annual Summit",
        )
        assert processed.status == "processed"
        assert processed.coordinator_id == coordinator
        assert processed.decided_at is not None


def test_going_ahead_clears_the_flags_but_keeps_the_record(app):
    with app.app_context():
        organiser, coordinator, _ = _people()
        event = _arranged_event(organiser, coordinator)[0]
        change = _significant(event)
        trigger_re_review(change.id, coordinator)

        apply_re_reviewed_change(change.id, coordinator)

        flags = _flags(change.id)
        assert len(flags) == 2
        assert all(f.cleared_at is not None for f in flags)
        record = get_review_detail(change.id, coordinator)["reReview"]
        assert len(record["flaggedArrangements"]) == 2
        assert all(a["needsReconsideration"] is False for a in record["flaggedArrangements"])


def test_going_ahead_records_old_and_new_value_for_each_field(app):
    with app.app_context():
        organiser, coordinator, _ = _people()
        event = _event(organiser, coordinator)
        change = submit_change_request(
            event, organiser, {"proposed_date": NEW_DAY, "expected_attendance": 120}, REASON
        )
        trigger_re_review(change.id, coordinator)

        apply_re_reviewed_change(change.id, coordinator)

        rows = (
            EventChangeHistory.query.filter_by(change_request_id=change.id)
            .order_by(EventChangeHistory.field)
            .all()
        )
        assert [(r.field, r.old_value, r.new_value) for r in rows] == [
            ("expected_attendance", 80, 120),
            ("proposed_date", BASE_DAY.isoformat(), NEW_DAY.isoformat()),
        ]
        assert all(r.changed_by == coordinator for r in rows)


def test_going_ahead_replaces_the_events_equipment_requirements(app):
    with app.app_context():
        organiser, coordinator, _ = _people()
        event = _event(organiser, coordinator)
        _equipment(event, "Projector", 2)
        change = submit_change_request(
            event, organiser, {"equipment_requirements": [{"type": "Microphone", "quantity": 3}]}, REASON
        )
        trigger_re_review(change.id, coordinator)

        apply_re_reviewed_change(change.id, coordinator)

        db.session.refresh(event)
        assert [(e.equipment_type, e.quantity) for e in event.equipment_requirements] == [("Microphone", 3)]


def test_a_venue_change_is_recorded_but_does_not_touch_the_bookings(app):
    with app.app_context():
        organiser, coordinator, _ = _people()
        event, venue, booking, _ = _arranged_event(organiser, coordinator)
        new_venue = _venue("Second Hall")
        change = submit_change_request(event, organiser, {"venue_id": new_venue.id}, REASON)
        trigger_re_review(change.id, coordinator)

        apply_re_reviewed_change(change.id, coordinator)

        row = EventChangeHistory.query.filter_by(change_request_id=change.id).one()
        assert (row.field, row.old_value, row.new_value) == ("venue_id", venue.id, new_venue.id)
        db.session.refresh(booking)
        assert (booking.venue_id, booking.status) == (venue.id, BOOKING_APPROVED)


def test_going_ahead_does_not_reconfirm_the_event_or_release_anything(app):
    with app.app_context():
        organiser, coordinator, _ = _people()
        event, _, booking, line = _arranged_event(organiser, coordinator, status="confirmed")
        change = _significant(event)
        trigger_re_review(change.id, coordinator)

        apply_re_reviewed_change(change.id, coordinator)

        db.session.refresh(event)
        db.session.refresh(booking)
        db.session.refresh(line)
        assert event.status == "planning"  # reconfirming is a separate step
        assert booking.status == BOOKING_APPROVED
        assert line.status == "confirmed"


@pytest.mark.parametrize("status", ["pending", "processed", "rejected"])
def test_going_ahead_is_refused_unless_the_request_is_under_re_review(app, status):
    with app.app_context():
        organiser, coordinator, _ = _people()
        event = _event(organiser, coordinator)
        change = _significant(event)
        if status != "pending":
            change.status = status
            db.session.commit()

        with pytest.raises(ChangeRequestError, match="re-review"):
            apply_re_reviewed_change(change.id, coordinator)

        db.session.refresh(event)
        assert event.expected_attendance == 80


def test_going_ahead_revalidates_the_stored_values_and_applies_nothing_if_one_fails(app):
    with app.app_context():
        organiser, coordinator, _ = _people()
        event = _arranged_event(organiser, coordinator)[0]
        change = _stored_re_review(event, coordinator, {
            "proposed_date": {"from": BASE_DAY.isoformat(), "to": (date.today() - timedelta(days=1)).isoformat()},
            "expected_attendance": {"from": 80, "to": 120},
        })

        with pytest.raises(ChangeRequestError) as raised:
            apply_re_reviewed_change(change.id, coordinator)

        assert "proposed_date" in raised.value.errors
        assert "expected_attendance" not in raised.value.errors
        db.session.refresh(event)
        db.session.refresh(change)
        assert event.expected_attendance == 80  # all or nothing
        assert change.status == "re_review"
        assert EventChangeHistory.query.count() == 0


def test_going_ahead_can_only_happen_once(app):
    with app.app_context():
        organiser, coordinator, _ = _people()
        event = _event(organiser, coordinator)
        change = _significant(event)
        trigger_re_review(change.id, coordinator)
        apply_re_reviewed_change(change.id, coordinator)
        event.expected_attendance = 150  # edited afterwards
        db.session.commit()
        history_before = EventChangeHistory.query.count()

        with pytest.raises(ChangeRequestError, match="re-review"):
            apply_re_reviewed_change(change.id, coordinator)

        db.session.refresh(event)
        assert event.expected_attendance == 150  # not applied a second time
        assert EventChangeHistory.query.count() == history_before


def test_going_ahead_is_refused_if_the_event_is_no_longer_changeable(app):
    with app.app_context():
        organiser, coordinator, _ = _people()
        event = _event(organiser, coordinator)
        change = _significant(event)
        trigger_re_review(change.id, coordinator)
        event.status = "cancelled"
        db.session.commit()

        with pytest.raises(ChangeRequestError, match="approved, planning or confirmed"):
            apply_re_reviewed_change(change.id, coordinator)

        db.session.refresh(event)
        db.session.refresh(change)
        assert (event.expected_attendance, change.status) == (80, "re_review")


def test_only_the_assigned_coordinator_can_record_the_go_ahead(app):
    with app.app_context():
        organiser, coordinator, other = _people()
        event = _event(organiser, coordinator)
        change = _significant(event)
        trigger_re_review(change.id, coordinator)

        for user_id in (other, organiser):
            with pytest.raises(PermissionError, match="assigned"):
                apply_re_reviewed_change(change.id, user_id)
        with pytest.raises(LookupError):
            apply_re_reviewed_change(999999, coordinator)

        db.session.refresh(event)
        db.session.refresh(change)
        assert (event.expected_attendance, change.status) == (80, "re_review")


def test_a_dry_run_of_the_go_ahead_writes_nothing(app):
    with app.app_context():
        organiser, coordinator, _ = _people()
        event = _arranged_event(organiser, coordinator)[0]
        change = _significant(event)
        trigger_re_review(change.id, coordinator)

        apply_re_reviewed_change(change.id, coordinator, dry_run=True)

        db.session.refresh(event)
        db.session.refresh(change)
        assert (event.expected_attendance, change.status) == (80, "re_review")
        assert all(f.cleared_at is None for f in _flags(change.id))
        assert EventChangeHistory.query.count() == 0


# ---------------------------------------------------------------------
# HTTP: POST .../re-review and POST .../apply
# ---------------------------------------------------------------------

def _scene(app):
    """An organiser, two coordinators, and a significant then a routine request
    on a confirmed event with one booking and one equipment line."""
    with app.app_context():
        organiser, coordinator, other = _people()
        event = _arranged_event(organiser, coordinator)[0]
        significant = _significant(event)
        routine = _routine(event)
        return {
            "event": event.id, "organiser": organiser, "coordinator": coordinator, "other": other,
            "significant": significant.id, "routine": routine.id,
        }


def _post(app, endpoint, user_id=None, body=None, **values):
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
    return app.test_client().post(path, json=body or {}, headers=headers)


def _trigger(app, request_id, coordinator_id):
    with app.app_context():
        trigger_re_review(request_id, coordinator_id)


def _request_status(app, request_id):
    with app.app_context():
        return db.session.get(ChangeRequest, request_id).status


def _event_value(app, event_id, attribute):
    with app.app_context():
        return getattr(db.session.get(Event, event_id), attribute)


def _flag_count(app, request_id):
    with app.app_context():
        return len(_flags(request_id))


def test_re_review_asks_for_confirmation_first_and_changes_nothing(app):
    scene = _scene(app)

    response = _post(app, "start_re_review", scene["coordinator"], request_id=scene["significant"])

    assert response.status_code == 409
    body = response.get_json()
    assert body["requiresConfirmation"] is True
    assert body["message"]
    assert _request_status(app, scene["significant"]) == "pending"
    assert _event_value(app, scene["event"], "status") == "confirmed"
    assert _flag_count(app, scene["significant"]) == 0


@pytest.mark.parametrize("confirmed", [False, None, "true", 1])
def test_only_a_literal_true_counts_as_confirmation(app, confirmed):
    scene = _scene(app)

    response = _post(
        app, "start_re_review", scene["coordinator"], body={"confirmed": confirmed}, request_id=scene["significant"]
    )

    assert response.status_code == 409
    assert _request_status(app, scene["significant"]) == "pending"


def test_confirming_puts_the_request_under_re_review(app):
    scene = _scene(app)

    response = _post(
        app, "start_re_review", scene["coordinator"], body={"confirmed": True}, request_id=scene["significant"]
    )

    assert response.status_code == 200
    assert response.get_json()["status"] == "re_review"
    assert _event_value(app, scene["event"], "status") == "planning"
    assert _flag_count(app, scene["significant"]) == 2


def test_a_routine_request_is_refused_without_asking_for_confirmation(app):
    scene = _scene(app)

    response = _post(app, "start_re_review", scene["coordinator"], request_id=scene["routine"])

    assert response.status_code == 400
    assert "significant" in response.get_data(as_text=True)


def test_a_second_re_review_attempt_is_refused(app):
    scene = _scene(app)
    body = {"confirmed": True}

    first = _post(app, "start_re_review", scene["coordinator"], body=body, request_id=scene["significant"])
    second = _post(app, "start_re_review", scene["coordinator"], body=body, request_id=scene["significant"])

    assert (first.status_code, second.status_code) == (200, 400)
    assert "already" in second.get_data(as_text=True)


@pytest.mark.parametrize("endpoint", ["start_re_review", "complete_re_review"])
def test_only_the_assigned_coordinator_can_use_either_endpoint(app, endpoint):
    scene = _scene(app)
    body = {"confirmed": True}

    assert _post(app, endpoint, scene["other"], body=body, request_id=scene["significant"]).status_code == 403
    assert _post(app, endpoint, scene["organiser"], body=body, request_id=scene["significant"]).status_code == 403
    assert _post(app, endpoint, None, body=body, request_id=scene["significant"]).status_code == 401
    assert _post(app, endpoint, scene["coordinator"], body=body, request_id=999999).status_code == 404
    assert _request_status(app, scene["significant"]) == "pending"


def test_the_go_ahead_asks_for_confirmation_first_and_changes_nothing(app):
    scene = _scene(app)
    _trigger(app, scene["significant"], scene["coordinator"])

    response = _post(app, "complete_re_review", scene["coordinator"], request_id=scene["significant"])

    assert response.status_code == 409
    assert response.get_json()["requiresConfirmation"] is True
    assert _request_status(app, scene["significant"]) == "re_review"
    assert _event_value(app, scene["event"], "expected_attendance") == 80


def test_confirming_the_go_ahead_updates_the_event_and_clears_the_flags(app):
    scene = _scene(app)
    _trigger(app, scene["significant"], scene["coordinator"])

    response = _post(
        app, "complete_re_review", scene["coordinator"], body={"confirmed": True}, request_id=scene["significant"]
    )

    assert response.status_code == 200
    assert response.get_json()["status"] == "processed"
    assert _event_value(app, scene["event"], "expected_attendance") == 120
    with app.app_context():
        assert all(f.cleared_at is not None for f in _flags(scene["significant"]))


def test_the_go_ahead_is_refused_for_a_request_not_under_re_review(app):
    scene = _scene(app)

    response = _post(app, "complete_re_review", scene["coordinator"], request_id=scene["significant"])

    assert response.status_code == 400  # refused before asking anyone to confirm
    assert "re-review" in response.get_data(as_text=True)