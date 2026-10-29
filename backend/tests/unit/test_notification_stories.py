"""Notification System epic: one test class per story, named after its ticket.

Each test drives the real service (or API) action and then checks who was
notified and what the notification says — i.e. the acceptance criteria.
"""
from datetime import date, time, timedelta

import pytest

from app.common.time import utcnow
from app.events.services import assignment, review, safety, status
from app.events.services import update as update_service
from app.extensions import db
from app.models.notification import (
    TYPE_COORDINATOR_ASSIGNMENT,
    TYPE_NEW_EQUIPMENT_REQUEST,
    TYPE_NEW_EVENT_SUBMISSION,
    TYPE_NEW_VENUE_BOOKING_REQUEST,
    TYPE_ORGANISER_UPDATE,
    TYPE_REGISTRATION_CHANGE,
    TYPE_SAFETY_CHECK,
    TYPE_VENUE_BOOKING_UPDATE,
    Notification,
)
from app.models.user import User
from app.models.venue import Venue, VenueBooking, BOOKING_APPROVED
from app.models.event import Event, EventEquipmentRequirement, EventSafetyReview
from app.registrations import service as registrations
from app.venues.services import booking as booking_service
from app.venues.services.booking_requests import (BookingRequestError,submit_booking_requests,)

FUTURE = date.today() + timedelta(days=60)


def inbox(user_id, type_=None):
    query = Notification.query.filter_by(recipient_id=user_id)
    if type_:
        query = query.filter_by(type=type_)
    return query.order_by(Notification.id).all()


def kinds(user_id):
    return [n.data.get("kind") for n in inbox(user_id, TYPE_ORGANISER_UPDATE)]


@pytest.fixture()
def staff(make_user):
    return {
        "lead1": make_user("lead1@test.com", ["event_coordinator_lead"], name="Lena Lead"),
        "lead2": make_user("lead2@test.com", ["event_coordinator_lead"], name="Leo Lead"),
        "coord_b": make_user("coord-b@test.com", ["event_coordinator"], name="Bea Coordinator"),
        "venue1": make_user("venue1@test.com", ["venue_staff"], name="Vic Venue"),
        "venue2": make_user("venue2@test.com", ["venue_staff"], name="Val Venue"),
        "tech": make_user("tech@test.com", ["technical_support_staff"], name="Tia Tech"),
        "safety1": make_user("safety1@test.com", ["safety_officer"], name="Sid Safety"),
        # Holds two roles: must still get exactly one safety notification.
        "safety2": make_user("safety2@test.com", ["safety_officer", "event_coordinator"], name="Sue Safety"),
    }


def new_event(organiser_id, status_="draft", coordinator_id=None, **fields):
    values = dict(
        name="Gala Night", purpose="Fundraising", description="Annual fundraising gala",
        category="Social", proposed_date=FUTURE, proposed_time=time(19, 0),
        expected_attendance=120, capacity_needed=150, required_layout="banquet",
        accessibility_needs="Step-free access",
    )
    values.update(fields)
    event = Event(organiser_id=organiser_id, status=status_, coordinator_id=coordinator_id, **values)
    db.session.add(event)
    db.session.commit()
    return event


def submitted_and_assigned(organiser, coordinator):
    event = review.submit_event(new_event(organiser), organiser)
    return assignment.lead_assign(event, db.session.get(User, coordinator))

# helper function to create an event that is ready for safety check
def ready_event(organiser_id, coordinator_id, venue_manager_id, venue_name="Grand Hall", **fields):
    """Planning event with an approved venue booking, so it may enter the safety check."""
    event = new_event(organiser_id, "planning", coordinator_id, **fields)
    venue = Venue(name=venue_name, capacity=300, created_by=venue_manager_id)
    db.session.add(venue)
    db.session.flush()
    start = utcnow() + timedelta(days=10)
    db.session.add(VenueBooking(
        event_id=event.id, venue_id=venue.id, requested_by=coordinator_id,
        status=BOOKING_APPROVED, start_datetime=start, end_datetime=start + timedelta(hours=3)))
    db.session.commit()
    return event
