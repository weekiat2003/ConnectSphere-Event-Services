"""Significant changes: Venue Staff and Technical Support are told to discuss with the Coordinator."""
from datetime import timedelta

import pytest

from app.change_requests import services as cr
from app.common.time import utcnow
from app.events.services import update as update_service
from app.extensions import db
from app.models.event import Event, EventEquipmentRequirement
from app.models.notification import NOTIFICATION_TYPES, TYPE_ARRANGEMENT_REVIEW, Notification
from app.models.user import User
from app.models.venue import Venue, VenueBooking
from app.notifications.services import core, triggers
from tests.unit.test_notification_stories import new_event

REASON = "The client moved their launch to a later week."


def inbox(user_id):
    return Notification.query.filter_by(recipient_id=user_id, type=TYPE_ARRANGEMENT_REVIEW).order_by(Notification.id).all()


@pytest.fixture()
def staff(make_user):
    return {
        "venue1": make_user("arr-venue1@test.com", ["venue_staff"], name="Vic Venue"),
        "venue2": make_user("arr-venue2@test.com", ["venue_staff"], name="Val Venue"),
        "tech": make_user("arr-tech@test.com", ["technical_support_staff"], name="Tia Tech"),
        "both": make_user("arr-both@test.com", ["venue_staff", "technical_support_staff"], name="Bo Both"),
    }


def book(event, created_by, status="approved", name="Grand Hall"):
    venue = Venue(name=name, capacity=300, created_by=created_by)
    db.session.add(venue)
    db.session.flush()
    start = utcnow() + timedelta(days=10)
    booking = VenueBooking(event_id=event.id, venue_id=venue.id, requested_by=event.coordinator_id,
                           status=status, start_datetime=start, end_datetime=start + timedelta(hours=3))
    db.session.add(booking)
    db.session.commit()
    return booking


def add_equipment(event):
    event.equipment_requirements.append(EventEquipmentRequirement(equipment_type="Projector", quantity=2))
    db.session.commit()


def planning_event(organiser, coordinator):
    return new_event(organiser, "planning", coordinator)


def test_type_is_registered():
    assert TYPE_ARRANGEMENT_REVIEW in NOTIFICATION_TYPES


def test_notify_accepts_the_type(app, organiser):
    core.notify(organiser, TYPE_ARRANGEMENT_REVIEW, "Title", "Body")  # raises if unknown


@pytest.mark.parametrize("status", ["pending", "approved", "held"])
def test_live_booking_notifies_the_venue_manager_with_details_and_link(
    app, organiser, coordinator, staff, status
):
    event = planning_event(organiser, coordinator)
    booking = book(event, staff["venue1"], status=status)

    triggers.notify_arrangements_of_significant_change(event, ["expected_attendance", "accessibility_needs"])

    [n] = inbox(staff["venue1"])
    assert "Grand Hall" in n.message and "Gala Night" in n.message
    assert "Expected attendance" in n.message and "Accessibility needs" in n.message
    assert "discuss with the Coordinator" in n.message
    assert n.link == f"/venues/approval?booking={booking.id}"
    assert n.data["bookingId"] == booking.id and n.data["venueName"] == "Grand Hall"
    assert n.data["fields"] == ["accessibility_needs", "expected_attendance"]
    assert inbox(staff["venue2"]) == []


@pytest.mark.parametrize("status", ["rejected", "cancelled", "withdrawn", "expired", "released"])
def test_finished_bookings_notify_nobody(app, organiser, coordinator, staff, status):
    event = planning_event(organiser, coordinator)
    book(event, staff["venue1"], status=status)

    triggers.notify_arrangements_of_significant_change(event, ["proposed_date"])

    assert Notification.query.filter_by(type=TYPE_ARRANGEMENT_REVIEW).count() == 0


def test_technical_support_is_notified_only_when_equipment_is_required(app, organiser, coordinator, staff):
    event = planning_event(organiser, coordinator)

    triggers.notify_arrangements_of_significant_change(event, ["proposed_date"])
    assert inbox(staff["tech"]) == []

    add_equipment(event)
    triggers.notify_arrangements_of_significant_change(event, ["proposed_date"])

    [n] = inbox(staff["tech"])
    assert n.link == f"/technical-review?event={event.id}"
    assert "discuss with the Coordinator" in n.message


