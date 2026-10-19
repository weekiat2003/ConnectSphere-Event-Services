from datetime import datetime, time, timedelta
from types import SimpleNamespace

import pytest

from app.common.time import utcnow
from app.extensions import db
from app.models.venue import Venue, VenueBooking


BASE = "/api/venues"
TODAY = utcnow().date()


def day(offset):
    return TODAY + timedelta(days=offset)


def at(d, hour):
    return datetime.combine(d, time(hour, 0))


# --------------------------------------------------------------------------
# Fixtures and helpers
# --------------------------------------------------------------------------

@pytest.fixture()
def make_venue(app):
    def _make(name, staff_id):
        venue = Venue(
            name=name,
            location="Test Location",
            capacity=100,
            created_by=staff_id,
        )
        db.session.add(venue)
        db.session.commit()
        return venue.id

    return _make


@pytest.fixture()
def ctx(client, organiser, make_user, make_event, make_venue, auth_header):
    coord_id = make_user(
        "coord@test.com",
        ["event_coordinator"],
    )

    staff_id = make_user(
        "staff@test.com",
        ["venue_staff"],
    )

    return SimpleNamespace(
        coord_id=coord_id,
        staff_id=staff_id,
        coord=auth_header("coord@test.com"),
        staff=auth_header("staff@test.com"),
        event_id=make_event(
            organiser,
            coordinator_id=coord_id,
        ),
        hall_a=make_venue("Hall A", staff_id),
        hall_b=make_venue("Hall B", staff_id),
    )


def entry(venue_id, **overrides):
    """One venue's booking request JSON."""

    data = {
        "venueId": venue_id,
        "date": day(30).isoformat(),
        "startTime": "10:00",
        "endTime": "12:00",
    }

    data.update(overrides)
    return data


def submit(client, ctx, venues):
    return client.post(
        f"{BASE}/bookings",
        json={
            "eventId": ctx.event_id,
            "venues": venues,
        },
        headers=ctx.coord,
    )


def all_bookings():
    # Read what the API committed.
    db.session.rollback()

    return VenueBooking.query.order_by(
        VenueBooking.id
    ).all()


def add_booking(ctx, venue_id, status):
    db.session.add(
        VenueBooking(
            event_id=ctx.event_id,
            venue_id=venue_id,
            status=status,
            requested_by=ctx.coord_id,
            start_datetime=at(day(30), 10),
            end_datetime=at(day(30), 12),
        )
    )

    db.session.commit()


def error_pairs(res):
    return {
        (e["venue"], e["field"])
        for e in res.get_json()["errors"]
    }


# --------------------------------------------------------------------------
# AC1:
# One request can contain several venues.
# Each venue has its own timing and creates its own pending booking.
# --------------------------------------------------------------------------

def test_ac1_request_with_several_venues_creates_a_linked_pending_booking_per_venue(
    client,
    ctx,
):
    d1 = day(30)
    d2 = day(31)

    res = submit(
        client,
        ctx,
        [
            entry(
                ctx.hall_a,
                date=d1.isoformat(),
                startTime="09:00",
                endTime="17:00",
            ),
            entry(
                ctx.hall_b,
                date=d2.isoformat(),
                startTime="13:00",
                endTime="15:00",
            ),
        ],
    )

    assert res.status_code == 201

    by_venue = {
        booking["venueId"]: booking
        for booking in res.get_json()
    }

    assert set(by_venue) == {
        ctx.hall_a,
        ctx.hall_b,
    }

    assert all(
        booking["eventId"] == ctx.event_id
        and booking["status"] == "pending"
        for booking in by_venue.values()
    )

    assert (
        by_venue[ctx.hall_a]["startDatetime"]
        == at(d1, 9).isoformat()
    )

    assert (
        by_venue[ctx.hall_a]["endDatetime"]
        == at(d1, 17).isoformat()
    )

    assert (
        by_venue[ctx.hall_b]["startDatetime"]
        == at(d2, 13).isoformat()
    )

    assert (
        by_venue[ctx.hall_b]["endDatetime"]
        == at(d2, 15).isoformat()
    )

    # Each venue should be a separate pending booking
    # that Venue Staff can review.
    pending = client.get(
        f"{BASE}/bookings/pending",
        headers=ctx.staff,
    ).get_json()

    assert sorted(
        booking["venueId"]
        for booking in pending
    ) == sorted(
        [
            ctx.hall_a,
            ctx.hall_b,
        ]
    )


