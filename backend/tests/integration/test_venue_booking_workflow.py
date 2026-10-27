
from datetime import timedelta

from app.common.time import utcnow
from app.extensions import db
from app.models.notification import TYPE_NEW_VENUE_BOOKING_REQUEST
from app.models.venue import Venue, VenueBooking
from app.venues.services.booking import expire_due_holds


def test_multi_venue_submission_routes_requests_and_notifications(
    client, organiser, make_user, make_event, auth_header
):
    # 1. Create an Event Coordinator and two Venue Staff members.
    coordinator_id = make_user(
        "integration-coordinator@test.com",
        ["event_coordinator"],
    )
    staff_a_id = make_user(
        "integration-venue-a@test.com",
        ["venue_staff"],
    )
    staff_b_id = make_user(
        "integration-venue-b@test.com",
        ["venue_staff"],
    )

    coordinator_headers = auth_header("integration-coordinator@test.com")
    staff_a_headers = auth_header("integration-venue-a@test.com")
    staff_b_headers = auth_header("integration-venue-b@test.com")

    # 2. Create an event and two venues with different owners.
    event_id = make_event(
        organiser,
        status="planning",
        coordinator_id=coordinator_id,
        name="Integration Conference",
    )

    venue_a = Venue(
        name="Integration Hall A",
        location="North Campus",
        capacity=200,
        created_by=staff_a_id,
    )
    venue_b = Venue(
        name="Integration Hall B",
        location="South Campus",
        capacity=150,
        created_by=staff_b_id,
    )

    db.session.add_all([venue_a, venue_b])
    db.session.commit()

    booking_date = (utcnow().date() + timedelta(days=30)).isoformat()

    # 3. Coordinator submits one request for both venues.
    response = client.post(
        "/api/venues/bookings",
        headers=coordinator_headers,
        json={
            "eventId": event_id,
            "venues": [
                {
                    "venueId": venue_a.id,
                    "date": booking_date,
                    "startTime": "09:00",
                    "endTime": "12:00",
                },
                {
                    "venueId": venue_b.id,
                    "date": booking_date,
                    "startTime": "13:00",
                    "endTime": "16:00",
                },
            ],
        },
    )

    assert response.status_code == 201, response.get_json()

    bookings = {
        item["venueId"]: item
        for item in response.get_json()
    }

    assert set(bookings) == {venue_a.id, venue_b.id}
    assert all(item["status"] == "pending" for item in bookings.values())

    booking_a_id = bookings[venue_a.id]["id"]
    booking_b_id = bookings[venue_b.id]["id"]

    # 4. Verify that both booking records were persisted.
    db.session.expire_all()

    assert db.session.get(VenueBooking, booking_a_id).event_id == event_id
    assert db.session.get(VenueBooking, booking_b_id).event_id == event_id

    # 5. Each Venue Staff member sees only their own pending request.
    queue_a_response = client.get(
        "/api/venues/bookings/pending",
        headers=staff_a_headers,
    )
    queue_b_response = client.get(
        "/api/venues/bookings/pending",
        headers=staff_b_headers,
    )

    assert queue_a_response.status_code == 200
    assert queue_b_response.status_code == 200

    assert {
        item["id"] for item in queue_a_response.get_json()
    } == {booking_a_id}

    assert {
        item["id"] for item in queue_b_response.get_json()
    } == {booking_b_id}

    # 6. Retrieve each Venue Staff member's notification inbox.
    notifications_a_response = client.get(
        "/api/notifications",
        headers=staff_a_headers,
    )
    notifications_b_response = client.get(
        "/api/notifications",
        headers=staff_b_headers,
    )

    assert notifications_a_response.status_code == 200
    assert notifications_b_response.status_code == 200

    notifications_a = [
        item for item in notifications_a_response.get_json()
        if item["type"] == TYPE_NEW_VENUE_BOOKING_REQUEST
    ]
    notifications_b = [
        item for item in notifications_b_response.get_json()
        if item["type"] == TYPE_NEW_VENUE_BOOKING_REQUEST
    ]

    # Exactly one notification per responsible staff member.
    assert len(notifications_a) == 1
    assert len(notifications_b) == 1

    notification_a = notifications_a[0]
    notification_b = notifications_b[0]

    # 7. Verify notification details and booking-specific links.
    assert notification_a["data"]["venueName"] == "Integration Hall A"
    assert notification_b["data"]["venueName"] == "Integration Hall B"

    assert notification_a["data"]["eventName"] == "Integration Conference"
    assert notification_b["data"]["eventName"] == "Integration Conference"

    assert booking_date in notification_a["data"]["bookingDate"] or (
        utcnow().date() + timedelta(days=30)
    ).strftime("%b %Y") in notification_a["data"]["bookingDate"]

    assert booking_date in notification_b["data"]["bookingDate"] or (
        utcnow().date() + timedelta(days=30)
    ).strftime("%b %Y") in notification_b["data"]["bookingDate"]

    assert notification_a["link"] == (
        f"/venues/approval?booking={booking_a_id}"
    )
    assert notification_b["link"] == (
        f"/venues/approval?booking={booking_b_id}"
    )

    assert notification_a["data"]["bookingId"] == booking_a_id
    assert notification_b["data"]["bookingId"] == booking_b_id


