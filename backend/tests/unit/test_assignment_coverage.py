from datetime import date

import pytest

from app.events.services import assignment
from app.extensions import db
from app.models.event import (
    CoordinatorReassignmentRequest,
    Event,
    EventCoordinatorHistory,
)
from app.models.user import User


def make_coordinator(make_user, email):
    user_id = make_user(email, ["event_coordinator"])
    return db.session.get(User, user_id)


def make_event_for_assignment(make_event, organiser, status, coordinator_id=None):
    event_id = make_event(
        organiser,
        status=status,
        coordinator_id=coordinator_id,
        proposed_date=date(2026, 12, 1),
    )
    return db.session.get(Event, event_id)


def test_get_next_coordinator_ignores_workload_assigned_to_non_coordinators(
    app, organiser, make_user, make_event
):
    with app.app_context():
        coordinator_a = make_coordinator(make_user, "workload-a@test.com")
        coordinator_b = make_coordinator(make_user, "workload-b@test.com")
        make_event_for_assignment(make_event, organiser, "planning", coordinator_a.id)
        make_event_for_assignment(make_event, organiser, "approved", organiser)

        assert assignment.get_next_coordinator().id == coordinator_b.id


def test_get_next_coordinator_returns_none_when_no_active_coordinator_exists(
    app, organiser, make_event
):
    with app.app_context():
        make_event_for_assignment(make_event, organiser, "submitted")

        assert assignment.get_next_coordinator() is None


def test_assign_coordinator_without_available_coordinator_changes_nothing(
    app, organiser, make_event
):
    with app.app_context():
        event = make_event_for_assignment(make_event, organiser, "submitted")

        with pytest.raises(ValueError, match="No active Event Coordinator"):
            assignment.assign_coordinator(event)

        db.session.expire_all()
        saved = db.session.get(Event, event.id)
        assert saved.coordinator_id is None
        assert EventCoordinatorHistory.query.filter_by(event_id=event.id).count() == 0


def test_lead_assign_rejects_an_event_outside_submitted_status(
    app, organiser, make_user, make_event
):
    with app.app_context():
        coordinator = make_coordinator(make_user, "lead-assign@test.com")
        event = make_event_for_assignment(
            make_event, organiser, "planning"
        )

        with pytest.raises(ValueError, match="Only a submitted, unassigned request"):
            assignment.lead_assign(event, coordinator)

        assert event.coordinator_id is None
        assert EventCoordinatorHistory.query.filter_by(event_id=event.id).count() == 0


def test_lead_reassign_rejects_an_unassigned_event(app, organiser, make_event):
    with app.app_context():
        event = make_event_for_assignment(make_event, organiser, "planning")

        with pytest.raises(ValueError, match="not assigned yet"):
            assignment.lead_reassign(event, None)

        assert event.coordinator_id is None


def test_try_assign_and_advance_assigns_and_advances_submitted_event(
    app, organiser, make_user, make_event
):
    with app.app_context():
        coordinator = make_coordinator(make_user, "retry-assignment@test.com")
        event = make_event_for_assignment(make_event, organiser, "submitted")

        result = assignment.try_assign_and_advance(event, commit=True)

        assert result.coordinator_id == coordinator.id
        assert result.status == "under_review"
        [history] = EventCoordinatorHistory.query.filter_by(event_id=event.id).all()
        assert history.coordinator_id == coordinator.id
        assert history.assignment_type == "auto"


def test_try_assign_and_advance_rejects_an_already_assigned_event(
    app, organiser, make_user, make_event
):
    with app.app_context():
        coordinator = make_coordinator(make_user, "already-assigned@test.com")
        event = make_event_for_assignment(
            make_event, organiser, "submitted", coordinator.id
        )

        with pytest.raises(ValueError, match="already has an assigned Coordinator"):
            assignment.try_assign_and_advance(event)

        assert event.coordinator_id == coordinator.id
        assert event.status == "submitted"