# --------------------------------------------------------------------------
# AC2:
# At least one venue is required.
# Every venue requires date, start time and end time.
# --------------------------------------------------------------------------

def test_ac2_request_without_a_venue_is_rejected(
    client,
    ctx,
):
    res = submit(
        client,
        ctx,
        [],
    )

    assert res.status_code == 400

    assert [
        error["field"]
        for error in res.get_json()["errors"]
    ] == ["venues"]

    assert all_bookings() == []


def test_ac2_missing_date_or_times_names_the_venue_and_fields(
    client,
    ctx,
):
    res = submit(
        client,
        ctx,
        [
            entry(ctx.hall_a),
            entry(
                ctx.hall_b,
                date=None,
                startTime=None,
                endTime=None,
            ),
        ],
    )

    assert res.status_code == 400

    assert error_pairs(res) == {
        ("Hall B", "date"),
        ("Hall B", "start_time"),
        ("Hall B", "end_time"),
    }

    # Hall A must not be saved either.
    # The whole request is all-or-nothing.
    assert all_bookings() == []


# --------------------------------------------------------------------------
# AC3:
# End time must be after start time.
# Booking date cannot be in the past.
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "end",
    [
        "10:00",
        "09:30",
    ],
)
def test_ac3_end_same_as_or_before_start_is_rejected(
    client,
    ctx,
    end,
):
    res = submit(
        client,
        ctx,
        [
            entry(ctx.hall_a),
            entry(
                ctx.hall_b,
                endTime=end,
            ),
        ],
    )

    assert res.status_code == 400

    assert error_pairs(res) == {
        ("Hall B", "end_time"),
    }

    assert (
        "after the start time"
        in res.get_json()["errors"][0]["message"]
    )

    assert all_bookings() == []


def test_ac3_date_in_the_past_is_rejected(
    client,
    ctx,
):
    res = submit(
        client,
        ctx,
        [
            entry(
                ctx.hall_a,
                date=day(-1).isoformat(),
            )
        ],
    )

    assert res.status_code == 400

    assert error_pairs(res) == {
        ("Hall A", "date"),
    }

    assert (
        "in the past"
        in res.get_json()["errors"][0]["message"]
    )

    assert all_bookings() == []


# --------------------------------------------------------------------------
# AC4:
# A booking may end on the following day.
# --------------------------------------------------------------------------

def test_ac4_end_time_on_the_next_day_is_accepted_with_the_correct_end(
    client,
    ctx,
):
    d = day(30)
    next_day = d + timedelta(days=1)

    res = submit(
        client,
        ctx,
        [
            entry(
                ctx.hall_a,
                startTime="22:00",
                endTime="02:00",
                endDate=next_day.isoformat(),
            )
        ],
    )

    assert res.status_code == 201

    pending = client.get(
        f"{BASE}/bookings/pending",
        headers=ctx.staff,
    ).get_json()[0]

    assert (
        pending["startDatetime"]
        == at(d, 22).isoformat()
    )

    assert (
        pending["endDatetime"]
        == at(next_day, 2).isoformat()
    )

# --------------------------------------------------------------------------
# AC5:
# One active (pending/approved) request
# per venue per event.
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "existing_status",
    [
        "pending",
        "approved",
    ],
)
def test_ac6_venue_with_an_active_booking_is_blocked_and_named(
    client,
    ctx,
    existing_status,
):
    add_booking(
        ctx,
        ctx.hall_a,
        existing_status,
    )

    res = submit(
        client,
        ctx,
        [
            entry(ctx.hall_a),
            entry(ctx.hall_b),
        ],
    )

    assert res.status_code == 400

    assert error_pairs(res) == {
        ("Hall A", "venue_id"),
    }

    assert (
        "already has an active booking"
        in res.get_json()["errors"][0]["message"]
    )

    # Only the booking created before the request should exist.
    # Nothing from the failed request should be saved.
    assert len(all_bookings()) == 1