def test_booking_approval_updates_coordinator_status_and_calendar(
    client, organiser, make_user, make_event, auth_header
):
    # 1. Create Coordinator and Venue Staff accounts.
    coordinator_id = make_user(
        "integration-approval-coord@test.com",
        ["event_coordinator"],
    )
    staff_id = make_user(
        "integration-approval-staff@test.com",
        ["venue_staff"],
    )

    coordinator_headers = auth_header(
        "integration-approval-coord@test.com"
    )
    staff_headers = auth_header(
        "integration-approval-staff@test.com"
    )

    # 2. Create an event and venue owned by the Venue Staff member.
    event_id = make_event(
        organiser,
        coordinator_id=coordinator_id,
    )

    venue = Venue(
        name="Integration Approval Hall",
        location="Main Campus",
        capacity=200,
        created_by=staff_id,
    )

    db.session.add(venue)
    db.session.commit()

    booking_date = utcnow().date() + timedelta(days=30)

    # 3. Coordinator submits a venue booking request.
    submit_response = client.post(
        "/api/venues/bookings",
        headers=coordinator_headers,
        json={
            "eventId": event_id,
            "venues": [
                {
                    "venueId": venue.id,
                    "date": booking_date.isoformat(),
                    "startTime": "10:00",
                    "endTime": "12:00",
                }
            ],
        },
    )

    assert submit_response.status_code == 201, submit_response.get_json()

    booking = submit_response.get_json()[0]
    booking_id = booking["id"]
    assert booking["status"] == "pending"

    # 4. Confirm the request appears in the owner's pending queue.
    pending_response = client.get(
        "/api/venues/bookings/pending",
        headers=staff_headers,
    )

    assert pending_response.status_code == 200
    assert booking_id in {
        item["id"] for item in pending_response.get_json()
    }

    # 5. Venue Staff approves the request.
    approve_response = client.post(
        f"/api/venues/bookings/{booking_id}/approve",
        headers=staff_headers,
    )

    assert approve_response.status_code == 200
    assert approve_response.get_json()["status"] == "approved"

    # 6. Verify approval was persisted in the database.
    db.session.expire_all()

    saved = db.session.get(VenueBooking, booking_id)

    assert saved.status == "approved"
    assert saved.decided_by == staff_id
    assert saved.decided_at is not None

    # 7. Approved booking disappears from the pending queue.
    pending_after = client.get(
        "/api/venues/bookings/pending",
        headers=staff_headers,
    )

    assert pending_after.status_code == 200
    assert booking_id not in {
        item["id"] for item in pending_after.get_json()
    }

    # 8. Coordinator sees the updated booking status.
    coordinator_response = client.get(
        "/api/venues/bookings/my",
        headers=coordinator_headers,
    )

    assert coordinator_response.status_code == 200

    coordinator_booking = next(
        item for item in coordinator_response.get_json()
        if item["id"] == booking_id
    )

    assert coordinator_booking["status"] == "approved"
    assert coordinator_booking["venueId"] == venue.id

    # 9. Approved booking appears on the venue calendar.
    calendar_response = client.get(
        f"/api/venues/{venue.id}/calendar",
        headers=staff_headers,
        query_string={
            "start": booking_date.isoformat() + "T00:00:00",
            "end": (
                booking_date + timedelta(days=1)
            ).isoformat() + "T00:00:00",
        },
    )

    assert calendar_response.status_code == 200

    confirmed = calendar_response.get_json()["confirmedBookings"]

    calendar_booking = next(
        item for item in confirmed
        if item["id"] == booking_id
    )

    assert calendar_booking["eventId"] == event_id
    assert calendar_booking["startDatetime"] == (
        booking_date.isoformat() + "T10:00:00"
    )
    assert calendar_booking["endDatetime"] == (
        booking_date.isoformat() + "T12:00:00"
    )