# ===========================================================================
# ISP-102 — Organiser
# ===========================================================================
class TestISP102Organiser:
    def test_ac1_submission(self, app, organiser, staff):
        event = review.submit_event(new_event(organiser), organiser)
        [n] = inbox(organiser, TYPE_ORGANISER_UPDATE)
        assert n.title == "Request submitted"
        assert f'"{event.name}" was submitted' in n.message

    def test_ac2_approval_and_rejection_with_reason(self, app, organiser, coordinator, staff):
        approved = submitted_and_assigned(organiser, coordinator)
        review.approve_event(approved, coordinator, "Looks good")
        rejected = submitted_and_assigned(organiser, coordinator)
        review.reject_event(rejected, coordinator, "The venue is unavailable that week.")

        by_kind = {n.data["kind"]: n for n in inbox(organiser, TYPE_ORGANISER_UPDATE)}
        assert by_kind["approved"].event_id == approved.id
        assert "The venue is unavailable that week." in by_kind["rejected"].message

    def test_ac3_clarification_includes_comments_and_editable_fields(self, app, organiser, coordinator, staff):
        event = submitted_and_assigned(organiser, coordinator)
        review.request_clarification(event, coordinator, "Please confirm the guest list size.",
                                     ["expected_attendance"])
        [n] = [n for n in inbox(organiser, TYPE_ORGANISER_UPDATE) if n.data["kind"] == "clarification_requested"]
        assert "Please confirm the guest list size." in n.message
        assert "Expected attendance" in n.message
        assert n.data["editableFields"] == ["expected_attendance"]

    def test_ac4_and_ac5_safety_stage_and_decisions(self, app, organiser, coordinator, staff):
        event = ready_event(organiser, coordinator, staff["venue1"])
        status.change_status(event, "safety_check", coordinator)
        officer = db.session.get(User, staff["safety1"])
        safety.review_safety_check(
            event, officer, "changes_requested", comments="The fire exit is blocked by staging.",
            assessed_factors=["emergency_access"], concern_factors=["emergency_access"],
            affected_arrangements=["venue"],
        )
        assert event.status == "planning"
        
        status.change_status(event, "safety_check", coordinator)
        safety.review_safety_check(event, officer, "approved", assessed_factors=list(safety.SAFETY_FACTOR_ORDER))

        # Approval alone no longer confirms the event — the assigned Coordinator
        # must explicitly confirm it (Clarification Session 3).
        latest_review = (
            EventSafetyReview.query.filter_by(event_id=event.id)
            .order_by(EventSafetyReview.id.desc())
            .first()
        )
        status.confirm_after_safety_approval(event, latest_review, coordinator)

        assert kinds(organiser) == ["safety_check", "safety_changes_requested", "safety_check", "confirmed"]
        
        decision = [n for n in inbox(organiser) if n.data.get("kind") == "safety_changes_requested"][0]
        assert "The fire exit is blocked by staging." in decision.message
        assert decision.data["affectedArrangements"] == ["venue"]
        assert "returned to planning" in decision.message

    def test_ac6_cancellation_with_reason(self, app, organiser, coordinator, staff):
        event = new_event(organiser, "planning", coordinator)
        status.cancel_event(event.id, coordinator, "The sponsor has withdrawn funding.")
        [n] = inbox(organiser, TYPE_ORGANISER_UPDATE)
        assert n.data["kind"] == "cancelled"
        assert "The sponsor has withdrawn funding." in n.message

    def test_ac7_reschedule_shows_previous_and_new(self, app, organiser, coordinator, staff):
        event = new_event(organiser, "planning", coordinator)
        user = db.session.get(User, coordinator)
        new_date = FUTURE + timedelta(days=7)
        update_service.update_event_fields(
            event, user, {"proposed_date": new_date, "proposed_time": time(18, 30)},
            offline_review_confirmed=True,
        )
        [n] = [n for n in inbox(organiser) if n.data.get("kind") == "rescheduled"]
        assert n.data["previous"].endswith("19:00") and n.data["new"].endswith("18:30")
        assert new_date.strftime("%b %Y") in n.data["new"]

    def test_ac8_ac9_inbox_is_private_shows_event_and_tracks_read(
        self, app, client, auth_header, organiser, make_user, staff
    ):
        event = review.submit_event(new_event(organiser), organiser)
        make_user("other-org@test.com", ["event_organiser"])
        mine = client.get("/api/notifications", headers=auth_header("organiser@test.com")).get_json()
        assert [(n["eventName"], n["link"]) for n in mine] == [(event.name, f"/events/{event.id}")]
        assert mine[0]["createdAt"]
        assert client.get("/api/notifications", headers=auth_header("other-org@test.com")).get_json() == []

        headers = auth_header("organiser@test.com")
        client.post(f"/api/notifications/{mine[0]['id']}/read", headers=headers)
        assert client.get("/api/notifications/unread-count", headers=headers).get_json()["count"] == 0

    def test_first_assignment_is_not_a_change(self, app, organiser, coordinator, staff):
        submitted_and_assigned(organiser, coordinator)
        assert "coordinator_changed" not in kinds(organiser)

    def test_planning_started_even_without_equipment(self, app, organiser, coordinator, staff):
        review.approve_event(submitted_and_assigned(organiser, coordinator), coordinator)
        assert "planning_started" in kinds(organiser)

    def test_completed(self, app, organiser, coordinator, staff):
        event = new_event(organiser, "confirmed", coordinator)
        status.change_status(event, "completed", coordinator)
        assert kinds(organiser) == ["completed"]

    def test_registration_open_close_notifies_organiser(self, app, organiser, coordinator):
        event = public_event(organiser, coordinator)
        registrations.open_registration(event.id, organiser)
        registrations.close_registration(event.id, organiser)
        notes = inbox(organiser, TYPE_ORGANISER_UPDATE)
        assert [n.data["kind"] for n in notes] == ["registration_opened", "registration_closed"]
        assert all(event.name in n.message for n in notes)


# ===========================================================================
# ISP-103 — Event Coordinator Lead
# ===========================================================================
class TestISP103CoordinatorLead:
    def test_ac1_ac2_ac3_only_leads_notified_with_request_details(self, app, organiser, coordinator, staff):
        event = review.submit_event(new_event(organiser), organiser)
        assert event.status == "submitted" and event.coordinator_id is None  # Unassigned

        for lead in ("lead1", "lead2"):
            [n] = inbox(staff[lead], TYPE_NEW_EVENT_SUBMISSION)
            assert n.data["requestId"] == event.id
            assert n.data["title"] == "Gala Night"
            assert n.data["requesterName"] == "Test Organiser"
            assert n.data["eventType"] == "Social"
            assert n.data["submittedAt"] == event.submitted_at.isoformat()
        assert Notification.query.filter_by(type=TYPE_NEW_EVENT_SUBMISSION).count() == 2
        assert inbox(coordinator) == []

    def test_ac4_ac5_lead_assigns_coordinator_is_notified_other_leads_cleared(
        self, app, client, auth_header, organiser, coordinator, staff
    ):
        event = review.submit_event(new_event(organiser), organiser)
        lead1 = auth_header("lead1@test.com")
        url = f"/api/events/{event.id}/assign"

        asked = client.post(url, headers=lead1, json={"coordinatorId": coordinator})
        assert asked.status_code == 409 and asked.get_json()["requiresConfirmation"]
        done = client.post(url, headers=lead1, json={"coordinatorId": coordinator, "confirmed": True})
        assert done.status_code == 200, done.get_json()
        assert done.get_json()["status"] == "under_review"
        assert event.id not in [e["id"] for e in client.get("/api/events/unassigned", headers=lead1).get_json()]

        assert len(inbox(coordinator, TYPE_COORDINATOR_ASSIGNMENT)) == 1
        lead2_notice = inbox(staff["lead2"], TYPE_NEW_EVENT_SUBMISSION)[0]
        assert lead2_notice.cleared_at is not None and lead2_notice.is_read
        assert lead2_notice.data["assignedTo"] == "Test Coordinator"

        late = client.post(url, headers=auth_header("lead2@test.com"),
                           json={"coordinatorId": staff["coord_b"], "confirmed": True})
        assert late.status_code == 409
        assert late.get_json()["assignedTo"] == "Test Coordinator"

    def test_only_leads_can_assign(self, app, client, auth_header, organiser, coordinator, staff):
        event = review.submit_event(new_event(organiser), organiser)
        res = client.post(f"/api/events/{event.id}/assign", headers=auth_header("coordinator@test.com"),
                          json={"coordinatorId": coordinator, "confirmed": True})
        assert res.status_code == 403