def test_try_assign_and_advance_rejects_non_submitted_event(
    app, organiser, make_user, make_event
):
    with app.app_context():
        make_coordinator(make_user, "wrong-status@test.com")
        event = make_event_for_assignment(
            make_event, organiser, "planning", coordinator_id=None
        )

        with pytest.raises(ValueError, match="Only a submitted, unassigned event"):
            assignment.try_assign_and_advance(event)

        assert event.coordinator_id is None
        assert event.status == "planning"


def test_coordinator_calendar_deduplicates_history_and_marks_prior_owner_read_only(
    app, organiser, make_user, make_event
):
    with app.app_context():
        coordinator_a = make_coordinator(make_user, "calendar-a@test.com")
        coordinator_b = make_coordinator(make_user, "calendar-b@test.com")
        event = make_event_for_assignment(
            make_event, organiser, "planning", coordinator_id=None
        )

        assignment.assign_coordinator(event, coordinator_a)
        assignment.reassign_coordinator(event, coordinator_b)
        assignment.reassign_coordinator(event, coordinator_a)
        assignment.reassign_coordinator(event, coordinator_b)

        calendar = assignment.coordinator_calendar(coordinator_a.id)

        assert len(calendar) == 1
        assert calendar[0]["id"] == event.id
        assert calendar[0]["isReadOnly"] is True
        assert assignment.has_coordinator_history(event, coordinator_a.id) is True
        assert assignment.has_coordinator_history(event, organiser) is False


def test_request_reassignment_rejects_reason_over_limit(
    app, organiser, make_user, make_event
):
    with app.app_context():
        coordinator = make_coordinator(make_user, "long-reason@test.com")
        event = make_event_for_assignment(
            make_event, organiser, "planning", coordinator.id
        )

        with pytest.raises(ValueError, match="500 characters or fewer"):
            assignment.request_reassignment(event, coordinator.id, "x" * 501)

        assert CoordinatorReassignmentRequest.query.count() == 0


def test_decline_reassignment_requires_a_pending_request(app, organiser, make_event):
    with app.app_context():
        event = make_event_for_assignment(make_event, organiser, "planning")

        with pytest.raises(ValueError, match="There is no pending reassignment request"):
            assignment.decline_reassignment_request(event, lead_id=999)


def test_decline_reassignment_rejects_note_over_limit(
    app, organiser, make_user, make_event
):
    with app.app_context():
        coordinator = make_coordinator(make_user, "decline-note@test.com")
        event = make_event_for_assignment(
            make_event, organiser, "planning", coordinator.id
        )
        request = assignment.request_reassignment(
            event, coordinator.id, "Coordinator unavailable"
        )

        with pytest.raises(ValueError, match="500 characters or fewer"):
            assignment.decline_reassignment_request(
                event, lead_id=999, note="x" * 501
            )

        db.session.refresh(request)
        assert request.status == "pending"
        assert request.decision_note is None


def test_withdraw_reassignment_requires_a_pending_request(app, organiser, make_event):
    with app.app_context():
        event = make_event_for_assignment(make_event, organiser, "planning")

        with pytest.raises(ValueError, match="There is no pending reassignment request"):
            assignment.withdraw_reassignment_request(event, coordinator_id=999)


def test_only_requesting_coordinator_can_withdraw_reassignment(
    app, organiser, make_user, make_event
):
    with app.app_context():
        requester = make_coordinator(make_user, "withdraw-requester@test.com")
        other = make_coordinator(make_user, "withdraw-other@test.com")
        event = make_event_for_assignment(
            make_event, organiser, "planning", requester.id
        )
        request = assignment.request_reassignment(
            event, requester.id, "Coordinator unavailable"
        )

        with pytest.raises(PermissionError, match="Only the Coordinator who asked"):
            assignment.withdraw_reassignment_request(event, other.id)

        db.session.refresh(request)
        assert request.status == "pending"