def test_rejection_and_resubmission_to_different_venue_staff(
    client, organiser, make_user, make_event, auth_header
):
    # 1. Create a Coordinator and two Venue Staff members.
    coordinator_id = make_user(
        "integration-resubmit-coord@test.com",
        ["event_coordinator"],
    )
    staff_a_id = make_user(
        "integration-resubmit-staff-a@test.com",
        ["venue_staff"],
    )
    staff_b_id = make_user(
        "integration-resubmit-staff-b@test.com",
        ["venue_staff"],
    )

    coordinator_headers = auth_header(
        "integration-resubmit-coord@test.com"
    )
    staff_a_headers = auth_header(
        "integration-resubmit-staff-a@test.com"
    )
    staff_b_headers = auth_header(
        "integration-resubmit-staff-b@test.com"
    )

    # 2. Create an event and two venues with different owners.
    event_id = make_event(
        organiser,
        coordinator_id=coordinator_id,
    )

    venue_a = Venue(
        name="Integration Resubmit Hall A",
        location="East Campus",
        capacity=200,
        created_by=staff_a_id,
    )
    venue_b = Venue(
        name="Integration Resubmit Hall B",
        location="West Campus",
        capacity=150,
        created_by=staff_b_id,
    )

    db.session.add_all([venue_a, venue_b])
    db.session.commit()

    booking_date = (utcnow().date() + timedelta(days=30)).isoformat()

    # 3. Coordinator submits the original request for Venue A.
    original_response = client.post(
        "/api/venues/bookings",
        headers=coordinator_headers,
        json={
            "eventId": event_id,
            "venues": [
                {
                    "venueId": venue_a.id,
                    "date": booking_date,
                    "startTime": "10:00",
                    "endTime": "12:00",
                }
            ],
        },
    )

    assert original_response.status_code == 201, original_response.get_json()
    original_id = original_response.get_json()[0]["id"]

    # 4. Venue A's owner rejects the booking with a suggestion.
    reject_response = client.post(
        f"/api/venues/bookings/{original_id}/reject",
        headers=staff_a_headers,
        json={
            "reason": "Venue unavailable",
            "alternativeSuggestion": "Try Hall B instead",
        },
    )

    assert reject_response.status_code == 200
    assert reject_response.get_json()["status"] == "rejected"

    # 5. Coordinator sees the rejection and suggestion.
    status_response = client.get(
        "/api/venues/bookings/my",
        headers=coordinator_headers,
    )

    assert status_response.status_code == 200

    original_status = next(
        item for item in status_response.get_json()
        if item["id"] == original_id
    )

    assert original_status["status"] == "rejected"
    assert original_status["decisionReason"] == "Venue unavailable"
    assert original_status["alternativeSuggestion"] == "Try Hall B instead"

    # 6. Coordinator submits a new request for Venue B.
    resubmit_response = client.post(
        "/api/venues/bookings",
        headers=coordinator_headers,
        json={
            "eventId": event_id,
            "venues": [
                {
                    "venueId": venue_b.id,
                    "date": booking_date,
                    "startTime": "14:00",
                    "endTime": "16:00",
                    "equipment": "Projector",
                }
            ],
        },
    )

    assert resubmit_response.status_code == 201, resubmit_response.get_json()

    new_booking = resubmit_response.get_json()[0]
    new_id = new_booking["id"]

    assert new_id != original_id
    assert new_booking["status"] == "pending"
    assert new_booking["venueId"] == venue_b.id

    # 7. Verify that the original rejection remains unchanged.
    db.session.expire_all()

    original_saved = db.session.get(VenueBooking, original_id)
    new_saved = db.session.get(VenueBooking, new_id)

    assert original_saved.status == "rejected"
    assert original_saved.venue_id == venue_a.id
    assert original_saved.decision_reason == "Venue unavailable"
    assert original_saved.alternative_suggestion == "Try Hall B instead"

    assert new_saved.status == "pending"
    assert new_saved.venue_id == venue_b.id
    assert new_saved.equipment == "Projector"

    # 8. Only Venue B's owner sees the new pending request.
    queue_a = client.get(
        "/api/venues/bookings/pending",
        headers=staff_a_headers,
    )
    queue_b = client.get(
        "/api/venues/bookings/pending",
        headers=staff_b_headers,
    )

    assert queue_a.status_code == 200
    assert queue_b.status_code == 200

    assert new_id not in {
        item["id"] for item in queue_a.get_json()
    }
    assert new_id in {
        item["id"] for item in queue_b.get_json()
    }

    # The rejected request must not remain in Venue A's pending queue.
    assert original_id not in {
        item["id"] for item in queue_a.get_json()
    }

    # 9. Coordinator's event booking history contains both records.
    history_response = client.get(
        f"/api/venues/events/{event_id}/bookings",
        headers=coordinator_headers,
    )

    assert history_response.status_code == 200

    history = {
        item["id"]: item
        for item in history_response.get_json()
    }

    assert original_id in history
    assert new_id in history

    assert history[original_id]["status"] == "rejected"
    assert history[original_id]["decisionReason"] == "Venue unavailable"
    assert history[new_id]["status"] == "pending"