# ===========================================================================
# ISP-105 — Coordinator
# ===========================================================================
class TestISP105Coordinator:
    def test_ac1_ac2_assignment_details_and_only_assignee(self, app, organiser, coordinator, staff):
        event = submitted_and_assigned(organiser, coordinator)
        [n] = inbox(coordinator, TYPE_COORDINATOR_ASSIGNMENT)
        assert n.data == {
            "kind": "assigned", "requestId": event.id, "eventName": "Gala Night",
            "eventDate": n.data["eventDate"], "requesterName": "Test Organiser",
        }
        assert FUTURE.strftime("%b %Y") in n.data["eventDate"]
        assert n.link == f"/events/{event.id}"
        assert inbox(staff["coord_b"], TYPE_COORDINATOR_ASSIGNMENT) == []

    def test_ac3_lead_reassignment_notifies_new_and_previous(
        self, app, client, auth_header, organiser, coordinator, staff
    ):
        event = submitted_and_assigned(organiser, coordinator)
        res = client.post(f"/api/events/{event.id}/lead-reassign", headers=auth_header("lead1@test.com"),
                          json={"coordinatorId": staff["coord_b"], "confirmed": True})
        assert res.status_code == 200, res.get_json()
        [new] = inbox(staff["coord_b"], TYPE_COORDINATOR_ASSIGNMENT)
        assert new.data["kind"] == "reassigned"
        removed = inbox(coordinator, TYPE_COORDINATOR_ASSIGNMENT)[-1]
        assert removed.data["kind"] == "removed" and "Bea Coordinator" in removed.message

    def test_venue_booking_status_changes_reach_the_coordinator(self, app, organiser, coordinator, staff):
        event = new_event(organiser, "planning", coordinator)
        venue = Venue(name="Grand Hall", capacity=300, created_by=staff["venue1"])
        db.session.add(venue)
        db.session.commit()
        [booking] = submit_booking_requests(
            event, [{"venue_id": venue.id, "date": FUTURE, "start_time": time(18), "end_time": time(23)}],
            coordinator,
        )
        booking_service.reject_booking(booking, staff["venue1"], reason="Closed for maintenance")
        [n] = inbox(coordinator, TYPE_VENUE_BOOKING_UPDATE)
        assert n.title == "Venue booking rejected" and "Closed for maintenance" in n.message