def test_user_with_both_roles_gets_one_notice_per_arrangement(app, organiser, coordinator, staff):
    event = planning_event(organiser, coordinator)
    book(event, staff["both"])
    add_equipment(event)

    triggers.notify_arrangements_of_significant_change(event, ["proposed_date"])

    assert len(inbox(staff["both"])) == 2  # one for the venue, one for the equipment


def test_event_with_no_arrangements_notifies_nobody(app, organiser, coordinator, staff):
    event = planning_event(organiser, coordinator)

    assert triggers.notify_arrangements_of_significant_change(event, ["proposed_date"]) == []
    assert Notification.query.filter_by(type=TYPE_ARRANGEMENT_REVIEW).count() == 0


def test_coordinator_and_organiser_are_not_notified(app, organiser, coordinator, staff):
    event = planning_event(organiser, coordinator)
    book(event, staff["venue1"])
    add_equipment(event)

    triggers.notify_arrangements_of_significant_change(event, ["proposed_date"])

    assert inbox(organiser) == [] and inbox(coordinator) == []


def test_all_venue_staff_are_told_when_the_creator_is_not_venue_staff(app, organiser, coordinator, staff):
    # Only applies if you added the fallback to list(venue_staff_ids).
    event = planning_event(organiser, coordinator)
    book(event, organiser)  # created by a user who is not Venue Staff

    triggers.notify_arrangements_of_significant_change(event, ["proposed_date"])

    assert len(inbox(staff["venue1"])) == 1 and len(inbox(staff["venue2"])) == 1


# ---- where it fires ----------------------------------------------------

def test_re_review_notifies_for_a_significant_change(app, organiser, coordinator, staff):
    event = planning_event(organiser, coordinator)
    book(event, staff["venue1"])
    request = cr.submit_change_request(event, organiser, {"accessibility_needs": "Hearing loop"}, REASON)

    cr.trigger_re_review(request.id, coordinator)

    [n] = inbox(staff["venue1"])
    assert "Accessibility needs" in n.message


def test_applying_after_re_review_does_not_notify_again(app, organiser, coordinator, staff):
    event = planning_event(organiser, coordinator)
    book(event, staff["venue1"])
    request = cr.submit_change_request(event, organiser, {"expected_attendance": 140}, REASON)
    cr.trigger_re_review(request.id, coordinator)

    cr.apply_re_reviewed_change(request.id, coordinator)

    assert len(inbox(staff["venue1"])) == 1


def test_processing_a_routine_change_does_not_notify(app, organiser, coordinator, staff):
    event = planning_event(organiser, coordinator)
    book(event, staff["venue1"])
    add_equipment(event)
    request = cr.submit_change_request(event, organiser, {"name": "Gala Summit"}, REASON)

    cr.process_routine_change(request.id, coordinator)

    assert Notification.query.filter_by(type=TYPE_ARRANGEMENT_REVIEW).count() == 0


@pytest.mark.parametrize("fields, expected", [
    ({"accessibility_needs": "Hearing loop"}, 1),
    ({"expected_attendance": 130}, 1),
    ({"purpose": "New purpose"}, 0),
])
def test_coordinator_edit_notifies_only_for_significant_fields(
    app, organiser, coordinator, staff, fields, expected
):
    event = planning_event(organiser, coordinator)
    book(event, staff["venue1"])

    update_service.update_event_fields(
        event, db.session.get(User, coordinator), fields, offline_review_confirmed=True
    )

    assert len(inbox(staff["venue1"])) == expected


def test_organiser_text_says_the_coordinator_will_update_the_event(app, organiser, coordinator):
    event = planning_event(organiser, coordinator)
    request = cr.submit_change_request(event, organiser, {"name": "Gala Summit"}, REASON)

    for outcome in ("processed", "applied"):
        triggers.notify_organiser_of_change_request(event, request, outcome)

    messages = [n.message for n in Notification.query.filter_by(recipient_id=organiser)]
    assert len(messages) == 2
    assert all("will update the event details" in m for m in messages)