@pytest.mark.parametrize(
    "old_status",
    [
        "rejected",
        "withdrawn",
    ],
)
def test_ac6_venue_can_be_included_again_after_reject_or_withdraw(
    client,
    ctx,
    old_status,
):
    add_booking(
        ctx,
        ctx.hall_a,
        old_status,
    )

    res = submit(
        client,
        ctx,
        [
            entry(ctx.hall_a),
        ],
    )

    assert res.status_code == 201

    assert [
        booking.status
        for booking in all_bookings()
    ] == [
        old_status,
        "pending",
    ]


# --------------------------------------------------------------------------
# User Story: View Status of a Submitted Booking Request
# --------------------------------------------------------------------------


# AC1:
# Given a submitted booking request, when I view it,
# then its current status is shown.

def test_status_ac1_submitted_booking_shows_current_status(client, ctx):
    res = submit(client, ctx, [entry(ctx.hall_a)])
    assert res.status_code == 201

    booking_id = res.get_json()[0]["id"]

    status_res = client.get(
        f"{BASE}/bookings/my",
        headers=ctx.coord,
    )

    assert status_res.status_code == 200

    bookings = status_res.get_json()
    booking = next(b for b in bookings if b["id"] == booking_id)

    assert "status" in booking
    assert booking["status"] == "pending"


# AC2:
# Given I have submitted a request that Venue Staff have not yet
# decided on, when I view it, then its status shows as "Pending".

def test_status_ac2_undecided_booking_shows_pending(client, ctx):
    res = submit(client, ctx, [entry(ctx.hall_a)])
    assert res.status_code == 201

    status_res = client.get(
        f"{BASE}/bookings/my",
        headers=ctx.coord,
    )

    assert status_res.status_code == 200
    assert status_res.get_json()[0]["status"] == "pending"


# AC3:
# Given Venue Staff have approved my request,
# when I view it, then its status shows as "Approved".

def test_status_ac3_approved_booking_shows_approved(client, ctx):
    res = submit(client, ctx, [entry(ctx.hall_a)])
    assert res.status_code == 201

    booking_id = res.get_json()[0]["id"]

    approve_res = client.post(
        f"{BASE}/bookings/{booking_id}/approve",
        headers=ctx.staff,
    )

    assert approve_res.status_code == 200

    status_res = client.get(
        f"{BASE}/bookings/my",
        headers=ctx.coord,
    )

    assert status_res.status_code == 200
    assert status_res.get_json()[0]["status"] == "approved"


# AC4:
# Given Venue Staff have rejected my request,
# when I view it, then its status shows as "Rejected".

def test_status_ac4_rejected_booking_shows_rejected(client, ctx):
    res = submit(client, ctx, [entry(ctx.hall_a)])
    assert res.status_code == 201

    booking_id = res.get_json()[0]["id"]

    reject_res = client.post(
        f"{BASE}/bookings/{booking_id}/reject",
        headers=ctx.staff,
        json={"reason": "Venue unavailable"},
    )

    assert reject_res.status_code == 200

    status_res = client.get(
        f"{BASE}/bookings/my",
        headers=ctx.coord,
    )

    assert status_res.status_code == 200

    booking = status_res.get_json()[0]

    assert booking["status"] == "rejected"
    assert booking["decisionReason"] == "Venue unavailable"


# AC5:
# Given Venue Staff have just made a decision on my request,
# when I open or refresh the request, then I see the updated
# status and not the old one.

def test_status_ac5_refresh_shows_updated_status(client, ctx):
    res = submit(client, ctx, [entry(ctx.hall_a)])
    assert res.status_code == 201

    booking_id = res.get_json()[0]["id"]

    # First view: booking is pending.
    first_res = client.get(
        f"{BASE}/bookings/my",
        headers=ctx.coord,
    )

    assert first_res.status_code == 200
    assert first_res.get_json()[0]["status"] == "pending"

    # Venue Staff approves the booking.
    approve_res = client.post(
        f"{BASE}/bookings/{booking_id}/approve",
        headers=ctx.staff,
    )

    assert approve_res.status_code == 200

    # Second view: simulates reopening or refreshing the page.
    refreshed_res = client.get(
        f"{BASE}/bookings/my",
        headers=ctx.coord,
    )

    assert refreshed_res.status_code == 200
    assert refreshed_res.get_json()[0]["status"] == "approved"
    assert refreshed_res.get_json()[0]["status"] != "pending"