# ===========================================================================
# ISP-104 — Venue Staff
# ===========================================================================
class TestISP104VenueStaff:

    def _submit(self, organiser, coordinator, created_by):
        event = new_event(organiser, "planning", coordinator)
        venue = Venue(
            name="Riverside Room",
            capacity=200,
            created_by=created_by,
        )
        db.session.add(venue)
        db.session.commit()

        [booking] = submit_booking_requests(
            event,
            [{
                "venue_id": venue.id,
                "date": FUTURE,
                "start_time": time(9),
                "end_time": time(12),
            }],
            coordinator,
        )
        return booking

    # -----------------------------------------------------------------------
    # AC1: Successful submission generates a notification.
    # AC2: Notification includes venue name, event name, and booking date.
    # AC3: Only the Venue Staff managing the venue receives it.
    # AC4: Notification contains the corresponding booking's link.
    # -----------------------------------------------------------------------
    def test_only_the_venue_manager_is_notified_with_details_and_link(
        self, app, organiser, coordinator, staff
    ):
        booking = self._submit(
            organiser, coordinator, staff["venue1"]
        )

        [n] = inbox(
            staff["venue1"],
            TYPE_NEW_VENUE_BOOKING_REQUEST,
        )

        assert n.data["venueName"] == "Riverside Room"
        assert n.data["eventName"] == "Gala Night"
        assert FUTURE.strftime("%b %Y") in n.data["bookingDate"]
        assert n.link == f"/venues/approval?booking={booking.id}"

        # AC3: Unrelated Venue Staff must not receive the notification.
        assert inbox(
            staff["venue2"],
            TYPE_NEW_VENUE_BOOKING_REQUEST,
        ) == []

    # -----------------------------------------------------------------------
    # AC2: Notification details are available through the inbox API.
    # AC3: Other Venue Staff cannot see another manager's notification.
    # AC4: Notification provides the correct booking deep link.
    #
    # Note: Actual frontend clicking/navigation requires a browser test.
    # -----------------------------------------------------------------------
    def test_venue_staff_inbox_contains_booking_details_and_deep_link(
        self, app, client, auth_header, organiser, coordinator, staff
    ):
        booking = self._submit(
            organiser, coordinator, staff["venue1"]
        )

        response = client.get(
            "/api/notifications",
            headers=auth_header("venue1@test.com"),
        )

        assert response.status_code == 200

        matches = [
            n for n in response.get_json()
            if n["type"] == TYPE_NEW_VENUE_BOOKING_REQUEST
        ]

        assert len(matches) == 1

        notification = matches[0]

        assert notification["data"]["venueName"] == "Riverside Room"
        assert notification["data"]["eventName"] == "Gala Night"
        assert FUTURE.strftime("%b %Y") in notification["data"]["bookingDate"]
        assert notification["link"] == (
            f"/venues/approval?booking={booking.id}"
        )

        # AC3: Venue Staff 2 must not see Venue Staff 1's notification.
        other = client.get(
            "/api/notifications",
            headers=auth_header("venue2@test.com"),
        )

        assert other.status_code == 200
        assert not any(
            n["type"] == TYPE_NEW_VENUE_BOOKING_REQUEST
            for n in other.get_json()
        )

    # -----------------------------------------------------------------------
    # AC5: Failed or incomplete booking submission must not generate
    #      any Venue Staff notification.
    # -----------------------------------------------------------------------
    def test_failed_booking_submission_creates_no_venue_staff_notification(
        self, app, organiser, coordinator, staff
    ):
        event = new_event(
            organiser, "planning", coordinator
        )

        # Invalid venue ID should cause submission to fail.
        with pytest.raises(BookingRequestError):
            submit_booking_requests(
                event,
                [{
                    "venue_id": -999999,
                    "date": FUTURE,
                    "start_time": time(9),
                    "end_time": time(12),
                }],
                coordinator,
            )

        db.session.rollback()

        # AC5: Neither Venue Staff member should be notified.
        assert inbox(
            staff["venue1"],
            TYPE_NEW_VENUE_BOOKING_REQUEST,
        ) == []

        assert inbox(
            staff["venue2"],
            TYPE_NEW_VENUE_BOOKING_REQUEST,
        ) == []

    # -----------------------------------------------------------------------
    # AC1: Multi-venue submission generates notifications.
    # AC3: Each Venue Staff receives notifications only for venues managed.
    # AC6: Different venue managers each receive the correct notification,
    #      with no duplicates for the same booking.
    # -----------------------------------------------------------------------
    def test_multiple_venues_notify_respective_managers_without_duplicates(
        self, app, organiser, coordinator, staff
    ):
        event = new_event(
            organiser, "planning", coordinator
        )

        venue1 = Venue(
            name="Riverside Room",
            capacity=200,
            created_by=staff["venue1"],
        )

        venue2 = Venue(
            name="Grand Hall",
            capacity=300,
            created_by=staff["venue2"],
        )

        db.session.add_all([venue1, venue2])
        db.session.commit()

        bookings = submit_booking_requests(
            event,
            [
                {
                    "venue_id": venue1.id,
                    "date": FUTURE,
                    "start_time": time(9),
                    "end_time": time(12),
                },
                {
                    "venue_id": venue2.id,
                    "date": FUTURE,
                    "start_time": time(14),
                    "end_time": time(17),
                },
            ],
            coordinator,
        )

        assert len(bookings) == 2

        notices1 = inbox(
            staff["venue1"],
            TYPE_NEW_VENUE_BOOKING_REQUEST,
        )

        notices2 = inbox(
            staff["venue2"],
            TYPE_NEW_VENUE_BOOKING_REQUEST,
        )

        # AC6: Each staff member receives exactly one notification.
        assert len(notices1) == 1
        assert len(notices2) == 1

        # AC3: Notifications belong to the correct venue manager.
        assert notices1[0].data["venueName"] == "Riverside Room"
        assert notices2[0].data["venueName"] == "Grand Hall"

        assert notices1[0].data["eventName"] == event.name
        assert notices2[0].data["eventName"] == event.name

        # AC6: Each notification points to a different booking.
        expected_links = {
            f"/venues/approval?booking={booking.id}"
            for booking in bookings
        }

        assert {
            notices1[0].link,
            notices2[0].link,
        } == expected_links

        assert notices1[0].link != notices2[0].link



# ===========================================================================
# ISP-106 — Technical Support Staff
# ===========================================================================
class TestISP106TechSupport:
    def test_requirements_notified_when_planning_starts_with_details_and_link(
        self, app, organiser, coordinator, staff
    ):
        event = submitted_and_assigned(organiser, coordinator)
        event.equipment_requirements.append(EventEquipmentRequirement(equipment_type="Projector", quantity=2))
        event.equipment_requirements.append(EventEquipmentRequirement(equipment_type="Microphone", quantity=4))
        db.session.commit()
        review.approve_event(event, coordinator)

        [n] = inbox(staff["tech"], TYPE_NEW_EQUIPMENT_REQUEST)
        for text in ("Gala Night", "Test Organiser", "2 × Projector", "4 × Microphone", "venue not yet booked"):
            assert text in n.message
        assert n.link == f"/technical-review?event={event.id}"

    def test_no_notification_without_requirements(self, app, organiser, coordinator, staff):
        review.approve_event(submitted_and_assigned(organiser, coordinator), coordinator)
        assert inbox(staff["tech"]) == []

    def test_changed_requirements_are_notified(self, app, organiser, coordinator, staff):
        event = new_event(organiser, "planning", coordinator)
        update_service.update_event_fields(
            event, db.session.get(User, coordinator),
            {"equipment_requirements": [{"type": "Speaker", "quantity": 2}]},
            offline_review_confirmed=True,
        )
        [n] = inbox(staff["tech"], TYPE_NEW_EQUIPMENT_REQUEST)
        assert n.data["kind"] == "updated" and "2 × Speaker" in n.message


