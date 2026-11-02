"""
Smoke test covering the core Sprint-1 path across the first six epics:
draft -> submit -> Lead assigns -> approve, and reject -> resubmit.
"""
from datetime import date, timedelta

from app.extensions import db
from app.events.services import assignment, drafts, review, status
from app.models.event import Event
from app.models.user import User

# Relative dates: a fixed calendar date eventually falls into the past and then
# fails the "proposed date cannot be in the past" rule.
FUTURE = (date.today() + timedelta(days=30)).isoformat()
LATER = (date.today() + timedelta(days=44)).isoformat()


def test_draft_submit_and_auto_assignment_flow(app, organiser, coordinator):
    with app.app_context():
        event = drafts.create_draft(
            organiser,
            {
                "name": "Annual Conference",
                "purpose": "Networking",
                "description": "A conference for the team",
                "proposed_date": FUTURE,
                "proposed_time": "09:00",
                "expected_attendance": 100,
                "capacity_needed": 120,
                "required_layout": "theatre",
                "accessibility_needs": "None",
            },
        )
        assert event.status == "draft"

        event = review.submit_event(event, organiser)
        assert event.status == "submitted"  # waits in the Unassigned queue
        event = assignment.lead_assign(event, db.session.get(User, coordinator))
        assert event.status == "under_review"
        assert event.coordinator_id == coordinator

        event = review.approve_event(event, coordinator, comments="Looks good")
        assert event.status == "approved"
        assert event.review_outcome == "approved"

        # Coordinator explicitly proceeds to planning.
        event = status.change_status(event, "planning", coordinator)
        assert event.status == "planning"


def test_reject_and_resubmit_creates_new_record(app, organiser, coordinator):
    with app.app_context():
        event = drafts.create_draft(
            organiser,
            {
                "name": "Product Launch",
                "purpose": "Launch",
                "description": "Launch event",
                "proposed_date": FUTURE,
                "proposed_time": "09:00",
                "expected_attendance": 50,
                "capacity_needed": 60,
                "required_layout": "theatre",
                "accessibility_needs": "None",
            },
        )
        event = review.submit_event(event, organiser)
        event = assignment.lead_assign(event, db.session.get(User, coordinator))
        event = review.reject_event(event, coordinator, reason="Date conflicts with another event")
        assert event.status == "rejected"

        new_event = review.resubmit_rejected_event(event, organiser, {"proposed_date": LATER})
        assert new_event.id != event.id
        assert new_event.resubmitted_from_event_id == event.id
        assert new_event.status == "submitted"  # back in the Unassigned queue

        # original stays retained with its final status (Event Status Management)
        original = db.session.get(Event, event.id)
        assert original.status == "rejected"