# AC6:
# Given I am viewing a submitted request, when the page loads,
# then I see the status together with the venue, date and time
# I requested, so I know which request the status belongs to.

def test_status_ac6_booking_shows_venue_date_and_time(client, ctx):
    requested_date = day(30)

    res = submit(
        client,
        ctx,
        [
            entry(
                ctx.hall_a,
                date=requested_date.isoformat(),
                startTime="09:00",
                endTime="17:00",
            )
        ],
    )

    assert res.status_code == 201

    booking_id = res.get_json()[0]["id"]

    status_res = client.get(
        f"{BASE}/bookings/my",
        headers=ctx.coord,
    )

    assert status_res.status_code == 200

    booking = next(
        b for b in status_res.get_json()
        if b["id"] == booking_id
    )

    assert booking["venueId"] == ctx.hall_a
    assert booking["venueName"] == "Hall A"
    assert booking["status"] == "pending"

    assert booking["startDatetime"] == at(
        requested_date, 9
    ).isoformat()

    assert booking["endDatetime"] == at(
        requested_date, 17
    ).isoformat()



# AC7:
# Given I am viewing a submitted request, when the system fails
# to load its status, then I see an error message instead of
# a blank or outdated status.

def test_status_ac7_failed_request_returns_error(
    app,
    client,
    ctx,
    monkeypatch,
):
    from flask_sqlalchemy.query import Query

    def fail_query(self, *args, **kwargs):
        raise RuntimeError("Database unavailable")

    # Simulate database failure.
    monkeypatch.setattr(
        Query,
        "filter_by",
        fail_query,
    )

    # Prevent Flask from propagating the exception to pytest.
    # Instead, return an HTTP 500 response.
    with app.test_request_context():
        original_propagate = app.config.get("PROPAGATE_EXCEPTIONS")
        app.config["PROPAGATE_EXCEPTIONS"] = False

        try:
            res = client.get(
                f"{BASE}/bookings/my",
                headers=ctx.coord,
            )

            assert res.status_code == 500

        finally:
            app.config["PROPAGATE_EXCEPTIONS"] = original_propagate


# --------------------------------------------------------------------------
# User Story: Withdraw a Pending Venue Booking Request
# --------------------------------------------------------------------------


# AC1:
# Given a pending booking request, when I withdraw it,
# then it no longer appears in Venue Staff's pending queue
# and its status reflects the withdrawal.

def test_withdraw_ac1_pending_booking_removed_from_staff_queue(client, ctx):
    res = submit(client, ctx, [entry(ctx.hall_a)])
    assert res.status_code == 201

    booking_id = res.get_json()[0]["id"]

    withdraw_res = client.post(
        f"{BASE}/bookings/{booking_id}/withdraw",
        headers=ctx.coord,
    )

    assert withdraw_res.status_code == 200
    assert withdraw_res.get_json()["status"] == "withdrawn"

    # Check that Venue Staff can no longer see it in the pending queue.
    pending_res = client.get(
        f"{BASE}/bookings/pending",
        headers=ctx.staff,
    )

    assert pending_res.status_code == 200
    assert booking_id not in [
        booking["id"] for booking in pending_res.get_json()
    ]

    # Coordinator should still see the request with withdrawn status.
    my_res = client.get(
        f"{BASE}/bookings/my",
        headers=ctx.coord,
    )

    assert my_res.status_code == 200

    booking = next(
        b for b in my_res.get_json()
        if b["id"] == booking_id
    )

    assert booking["status"] == "withdrawn"


# AC2:
# Given I have a pending request, when I choose to withdraw it,
# then I am asked to confirm first.

# This is a frontend acceptance criterion.
# The backend test verifies that simply viewing the request
# does not withdraw it. The confirmation dialog itself
# must be tested in Vue.

def test_withdraw_ac2_viewing_booking_does_not_withdraw(client, ctx):
    res = submit(client, ctx, [entry(ctx.hall_a)])
    assert res.status_code == 201

    booking_id = res.get_json()[0]["id"]

    view_res = client.get(
        f"{BASE}/bookings/my",
        headers=ctx.coord,
    )

    assert view_res.status_code == 200

    booking = next(
        b for b in view_res.get_json()
        if b["id"] == booking_id
    )

    assert booking["status"] == "pending"

    db.session.expire_all()
    record = db.session.get(VenueBooking, booking_id)

    assert record.status == "pending"