# ===========================================================================
# ISP-108 — Attendees
# ===========================================================================
@pytest.fixture()
def attendees(make_user):
    return [make_user(f"att{i}@test.com", ["attendee"], name=f"Attendee {i}") for i in range(1, 6)]


def public_event(organiser, coordinator, capacity=1, **fields):
    return new_event(organiser, "confirmed", coordinator, registration_required=True,
                     intended_capacity=capacity, proposed_date=(utcnow() + timedelta(days=30)).date(),
                     **fields)


def open_event(organiser, coordinator, capacity=1, **fields):
    event = public_event(organiser, coordinator, capacity=capacity, **fields)
    registrations.open_registration(event.id, organiser)
    return event


def count_all():
    return Notification.query.count()


def status_pair(notification):
    return notification.data["oldStatus"], notification.data["newStatus"]


# ===========================================================================
# AC1  Opted-in Attendee: registration opens or closes
# ===========================================================================
class TestISP108AC1RegistrationOpensOrCloses:
    def test_opted_in_attendee_is_notified_when_registration_opens(self, app, organiser, coordinator, attendees):
        event = public_event(organiser, coordinator)
        registrations.set_following(event.id, attendees[0], True)

        registrations.open_registration(event.id, organiser)

        [n] = inbox(attendees[0])
        assert n.type == TYPE_REGISTRATION_CHANGE
        assert n.title == "Registration open"
        assert "Gala Night" in n.message and "open" in n.message  # event name + new status
        assert n.data["registrationOpen"] is True

    def test_opted_in_attendee_is_notified_when_registration_closes(self, app, organiser, coordinator, attendees):
        event = open_event(organiser, coordinator)
        registrations.set_following(event.id, attendees[0], True)

        registrations.close_registration(event.id, organiser)

        [n] = inbox(attendees[0])
        assert n.title == "Registration closed"
        assert "Gala Night" in n.message and "closed" in n.message
        assert n.data["registrationOpen"] is False

        event = public_event(organiser, coordinator)
        registrations.set_following(event.id, attendees[0], True)

        registrations.open_registration(event.id, organiser)

        [n] = inbox(attendees[0])
        assert n.is_read is False
        assert n.event_id == event.id and n.link == f"/attendee/events/{event.id}"

    def test_attendee_who_did_not_opt_in_hears_nothing(self, app, organiser, coordinator, attendees):
        event = public_event(organiser, coordinator)

        registrations.open_registration(event.id, organiser)
        registrations.close_registration(event.id, organiser)

        assert count_all() == 0


# ===========================================================================
# AC2  Status changes: one notification with old status, new status, event name
# ===========================================================================
class TestISP108AC2StatusChanges:
    def test_waitlisted_to_registered(self, app, organiser, coordinator, attendees):
        event = open_event(organiser, coordinator, capacity=1)
        holder = registrations.register(event.id, attendees[0])
        registrations.join_waitlist(event.id, attendees[1])

        registrations.withdraw(holder.id, attendees[0])

        [n] = inbox(attendees[1])
        assert status_pair(n) == ("waitlisted", "registered")
        assert 'from Waiting list to Registered' in n.message and "Gala Night" in n.message

    def test_registered_to_withdrawn(self, app, organiser, coordinator, attendees):
        event = open_event(organiser, coordinator, capacity=3)
        mine = registrations.register(event.id, attendees[0])

        registrations.withdraw(mine.id, attendees[0])

        [n] = inbox(attendees[0])
        assert status_pair(n) == ("registered", "withdrawn")
        assert "from Registered to Withdrawn" in n.message and "Gala Night" in n.message

        event = open_event(organiser, coordinator, capacity=1)
        registrations.register(event.id, attendees[0])
        waiting = registrations.join_waitlist(event.id, attendees[1])

        registrations.withdraw(waiting.id, attendees[1])

        [n] = inbox(attendees[1])
        assert status_pair(n) == ("waitlisted", "withdrawn")
        assert "from Waiting list to Withdrawn" in n.message

    def test_registered_to_cancelled_when_the_event_is_cancelled(self, app, organiser, coordinator, attendees):
        event = open_event(organiser, coordinator, capacity=3)
        registrations.register(event.id, attendees[0])

        status.cancel_event(event.id, coordinator, "The venue flooded overnight.")

        [n] = inbox(attendees[0])
        assert status_pair(n) == ("registered", "cancelled")
        assert "from Registered to Cancelled" in n.message and "Gala Night" in n.message
        assert "The venue flooded overnight." in n.message

        event = open_event(organiser, coordinator, capacity=1)
        registrations.register(event.id, attendees[0])
        registrations.join_waitlist(event.id, attendees[1])

        status.cancel_event(event.id, coordinator, "No longer going ahead.")

        assert status_pair(inbox(attendees[1])[0]) == ("waitlisted", "cancelled")

    def test_one_notification_per_change_with_no_duplicates(self, app, organiser, coordinator, attendees):
        event = open_event(organiser, coordinator, capacity=1)
        holder = registrations.register(event.id, attendees[0])
        registrations.join_waitlist(event.id, attendees[1])

        registrations.withdraw(holder.id, attendees[0])

        assert len(inbox(attendees[0])) == 1 and len(inbox(attendees[1])) == 1
        # reading the event again must not repeat the promotion notice
        registrations.get_event(event.id, attendees[1])
        registrations.my_registrations(attendees[1])
        assert len(inbox(attendees[1])) == 1


