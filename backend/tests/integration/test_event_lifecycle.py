"""
Smoke test covering the core Sprint-1 path across the first six epics:
draft -> submit -> auto-assign -> approve, and reject -> resubmit.
"""
from app.extensions import db
from app.events.services import drafts, review
from app.models.event import Event


def test_draft_submit_and_auto_assignment_flow(app, organiser, coordinator):
    with app.app_context():
        event = drafts.create_draft(
            organiser,
            {
                "name": "Annual Conference",
                "purpose": "Networking",
                "description": "A conference for the team",
                "proposed_date": "2026-12-01",
                "proposed_time": "09:00",
                "expected_attendance": 100,
                "capacity_needed": 120,
                "required_layout": "theatre",
                "accessibility_needs": "None",
            },
        )
        assert event.status == "draft"

        event = review.submit_event(event, organiser)
        assert event.status == "under_review"
        assert event.coordinator_id == coordinator

        event = review.approve_event(event, coordinator, comments="Looks good")
        assert event.status == "planning"
        assert event.review_outcome == "approved"


def test_reject_and_resubmit_creates_new_record(app, organiser, coordinator):
    with app.app_context():
        event = drafts.create_draft(
            organiser,
            {
                "name": "Product Launch",
                "purpose": "Launch",
                "description": "Launch event",
                "proposed_date": "2026-11-01",
                "proposed_time": "09:00",
                "expected_attendance": 50,
                "capacity_needed": 60,
                "required_layout": "theatre",
                "accessibility_needs": "None",
            },
        )
        event = review.submit_event(event, organiser)
        event = review.reject_event(event, coordinator, reason="Date conflicts with another event")
        assert event.status == "rejected"

        new_event = review.resubmit_rejected_event(event, organiser, {"proposed_date": "2026-11-15"})
        assert new_event.id != event.id
        assert new_event.resubmitted_from_event_id == event.id
        assert new_event.status == "under_review"

        # original stays retained with its final status (Event Status Management)
        original = db.session.get(Event, event.id)
        assert original.status == "rejected"