# AC3:
# Given my request has already been approved or rejected,
# when I view it, then the withdraw option is not available.

# Button visibility must be tested in Vue.
# This backend test verifies that withdrawal is rejected
# for both approved and rejected bookings.

@pytest.mark.parametrize(
    "status",
    ["approved", "rejected"],
)
def test_withdraw_ac3_decided_booking_cannot_be_withdrawn(
    client,
    ctx,
    status,
):
    add_booking(ctx, ctx.hall_a, status)

    booking_id = all_bookings()[0].id

    withdraw_res = client.post(
        f"{BASE}/bookings/{booking_id}/withdraw",
        headers=ctx.coord,
    )

    assert withdraw_res.status_code == 400

    db.session.expire_all()
    record = db.session.get(VenueBooking, booking_id)

    assert record.status == status


# AC4:
# Given Venue Staff approve or reject my request just before
# I confirm the withdrawal, when I confirm, then the withdrawal
# is not applied and I am told the request has already been decided.

@pytest.mark.parametrize(
    "decision, expected_status",
    [
        ("approve", "approved"),
        ("reject", "rejected"),
    ],
)
def test_withdraw_ac4_staff_decision_before_confirmation(
    client,
    ctx,
    decision,
    expected_status,
):
    res = submit(client, ctx, [entry(ctx.hall_a)])
    assert res.status_code == 201

    booking_id = res.get_json()[0]["id"]

    # Venue Staff decides before the coordinator confirms withdrawal.
    decision_res = client.post(
        f"{BASE}/bookings/{booking_id}/{decision}",
        headers=ctx.staff,
        json={"reason": "Staff decision"},
    )

    assert decision_res.status_code == 200

    # Coordinator now tries to withdraw the same booking.
    withdraw_res = client.post(
        f"{BASE}/bookings/{booking_id}/withdraw",
        headers=ctx.coord,
    )

    assert withdraw_res.status_code == 400
    assert "pending" in withdraw_res.get_json()["error"].lower() \
        or "decided" in withdraw_res.get_json()["error"].lower()

    db.session.expire_all()
    record = db.session.get(VenueBooking, booking_id)

    assert record.status == expected_status


# AC5:
# Given I confirm a withdrawal, when the system fails to process it,
# then I am told it did not go through and the request stays pending
# in Venue Staff's queue.

def test_withdraw_ac5_failed_withdrawal_keeps_booking_pending(
    client,
    ctx,
    monkeypatch,
):
    from app.venues.services import booking as booking_service

    res = submit(client, ctx, [entry(ctx.hall_a)])
    assert res.status_code == 201

    booking_id = res.get_json()[0]["id"]

    # Simulate a withdrawal service failure.
    def fail_withdrawal(record, user_id):
        raise ValueError("Withdrawal could not be processed")

    with monkeypatch.context() as patch:
        patch.setattr(
            booking_service,
            "withdraw_booking_request",
            fail_withdrawal,
        )

        withdraw_res = client.post(
            f"{BASE}/bookings/{booking_id}/withdraw",
            headers=ctx.coord,
        )

    assert withdraw_res.status_code == 400
    assert "error" in withdraw_res.get_json()
    assert "could not be processed" in withdraw_res.get_json()["error"]

    # The booking must remain pending.
    db.session.expire_all()
    record = db.session.get(VenueBooking, booking_id)

    assert record.status == "pending"

    # Venue Staff should still see the booking.
    pending_res = client.get(
        f"{BASE}/bookings/pending",
        headers=ctx.staff,
    )

    assert pending_res.status_code == 200
    assert booking_id in [
        booking["id"] for booking in pending_res.get_json()
    ]


# AC6:
# Given a booking request for an event I am not coordinating,
# when I view it, then the withdraw button is not shown to me.

# Button visibility is tested in Vue.
# This backend test verifies that a different coordinator
# cannot withdraw someone else's booking.