# ===========================================================================
# AC3  A place is released: only the first Attendee on the waiting list is told
# ===========================================================================
class TestISP108AC3OnlyTheFirstWaitingAttendeeIsNotified:
    def test_first_in_waiting_list_order_is_notified_and_nobody_else(self, app, organiser, coordinator, attendees):
        event = open_event(organiser, coordinator, capacity=1)
        holder = registrations.register(event.id, attendees[0])
        registrations.join_waitlist(event.id, attendees[1])
        registrations.join_waitlist(event.id, attendees[2])
        registrations.join_waitlist(event.id, attendees[3])

        registrations.withdraw(holder.id, attendees[0])

        [promoted] = inbox(attendees[1])
        assert promoted.title == "A place is available for you"
        assert status_pair(promoted) == ("waitlisted", "registered")
        assert inbox(attendees[2]) == [] and inbox(attendees[3]) == []

    def test_two_places_free_notifies_exactly_the_first_two_in_order(self, app, organiser, coordinator, attendees):
        event = open_event(organiser, coordinator, capacity=1)
        registrations.register(event.id, attendees[0])
        for attendee in attendees[1:4]:
            registrations.join_waitlist(event.id, attendee)

        event.intended_capacity = 3  # two more places
        db.session.commit()
        registrations.get_event(event.id, attendees[4])

        assert len(inbox(attendees[1])) == 1 and len(inbox(attendees[2])) == 1
        assert inbox(attendees[3]) == []
        assert inbox(attendees[1])[0].id < inbox(attendees[2])[0].id  # told in queue order


# ===========================================================================
# AC4  Only Attendees affected by the event are notified
# ===========================================================================
class TestISP108AC4OnlyAffectedAttendees:
    def test_cancelling_one_event_does_not_notify_attendees_of_another(self, app, organiser, coordinator, attendees):
        event = open_event(organiser, coordinator, capacity=5, name="Gala Night")
        other = open_event(organiser, coordinator, capacity=5, name="Quiz Night")
        registrations.register(event.id, attendees[0])
        registrations.register(other.id, attendees[1])

        status.cancel_event(event.id, coordinator, "Cancelled for testing.")

        assert len(inbox(attendees[0])) == 1
        assert inbox(attendees[1]) == []

    def test_cancellation_reaches_registered_and_waitlisted_but_not_withdrawn(self, app, organiser, coordinator, attendees):
        event = open_event(organiser, coordinator, capacity=1)
        registrations.register(event.id, attendees[0])
        registrations.join_waitlist(event.id, attendees[1])
        gone = registrations.join_waitlist(event.id, attendees[2])
        registrations.withdraw(gone.id, attendees[2])
        before = len(inbox(attendees[2]))  # their own withdrawal confirmation

        status.cancel_event(event.id, coordinator, "Cancelled for testing.")

        assert len(inbox(attendees[0])) == 1 and len(inbox(attendees[1])) == 1
        assert len(inbox(attendees[2])) == before  # already withdrawn: not affected any more
        assert inbox(attendees[3]) == [] and inbox(attendees[4]) == []

# ---------------------------------------------------------------------------
# The same notifications seen through the API (what the Attendee actually sees)
# ---------------------------------------------------------------------------
class TestISP108AttendeeInbox:
    def test_the_attendee_lists_their_own_promotion_notice(self, app, client, auth_header, organiser, coordinator, attendees):
        event = open_event(organiser, coordinator, capacity=1)
        holder = registrations.register(event.id, attendees[0])
        registrations.join_waitlist(event.id, attendees[1])
        registrations.withdraw(holder.id, attendees[0])

        listed = client.get("/api/notifications", headers=auth_header("att2@test.com")).get_json()

        assert len(listed) == 1
        assert listed[0]["isRead"] is False and "Gala Night" in listed[0]["message"]
        assert client.get("/api/notifications/unread-count", headers=auth_header("att2@test.com")).get_json()["count"] == 1

    def test_another_attendee_cannot_see_or_mark_it_read(self, app, client, auth_header, organiser, coordinator, attendees):
        event = open_event(organiser, coordinator, capacity=1)
        holder = registrations.register(event.id, attendees[0])
        registrations.join_waitlist(event.id, attendees[1])
        registrations.withdraw(holder.id, attendees[0])
        promoted = inbox(attendees[1])[0]

        stranger = auth_header("att3@test.com")

        assert client.get("/api/notifications", headers=stranger).get_json() == []
        assert client.post(f"/api/notifications/{promoted.id}/read", headers=stranger).status_code in (403, 404)
        assert Notification.query.get(promoted.id).is_read is False

    def test_opening_it_marks_it_read_and_the_unread_count_drops(self, app, client, auth_header, organiser, coordinator, attendees):
        event = public_event(organiser, coordinator)
        registrations.set_following(event.id, attendees[0], True)
        registrations.open_registration(event.id, organiser)
        headers = auth_header("att1@test.com")
        [n] = client.get("/api/notifications", headers=headers).get_json()

        client.post(f"/api/notifications/{n['id']}/read", headers=headers)

        assert client.get("/api/notifications/unread-count", headers=headers).get_json()["count"] == 0
        assert len(client.get("/api/notifications", headers=headers).get_json()) == 1  # still viewable


class TestISP108Following:
    def test_follow_toggle_api(self, app, client, auth_header, organiser, coordinator, attendees):
        event = public_event(organiser, coordinator)
        headers = auth_header("att1@test.com")
        assert client.post(f"/api/registrations/events/{event.id}/follow", headers=headers) \
            .get_json()["followingUpdates"] is True
        assert client.delete(f"/api/registrations/events/{event.id}/follow", headers=headers) \
            .get_json()["followingUpdates"] is False