def test_withdrawal_updates_status_and_removes_staff_pending_request(
    client, organiser, make_user, make_event, auth_header
):
    # 1. Create a Coordinator and Venue Staff member.
    coordinator_id = make_user(
        "integration-withdraw-coord@test.com",
        ["event_coordinator"],
    )
    staff_id = make_user(
        "integration-withdraw-staff@test.com",
        ["venue_staff"],
    )

    coordinator_headers = auth_header(
        "integration-withdraw-coord@test.com"
    )
    staff_headers = auth_header(
        "integration-withdraw-staff@test.com"
    )

    # 2. Create an event and a venue owned by the staff member.
    event_id = make_event(
        organiser,
        coordinator_id=coordinator_id,
    )

    venue = Venue(
        name="Integration Withdrawal Hall",
        location="Main Campus",
        capacity=100,
        created_by=staff_id,
    )

    db.session.add(venue)
    db.session.commit()

    booking_date = (utcnow().date() + timedelta(days=30)).isoformat()

    # 3. Coordinator submits a booking request.
    submit_response = client.post(
        "/api/venues/bookings",
        headers=coordinator_headers,
        json={
            "eventId": event_id,
            "venues": [
                {
                    "venueId": venue.id,
                    "date": booking_date,
                    "startTime": "10:00",
                    "endTime": "12:00",
                }
            ],
        },
    )

    assert submit_response.status_code == 201, submit_response.get_json()

    booking_id = submit_response.get_json()[0]["id"]

    # 4. Verify the booking is initially pending.
    pending_before = client.get(
        "/api/venues/bookings/pending",
        headers=staff_headers,
    )

    assert pending_before.status_code == 200
    assert booking_id in {
        item["id"] for item in pending_before.get_json()
    }

    # 5. Coordinator withdraws the pending booking.
    withdraw_response = client.post(
        f"/api/venues/bookings/{booking_id}/withdraw",
        headers=coordinator_headers,
    )

    assert withdraw_response.status_code == 200
    assert withdraw_response.get_json()["status"] == "withdrawn"

    # 6. Verify the withdrawal is persisted in the database.
    db.session.expire_all()

    saved_booking = db.session.get(VenueBooking, booking_id)

    assert saved_booking is not None
    assert saved_booking.status == "withdrawn"

    # 7. Withdrawn booking disappears from the staff pending queue.
    pending_after = client.get(
        "/api/venues/bookings/pending",
        headers=staff_headers,
    )

    assert pending_after.status_code == 200
    assert booking_id not in {
        item["id"] for item in pending_after.get_json()
    }

    # 8. Coordinator can still see the booking with withdrawn status.
    my_bookings_response = client.get(
        "/api/venues/bookings/my",
        headers=coordinator_headers,
    )

    assert my_bookings_response.status_code == 200

    coordinator_booking = next(
        item for item in my_bookings_response.get_json()
        if item["id"] == booking_id
    )

    assert coordinator_booking["status"] == "withdrawn"
    assert coordinator_booking["venueId"] == venue.id

    # 9. Verify withdrawal is reflected in booking history.
    history_response = client.get(
        f"/api/venues/events/{event_id}/bookings",
        headers=coordinator_headers,
    )

    assert history_response.status_code == 200

    history_booking = next(
        item for item in history_response.get_json()
        if item["id"] == booking_id
    )

    assert history_booking["status"] == "withdrawn"