def test_withdraw_ac6_other_coordinator_cannot_withdraw(
    client,
    ctx,
    make_user,
    auth_header,
):
    res = submit(client, ctx, [entry(ctx.hall_a)])
    assert res.status_code == 201

    booking_id = res.get_json()[0]["id"]

    make_user(
        "other-withdraw-coord@test.com",
        ["event_coordinator"],
    )

    other_coord = auth_header("other-withdraw-coord@test.com")

    withdraw_res = client.post(
        f"{BASE}/bookings/{booking_id}/withdraw",
        headers=other_coord,
    )

    assert withdraw_res.status_code == 400
    assert "not authorised" in withdraw_res.get_json()["error"].lower()

    db.session.expire_all()
    record = db.session.get(VenueBooking, booking_id)

    assert record.status == "pending"

    # Other coordinator should not see this booking in their list.
    my_res = client.get(
        f"{BASE}/bookings/my",
        headers=other_coord,
    )

    assert my_res.status_code == 200
    assert all(
        b["id"] != booking_id
        for b in my_res.get_json()
    )

# --------------------------------------------------------------------------
# User Story: Block a booking request when the venue has a confirmed
# booking for another event at an overlapping time
# --------------------------------------------------------------------------

@pytest.fixture()
def other_event_id(organiser, make_event, ctx):
    """A second event, coordinated by the same Coordinator."""
    return make_event(organiser, coordinator_id=ctx.coord_id)


def add_other_booking(ctx, event_id, venue_id, status="approved",
                      start=None, end=None):
    """A booking for a given event, defaulting to day(30) 10:00-12:00."""
    db.session.add(
        VenueBooking(
            event_id=event_id,
            venue_id=venue_id,
            status=status,
            requested_by=ctx.coord_id,
            start_datetime=start or at(day(30), 10),
            end_datetime=end or at(day(30), 12),
        )
    )
    db.session.commit()


def set_padding(venue_id, setup=0, turnaround=0):
    venue = db.session.get(Venue, venue_id)
    venue.setup_minutes = setup
    venue.turnaround_minutes = turnaround
    db.session.commit()

# Double booking
# AC1: overlap with another event's approved booking is blocked, and the
# message names the venue, the conflicting date and the time period.

def test_conflict_ac1_overlapping_confirmed_booking_blocks_request(
    client, ctx, other_event_id,
):
    add_other_booking(ctx, other_event_id, ctx.hall_a)

    res = submit(client, ctx, [entry(ctx.hall_a, startTime="11:00", endTime="13:00")])

    assert res.status_code == 400
    assert error_pairs(res) == {("Hall A", "venue_id")}

    message = res.get_json()["errors"][0]["message"]
    assert "Hall A" in message
    assert "unavailable" in message
    assert day(30).isoformat() in message
    assert "10:00 to 12:00" in message

    # Only the pre-existing approved booking exists; nothing was saved.
    assert len(all_bookings()) == 1


@pytest.mark.parametrize(
    "start, end",
    [
        ("09:00", "11:00"),   # overlaps the start
        ("11:00", "13:00"),   # overlaps the end
        ("10:30", "11:30"),   # inside the existing booking
        ("09:00", "13:00"),   # contains the existing booking
        ("10:00", "12:00"),   # identical period
    ],
)
def test_conflict_ac1_every_kind_of_overlap_is_blocked(
    client, ctx, other_event_id, start, end,
):
    add_other_booking(ctx, other_event_id, ctx.hall_a)

    res = submit(client, ctx, [entry(ctx.hall_a, startTime=start, endTime=end)])

    assert res.status_code == 400
    assert error_pairs(res) == {("Hall A", "venue_id")}
    assert "unavailable" in res.get_json()["errors"][0]["message"]
    assert len(all_bookings()) == 1


# AC2: bookings that merely touch, or that do not overlap, are allowed.

@pytest.mark.parametrize(
    "booking_date, start, end",
    [
        (30, "12:00", "14:00"),   # starts exactly when the other ends
        (30, "08:00", "10:00"),   # ends exactly when the other starts
        (30, "14:00", "16:00"),   # later the same day
        (31, "10:00", "12:00"),   # same hours, next day
    ],
)
def test_conflict_ac2_non_overlapping_request_is_accepted(
    client, ctx, other_event_id, booking_date, start, end,
):
    add_other_booking(ctx, other_event_id, ctx.hall_a)

    res = submit(
        client, ctx,
        [entry(ctx.hall_a, date=day(booking_date).isoformat(),
               startTime=start, endTime=end)],
    )

    assert res.status_code == 201
    assert len(all_bookings()) == 2


