"""Event Coordinator notifications (assignment + venue booking updates).

User story: As an Event Coordinator, I want to be notified when a new event
request is assigned to me or a venue booking request changes status, so that
I can proceed with the event planning accordingly. One test per AC.
"""
from datetime import time

import pytest

from app.events.services import assignment
from app.extensions import db
from app.models.notification import (
    TYPE_COORDINATOR_ASSIGNMENT,
    TYPE_VENUE_BOOKING_UPDATE,
    Notification,
)
from app.models.user import User
from app.models.venue import Venue
from app.venues.services import booking as booking_service
from app.venues.services.booking_requests import submit_booking_requests
from tests.unit.test_notification_stories import FUTURE, inbox, new_event
from app.events.services import review


@pytest.fixture()
def staff(make_user):
    return {
        "lead": make_user("lead@test.com", ["event_coordinator_lead"], name="Lena Lead"),
        "coord_a": make_user("a@test.com", ["event_coordinator"], name="Ada Coordinator"),
        "coord_b": make_user("b@test.com", ["event_coordinator"], name="Ben Coordinator"),
        "coord_c": make_user("c@test.com", ["event_coordinator"], name="Cal Coordinator"),
        "venue": make_user("venue@test.com", ["venue_staff"], name="Vic Venue"),
    }


def user(uid):
    return db.session.get(User, uid)


def assigned(organiser, coordinator, lead):
    event = review.submit_event(new_event(organiser), organiser)
    return assignment.lead_assign(event, user(coordinator), assigned_by_id=lead)


def booking_for(event, coordinator, venue_staff):
    venue = Venue(name="Grand Hall", capacity=300, created_by=venue_staff)
    db.session.add(venue)
    db.session.commit()
    [booking] = submit_booking_requests(
        event, [{"venue_id": venue.id, "date": FUTURE, "start_time": time(18), "end_time": time(23)}],
        coordinator,
    )
    return booking


# AC1 + AC2 ---------------------------------------------------------------------
def test_ac1_ac2_assignment_notifies_with_details_and_link(app, organiser, staff):
    event = assigned(organiser, staff["coord_a"], staff["lead"])
    [n] = inbox(staff["coord_a"], TYPE_COORDINATOR_ASSIGNMENT)
    assert n.data["requestId"] == event.id
    assert n.data["eventName"] == "Gala Night"
    assert FUTURE.strftime("%b %Y") in n.data["eventDate"]
    assert n.data["requesterName"] == "Test Organiser"
    assert n.link == f"/events/{event.id}"
    assert f"#{event.id}" in n.message and "Gala Night" in n.message and "Test Organiser" in n.message


# AC3 ---------------------------------------------------------------------------
def test_ac3_reassignment_notifies_new_and_previous(app, organiser, staff):
    event = assigned(organiser, staff["coord_a"], staff["lead"])
    assignment.lead_reassign(event, user(staff["coord_b"]), assigned_by_id=staff["lead"])
    [new] = inbox(staff["coord_b"], TYPE_COORDINATOR_ASSIGNMENT)
    assert new.data["kind"] == "reassigned" and new.link == f"/events/{event.id}"
    removed = inbox(staff["coord_a"], TYPE_COORDINATOR_ASSIGNMENT)[-1]
    assert removed.data["kind"] == "removed" and "Ben Coordinator" in removed.message


# AC4 ---------------------------------------------------------------------------
def test_ac4_only_the_assigned_coordinator_is_notified(app, organiser, staff):
    assigned(organiser, staff["coord_a"], staff["lead"])
    assert len(inbox(staff["coord_a"], TYPE_COORDINATOR_ASSIGNMENT)) == 1
    for other in ("coord_b", "coord_c", "venue"):
        assert inbox(staff[other], TYPE_COORDINATOR_ASSIGNMENT) == []


# AC5 ---------------------------------------------------------------------------
@pytest.mark.parametrize("change", ["approved", "rejected"])
def test_ac5_venue_booking_status_change_notifies_coordinator(app, organiser, staff, change):
    event = new_event(organiser, "planning", staff["coord_a"])
    booking = booking_for(event, staff["coord_a"], staff["venue"])
    if change == "approved":
        booking_service.approve_booking(booking, staff["venue"])
    else:
        booking_service.reject_booking(booking, staff["venue"], reason="Closed for maintenance")
    [n] = inbox(staff["coord_a"], TYPE_VENUE_BOOKING_UPDATE)
    assert n.data["change"] == change and n.data["venueName"] == "Grand Hall"
    assert "Grand Hall" in n.message and "Gala Night" in n.message
    assert n.link == f"/events/{event.id}"
    if change == "rejected":
        assert "Closed for maintenance" in n.message


# AC6 (edge) --------------------------------------------------------------------
def test_ac6_after_reassignment_booking_updates_go_only_to_new_coordinator(app, organiser, staff):
    event = assigned(organiser, staff["coord_a"], staff["lead"])
    event.status = "planning"
    db.session.commit()
    booking = booking_for(event, staff["coord_a"], staff["venue"])  # requested by A
    assignment.lead_reassign(event, user(staff["coord_b"]), assigned_by_id=staff["lead"])

    booking_service.approve_booking(booking, staff["venue"])
    assert len(inbox(staff["coord_b"], TYPE_VENUE_BOOKING_UPDATE)) == 1
    assert inbox(staff["coord_a"], TYPE_VENUE_BOOKING_UPDATE) == []


# AC7 (edge) --------------------------------------------------------------------
def test_ac7_failed_assignment_sends_no_notification(app, organiser, staff):
    event = assigned(organiser, staff["coord_a"], staff["lead"])
    before = Notification.query.count()

    # Another Lead tries to assign the already-assigned request.
    with pytest.raises(assignment.AlreadyAssignedError):
        assignment.lead_assign(event, user(staff["coord_b"]), assigned_by_id=staff["lead"])
    # Reassigning to the same Coordinator is refused.
    with pytest.raises(ValueError):
        assignment.lead_reassign(event, user(staff["coord_a"]), assigned_by_id=staff["lead"])
    # An inactive Coordinator cannot be given the request.
    inactive = user(staff["coord_c"])
    inactive.is_active = False
    db.session.commit()
    with pytest.raises(ValueError):
        assignment.lead_reassign(event, inactive, assigned_by_id=staff["lead"])

    assert Notification.query.count() == before
    assert inbox(staff["coord_b"], TYPE_COORDINATOR_ASSIGNMENT) == []
    assert inbox(staff["coord_c"], TYPE_COORDINATOR_ASSIGNMENT) == []


# AC8 (edge) --------------------------------------------------------------------
def test_ac8_notification_private_and_unread_until_opened(app, client, auth_header, organiser, staff):
    assigned(organiser, staff["coord_a"], staff["lead"])
    a = auth_header("a@test.com")
    [n] = [x for x in client.get("/api/notifications", headers=a).get_json()
           if x["type"] == TYPE_COORDINATOR_ASSIGNMENT]
    assert n["isRead"] is False
    assert client.get("/api/notifications/unread-count", headers=a).get_json()["count"] >= 1

    # Another Coordinator can neither see nor mark it.
    b = auth_header("b@test.com")
    assert n["id"] not in [x["id"] for x in client.get("/api/notifications", headers=b).get_json()]
    assert client.post(f"/api/notifications/{n['id']}/read", headers=b).status_code == 404

    assert client.post(f"/api/notifications/{n['id']}/read", headers=a).status_code == 200
    again = [x for x in client.get("/api/notifications", headers=a).get_json() if x["id"] == n["id"]]
    assert again and again[0]["isRead"] is True  # still viewable after reading