def test_tentative_hold_lifecycle_blocks_conflicts_and_releases_booking(
    client, organiser, make_user, make_event, auth_header
):
    # 1. Create a Coordinator and responsible Venue Staff member.
    coordinator_id = make_user(
        "integration-hold-coord@test.com",
        ["event_coordinator"],
    )
    staff_id = make_user(
        "integration-hold-staff@test.com",
        ["venue_staff"],
    )

    coordinator_headers = auth_header(
        "integration-hold-coord@test.com"
    )
    staff_headers = auth_header(
        "integration-hold-staff@test.com"
    )

    event_id = make_event(
        organiser,
        coordinator_id=coordinator_id,
    )

    venue = Venue(
        name="Integration Hold Hall",
        location="Main Campus",
        capacity=200,
        created_by=staff_id,
    )
    db.session.add(venue)
    db.session.commit()

    booking_date = (utcnow().date() + timedelta(days=30)).isoformat()

    def submit_booking():
        response = client.post(
            "/api/venues/bookings",
            headers=coordinator_headers,
            json={
                "eventId": event_id,
                "venues": [{
                    "venueId": venue.id,
                    "date": booking_date,
                    "startTime": "10:00",
                    "endTime": "12:00",
                }],
            },
        )
        assert response.status_code == 201, response.get_json()
        return response.get_json()[0]["id"]

    # 2. Submit a booking through the real API.
    booking_id = submit_booking()

    # 3. Staff places a tentative hold.
    first_expiry = (
        utcnow() + timedelta(hours=48)
    ).replace(microsecond=0)

    hold_response = client.post(
        f"/api/venues/bookings/{booking_id}/hold",
        headers=staff_headers,
        json={"expiresAt": first_expiry.isoformat() + "Z"},
    )

    assert hold_response.status_code == 200, hold_response.get_json()
    assert hold_response.get_json()["status"] == "held"

    db.session.expire_all()
    saved = db.session.get(VenueBooking, booking_id)

    assert saved.status == "held"
    assert saved.hold_expires_at == first_expiry

    # 4. Held booking remains visible in the staff queue.
    queue_response = client.get(
        "/api/venues/bookings/pending",
        headers=staff_headers,
    )

    assert queue_response.status_code == 200

    held_booking = next(
        item for item in queue_response.get_json()
        if item["id"] == booking_id
    )

    assert held_booking["status"] == "held"
    assert held_booking["holdExpiresAt"] is not None

    # 5. Staff extends the hold.
    extended_expiry = (
        utcnow() + timedelta(hours=96)
    ).replace(microsecond=0)

    extend_response = client.post(
        f"/api/venues/bookings/{booking_id}/hold/extend",
        headers=staff_headers,
        json={"expiresAt": extended_expiry.isoformat() + "Z"},
    )

    assert extend_response.status_code == 200, extend_response.get_json()

    db.session.expire_all()
    saved = db.session.get(VenueBooking, booking_id)

    assert saved.status == "held"
    assert saved.hold_expires_at == extended_expiry

    # 6. A second Coordinator request overlaps the held time.
    # Use a separate event to avoid the one-active-booking rule.
    other_coordinator_id = make_user(
        "integration-hold-other-coord@test.com",
        ["event_coordinator"],
    )
    other_event_id = make_event(
        organiser,
        coordinator_id=other_coordinator_id,
    )

    conflict_response = client.post(
        "/api/venues/bookings",
        headers=auth_header("integration-hold-other-coord@test.com"),
        json={
            "eventId": other_event_id,
            "venues": [{
                "venueId": venue.id,
                "date": booking_date,
                "startTime": "11:00",
                "endTime": "13:00",
            }],
        },
    )

    assert conflict_response.status_code == 201, conflict_response.get_json()
    conflicting_id = conflict_response.get_json()[0]["id"]

    # 7. Overlapping approval is blocked while the hold is active.
    blocked_response = client.post(
        f"/api/venues/bookings/{conflicting_id}/approve",
        headers=staff_headers,
    )

    assert blocked_response.status_code == 409, blocked_response.get_json()

    db.session.expire_all()
    assert db.session.get(VenueBooking, conflicting_id).status == "pending"

    # 8. Staff releases the original hold.
    release_response = client.post(
        f"/api/venues/bookings/{booking_id}/hold/release",
        headers=staff_headers,
        json={},
    )

    assert release_response.status_code == 200, release_response.get_json()

    db.session.expire_all()
    released = db.session.get(VenueBooking, booking_id)

    assert released.status == "released"
    assert released.hold_released_at is not None

    # 9. The conflicting booking can now be approved.
    approve_response = client.post(
        f"/api/venues/bookings/{conflicting_id}/approve",
        headers=staff_headers,
    )

    assert approve_response.status_code == 200, approve_response.get_json()
    assert approve_response.get_json()["status"] == "approved"

    db.session.expire_all()
    assert db.session.get(VenueBooking, conflicting_id).status == "approved"