# ===========================================================================
# ISP-130 — Safety Officer
# ===========================================================================
class TestISP130SafetyOfficer:
        # ---- AC1
    def test_ac1_only_safety_officers_are_notified(self, app, organiser, coordinator, staff):
        event = ready_event(organiser, coordinator, staff["venue1"])
        status.change_status(event, "safety_check", coordinator)
        for user_id in (organiser, coordinator, staff["tech"], staff["lead1"],
                        staff["venue1"], staff["coord_b"]):
            assert inbox(user_id, TYPE_SAFETY_CHECK) == []

    def test_ac1_inactive_officer_is_not_notified(self, app, organiser, coordinator, staff):
        db.session.get(User, staff["safety1"]).is_active = False
        db.session.commit()
        event = ready_event(organiser, coordinator, staff["venue1"])
        status.change_status(event, "safety_check", coordinator)
        assert inbox(staff["safety1"], TYPE_SAFETY_CHECK) == []
        assert len(inbox(staff["safety2"], TYPE_SAFETY_CHECK)) == 1

    def test_ac1_real_trigger_notifies_when_arrangements_complete(self, app, organiser, coordinator, staff):
        event = ready_event(organiser, coordinator, staff["venue1"])
        status.try_advance_to_safety_check(event, coordinator)
        assert event.status == "safety_check"
        for officer in ("safety1", "safety2"):
            assert len(inbox(staff[officer], TYPE_SAFETY_CHECK)) == 1

    def test_ac1_expired_or_released_hold_does_not_block(self, app, organiser, coordinator, staff):
        event = ready_event(organiser, coordinator, staff["venue1"])
        venue = Venue(name="Annex", capacity=100, created_by=staff["venue1"])
        db.session.add(venue)
        db.session.flush()
        for state in ("expired", "released"):
            db.session.add(VenueBooking(event_id=event.id, venue_id=venue.id, requested_by=coordinator,
                                        status=state, start_datetime=utcnow() + timedelta(days=10),
                                        end_datetime=utcnow() + timedelta(days=10, hours=3)))
        db.session.commit()
        status.try_advance_to_safety_check(event, coordinator)
        assert event.status == "safety_check"
        assert len(inbox(staff["safety1"], TYPE_SAFETY_CHECK)) == 1


    def test_ac1_ac2_ac4_every_officer_once_with_details(self, app, organiser, coordinator, staff):
        event = ready_event(organiser, coordinator, staff["venue1"])
        status.change_status(event, "safety_check", coordinator)

        for officer in ("safety1", "safety2"):
            [n] = inbox(staff[officer], TYPE_SAFETY_CHECK)  # exactly one each, even with two roles
            assert n.title == "Safety check required" and n.data["recheck"] is False
            for text in ("Gala Night", "19:00", "Expected attendance: 120"):
                assert text in n.message
            assert n.link == f"/safety-reviews/{event.id}"

 # ---- AC2
    def test_ac2_message_has_venue_date_time_and_attendance(self, app, organiser, coordinator, staff):
        event = ready_event(organiser, coordinator, staff["venue1"])
        status.change_status(event, "safety_check", coordinator)
        [n] = inbox(staff["safety1"], TYPE_SAFETY_CHECK)
        for text in ("Gala Night", "Grand Hall", FUTURE.strftime("%b %Y"), "19:00", "Expected attendance: 120"):
            assert text in n.message
        assert n.link == f"/safety-reviews/{event.id}"



    def test_ac3_unread_until_opened_then_still_viewable(self, app, client, auth_header, organiser, coordinator, staff):
        event = ready_event(organiser, coordinator, staff["venue1"])
        status.change_status(event, "safety_check", coordinator)
        headers = auth_header("safety1@test.com")
        [n] = client.get("/api/notifications", headers=headers).get_json()
        assert n["isRead"] is False and n["createdAt"]
        assert client.get("/api/notifications/unread-count", headers=headers).get_json()["count"] == 1
        client.post(f"/api/notifications/{n['id']}/read", headers=headers)
        assert client.get("/api/notifications/unread-count", headers=headers).get_json()["count"] == 0
        assert len(client.get("/api/notifications", headers=headers).get_json()) == 1

  # ---- AC3
    def test_ac3_notification_remains_after_the_officer_decides(self, app, organiser, coordinator, staff):
        event = ready_event(organiser, coordinator, staff["venue1"])
        status.change_status(event, "safety_check", coordinator)
        safety.review_safety_check(event, db.session.get(User, staff["safety1"]), "approved",
                                   assessed_factors=list(safety.SAFETY_FACTOR_ORDER))
        assert len(inbox(staff["safety1"], TYPE_SAFETY_CHECK)) == 1


     # ---- AC4
    def test_ac4_officer_who_is_also_the_coordinator_gets_one(self, app, organiser, staff):
        event = ready_event(organiser, staff["safety2"], staff["venue1"])
        status.change_status(event, "safety_check", staff["safety2"])
        assert len(inbox(staff["safety2"], TYPE_SAFETY_CHECK)) == 1

    def test_ac4_repeated_advance_does_not_notify_twice(self, app, organiser, coordinator, staff):
        event = ready_event(organiser, coordinator, staff["venue1"])
        status.try_advance_to_safety_check(event, coordinator)
        status.try_advance_to_safety_check(event, coordinator)
        assert len(inbox(staff["safety1"], TYPE_SAFETY_CHECK)) == 1


    # ---- AC5
    def test_ac5_changes_requested_also_triggers_recheck(self, app, organiser, coordinator, staff):
        event = ready_event(organiser, coordinator, staff["venue1"])
        status.change_status(event, "safety_check", coordinator)
        safety.review_safety_check(
            event, db.session.get(User, staff["safety1"]), "changes_requested",
            comments="The exit is blocked by staging.", assessed_factors=["emergency_access"],
            concern_factors=["emergency_access"], affected_arrangements=["venue"])
        status.change_status(event, "safety_check", coordinator)
        assert [n.data["recheck"] for n in inbox(staff["safety1"], TYPE_SAFETY_CHECK)] == [False, True]

    def _approve_and_confirm(self, event, staff, coordinator):
        safety.review_safety_check(event, db.session.get(User, staff["safety1"]), "approved",
                                   assessed_factors=list(safety.SAFETY_FACTOR_ORDER))
        status.confirm_after_safety_approval(
            event, status.approved_safety_review_for_current_check(event), coordinator)
        assert event.status == "confirmed"

    def test_ac5_reentry_after_confirmed_event_changes_is_a_recheck(self, app, organiser, coordinator, staff):
        event = ready_event(organiser, coordinator, staff["venue1"])
        status.change_status(event, "safety_check", coordinator)
        self._approve_and_confirm(event, staff, coordinator)
        status.revert_to_planning(event, coordinator, "Attendance increased")
        status.try_advance_to_safety_check(event, coordinator)
        notices = inbox(staff["safety1"], TYPE_SAFETY_CHECK)
        assert [n.data["recheck"] for n in notices] == [False, True]
        assert notices[1].title == "Safety re-check required"

    def test_ac5_officer_can_decide_the_recheck_and_stale_approval_cannot_confirm(
        self, app, client, auth_header, organiser, coordinator, staff
    ):
        event = ready_event(organiser, coordinator, staff["venue1"])
        status.change_status(event, "safety_check", coordinator)
        self._approve_and_confirm(event, staff, coordinator)
        status.revert_to_planning(event, coordinator, "Attendance increased")
        status.try_advance_to_safety_check(event, coordinator)

        res = client.post(f"/api/events/{event.id}/confirm", headers=auth_header("coordinator@test.com"))
        assert res.status_code == 400 and event.status == "safety_check"

        safety.review_safety_check(event, db.session.get(User, staff["safety1"]), "approved",
                                   assessed_factors=list(safety.SAFETY_FACTOR_ORDER))  # must not raise
        assert status.approved_safety_review_for_current_check(event) is not None


    def test_ac5_re_entry_after_rework_is_a_recheck(self, app, organiser, coordinator, staff):
        event = ready_event(organiser, coordinator, staff["venue1"])
        status.change_status(event, "safety_check", coordinator)
        safety.review_safety_check(
            event, db.session.get(User, staff["safety1"]), "rejected",
            comments="Crowd flow plan is not adequate.", assessed_factors=["crowd_movement"],
            concern_factors=["crowd_movement"], affected_arrangements=["venue", "equipment"],
        )
        status.change_status(event, "safety_check", coordinator)

        notices = inbox(staff["safety1"], TYPE_SAFETY_CHECK)
        assert [n.data["recheck"] for n in notices] == [False, True]
        assert notices[1].title == "Safety re-check required"