def test_conflict_ac2_other_venue_is_not_affected(client, ctx, other_event_id):
    add_other_booking(ctx, other_event_id, ctx.hall_a)

    res = submit(client, ctx, [entry(ctx.hall_b)])  # same time, different venue

    assert res.status_code == 201


# AC3: only APPROVED bookings block. Pending, rejected, withdrawn and
# cancelled bookings of other events do not.

@pytest.mark.parametrize(
    "other_status",
    ["pending", "rejected", "withdrawn", "cancelled"],
)
def test_conflict_ac3_only_approved_bookings_block(
    client, ctx, other_event_id, other_status,
):
    add_other_booking(ctx, other_event_id, ctx.hall_a, status=other_status)

    res = submit(client, ctx, [entry(ctx.hall_a)])

    assert res.status_code == 201


# AC4: setup and turnaround time count as part of the overlap.

def test_conflict_ac4_setup_time_makes_adjacent_request_conflict(
    client, ctx, other_event_id,
):
    set_padding(ctx.hall_a, setup=30)
    add_other_booking(ctx, other_event_id, ctx.hall_a)  # 10:00-12:00

    # Requested 12:00-14:00 needs the venue from 11:30, inside the other booking.
    res = submit(client, ctx, [entry(ctx.hall_a, startTime="12:00", endTime="14:00")])

    assert res.status_code == 400
    assert error_pairs(res) == {("Hall A", "venue_id")}
    assert "unavailable" in res.get_json()["errors"][0]["message"]


def test_conflict_ac4_turnaround_time_blocks_until_it_has_passed(
    client, ctx, other_event_id,
):
    set_padding(ctx.hall_a, turnaround=30)
    add_other_booking(ctx, other_event_id, ctx.hall_a)  # busy until 12:30

    blocked = submit(client, ctx, [entry(ctx.hall_a, startTime="12:15", endTime="14:00")])
    assert blocked.status_code == 400
    assert error_pairs(blocked) == {("Hall A", "venue_id")}

    allowed = submit(client, ctx, [entry(ctx.hall_a, startTime="12:30", endTime="14:00")])
    assert allowed.status_code == 201


# AC5: the message handles bookings that span midnight.

def test_conflict_ac5_message_shows_full_period_for_overnight_booking(
    client, ctx, other_event_id,
):
    start = at(day(30), 22)
    end = at(day(31), 2)
    add_other_booking(ctx, other_event_id, ctx.hall_a, start=start, end=end)

    res = submit(
        client, ctx,
        [entry(ctx.hall_a, date=day(31).isoformat(), startTime="01:00", endTime="03:00")],
    )

    assert res.status_code == 400
    message = res.get_json()["errors"][0]["message"]
    assert f"{day(30).isoformat()} 22:00" in message
    assert f"{day(31).isoformat()} 02:00" in message


# AC6: the request is all-or-nothing and every conflict is reported.

def test_conflict_ac6_one_conflicting_venue_saves_nothing(
    client, ctx, other_event_id,
):
    add_other_booking(ctx, other_event_id, ctx.hall_a)

    res = submit(client, ctx, [entry(ctx.hall_a), entry(ctx.hall_b)])

    assert res.status_code == 400
    assert error_pairs(res) == {("Hall A", "venue_id")}  # Hall B is fine
    assert len(all_bookings()) == 1                      # only the pre-existing one


def test_conflict_ac6_all_conflicting_venues_are_reported(
    client, ctx, other_event_id,
):
    add_other_booking(ctx, other_event_id, ctx.hall_a)
    add_other_booking(ctx, other_event_id, ctx.hall_b)

    res = submit(client, ctx, [entry(ctx.hall_a), entry(ctx.hall_b)])

    assert res.status_code == 400
    assert error_pairs(res) == {("Hall A", "venue_id"), ("Hall B", "venue_id")}


# AC7: the event's own bookings are not "another event", and the conflict
# message takes priority over the generic active-booking message.