# ---- AC6
    def test_ac6_direct_entry_blocked_while_booking_pending(self, app, organiser, coordinator, staff):
        event = new_event(organiser, "planning", coordinator)
        venue = Venue(name="Hall", capacity=300, created_by=staff["venue1"])
        db.session.add(venue)
        db.session.flush()
        db.session.add(VenueBooking(event_id=event.id, venue_id=venue.id, requested_by=coordinator,
                                    status="pending", start_datetime=utcnow() + timedelta(days=10),
                                    end_datetime=utcnow() + timedelta(days=10, hours=3)))
        db.session.commit()
        with pytest.raises(status.InvalidTransitionError):
            status.change_status(event, "safety_check", coordinator)
        assert event.status == "planning"
        assert Notification.query.filter_by(type=TYPE_SAFETY_CHECK).count() == 0

    def test_ac6_status_endpoint_cannot_bypass_the_guard(self, app, client, auth_header, organiser, coordinator, staff):
        event = new_event(organiser, "planning", coordinator)  # no approved venue yet
        res = client.post(f"/api/events/{event.id}/status", headers=auth_header("coordinator@test.com"),
                          json={"status": "safety_check"})
        assert res.status_code == 400
        assert Notification.query.filter_by(type=TYPE_SAFETY_CHECK).count() == 0

    def test_ac6_unreserved_equipment_blocks_notification(self, app, organiser, coordinator, staff):
        event = ready_event(organiser, coordinator, staff["venue1"])
        event.equipment_requirements.append(EventEquipmentRequirement(equipment_type="Projector", quantity=2))
        db.session.commit()
        status.try_advance_to_safety_check(event, coordinator)
        assert event.status == "planning"
        assert Notification.query.filter_by(type=TYPE_SAFETY_CHECK).count() == 0

    def test_ac6_no_notification_in_earlier_stages(self, app, organiser, coordinator, staff):
        event = submitted_and_assigned(organiser, coordinator)
        review.approve_event(event, coordinator)  # submitted -> under_review -> approved -> planning
        assert Notification.query.filter_by(type=TYPE_SAFETY_CHECK).count() == 0


    def test_ac6_no_notification_while_arrangements_are_pending(self, app, organiser, coordinator, staff):
        event = new_event(organiser, "planning", coordinator)
        venue = Venue(name="Hall", capacity=300, created_by=staff["venue1"])
        db.session.add(venue)
        db.session.flush()
        db.session.add(VenueBooking(event_id=event.id, venue_id=venue.id, requested_by=coordinator,
                                    status="pending", start_datetime=utcnow() + timedelta(days=10),
                                    end_datetime=utcnow() + timedelta(days=10, hours=3)))
        db.session.commit()

        status.try_advance_to_safety_check(event, coordinator)

        assert event.status == "planning"
        assert Notification.query.filter_by(type=TYPE_SAFETY_CHECK).count() == 0