def test_conflict_ac7_own_approved_booking_gives_active_booking_message(
    client, ctx,
):
    add_booking(ctx, ctx.hall_a, "approved")  # same event, 10:00-12:00

    res = submit(client, ctx, [entry(ctx.hall_a)])

    assert res.status_code == 400
    message = res.get_json()["errors"][0]["message"]
    assert "already has an active booking" in message
    assert "unavailable" not in message


def test_conflict_ac7_conflict_message_wins_over_active_booking_message(
    client, ctx, other_event_id,
):
    # This event already has a pending request for Hall A on another day...
    add_booking(ctx, ctx.hall_a, "pending")
    # ...and another event holds an approved booking at the requested time.
    add_other_booking(
        ctx, other_event_id, ctx.hall_a,
        start=at(day(40), 10), end=at(day(40), 12),
    )

    res = submit(client, ctx, [entry(ctx.hall_a, date=day(40).isoformat())])

    assert res.status_code == 400
    errors = res.get_json()["errors"]
    assert len(errors) == 1  # one venue_id error per venue
    assert "unavailable" in errors[0]["message"]
    assert "already has an active booking" not in errors[0]["message"]

# Booking advisory

def _mine(client, ctx, event_id):
    res = client.get(f"{BASE}/bookings/my", headers=ctx.coord).get_json()
    return next(b for b in res if b["eventId"] == event_id)


def test_advisory_ac1_ac2_pending_overlap_warns_without_other_event_details(client, ctx, other_event_id):
    add_other_booking(ctx, other_event_id, ctx.hall_a, status="pending")
    res = submit(client, ctx, [entry(ctx.hall_a, startTime="11:00", endTime="13:00")])
    assert res.status_code == 201
    booking = res.get_json()[0]
    assert booking["status"] == "pending"
    adv = booking["advisory"]
    assert adv["type"] == "possible_conflict" and adv["overlapCount"] == 1
    assert "Hall A" in adv["message"] and "not guaranteed" in adv["message"]
    assert "11:00 to 12:00" in adv["message"]
    assert "@" not in adv["message"] and "Event" not in adv["message"]


def test_advisory_ac4_no_warning_cases(client, ctx, other_event_id):
    add_other_booking(ctx, other_event_id, ctx.hall_a, status="pending")
    # different venue, and non-overlapping time
    res = submit(client, ctx, [entry(ctx.hall_b),
                               entry(ctx.hall_a, startTime="14:00", endTime="15:00")])
    assert all(b["advisory"] is None for b in res.get_json())


@pytest.mark.parametrize("status", ["rejected", "withdrawn"])
def test_advisory_ac4_inactive_overlaps_ignored(client, ctx, other_event_id, status):
    add_other_booking(ctx, other_event_id, ctx.hall_a, status=status)
    assert submit(client, ctx, [entry(ctx.hall_a)]).get_json()[0]["advisory"] is None


def test_advisory_ac5_ac6_earlier_request_warned_then_cleared(client, ctx, other_event_id):
    add_other_booking(ctx, other_event_id, ctx.hall_a, status="pending")
    new_id = submit(client, ctx, [entry(ctx.hall_a)]).get_json()[0]["id"]

    assert _mine(client, ctx, other_event_id)["advisory"]["overlapCount"] == 1

    client.post(f"{BASE}/bookings/{new_id}/withdraw", headers=ctx.coord)
    assert _mine(client, ctx, other_event_id)["advisory"] is None


def test_advisory_ac7_confirmed_overlap_replaces_warning_and_blocks_approval(client, ctx, other_event_id):
    add_other_booking(ctx, other_event_id, ctx.hall_a, status="pending")
    new_id = submit(client, ctx, [entry(ctx.hall_a)]).get_json()[0]["id"]
    other_id = next(b.id for b in all_bookings() if b.event_id == other_event_id)

    assert client.post(f"{BASE}/bookings/{other_id}/approve", headers=ctx.staff).status_code == 200

    adv = _mine(client, ctx, ctx.event_id)["advisory"]
    assert adv["type"] == "venue_confirmed"
    assert "confirmed for another event" in adv["message"]
    assert client.post(f"{BASE}/bookings/{new_id}/approve", headers=ctx.staff).status_code == 409

    pending = client.get(f"{BASE}/bookings/pending", headers=ctx.staff).get_json()
    assert next(b for b in pending if b["id"] == new_id)["canApprove"] is False