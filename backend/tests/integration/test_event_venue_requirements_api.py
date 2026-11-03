from datetime import datetime, timedelta

import pytest

from app.common.time import utcnow
from app.extensions import db
from app.models.venue import Venue, VenueBooking


def _venue(name="Main Hall", location="North Campus", capacity=150, created_by=None):
    venue = Venue(name=name, location=location, capacity=capacity, created_by=created_by)
    db.session.add(venue)
    db.session.commit()
    return venue


def _booking(event_id, venue, requested_by, status="approved",
             start=datetime(2026, 12, 1, 9), end=datetime(2026, 12, 1, 12), **extra):
    booking = VenueBooking(
        event_id=event_id, venue_id=venue.id, requested_by=requested_by,
        status=status, start_datetime=start, end_datetime=end, **extra,
    )
    db.session.add(booking)
    db.session.commit()
    return booking


def _get(client, auth_header, event_id, email="coordinator@test.com"):
    res = client.get(f"/api/events/{event_id}", headers=auth_header(email))
    assert res.status_code == 200, res.get_json()
    return res.get_json()


def test_event_detail_includes_venue_name_location_and_capacity(
    client, auth_header, organiser, coordinator, make_event
):
    event_id = make_event(organiser, status="planning", coordinator_id=coordinator)
    venue = _venue()
    booking = _booking(event_id, venue, coordinator)

    [row] = _get(client, auth_header, event_id)["venueBookings"]

    assert row["id"] == booking.id
    assert row["venueId"] == venue.id
    assert row["venueName"] == "Main Hall"
    assert row["venueLocation"] == "North Campus"
    assert row["venueCapacity"] == 150
    assert row["status"] == "approved"
    assert row["startDatetime"] == "2026-12-01T09:00:00"
    assert row["endDatetime"] == "2026-12-01T12:00:00"


def test_venue_without_location_returns_null_not_an_error(
    client, auth_header, organiser, coordinator, make_event
):
    event_id = make_event(organiser, status="planning", coordinator_id=coordinator)
    _booking(event_id, _venue(location=None), coordinator)

    [row] = _get(client, auth_header, event_id)["venueBookings"]

    assert row["venueLocation"] is None
    assert row["venueName"] == "Main Hall"


def test_event_with_no_bookings_returns_empty_list(
    client, auth_header, organiser, coordinator, make_event
):
    event_id = make_event(organiser, status="planning", coordinator_id=coordinator)

    assert _get(client, auth_header, event_id)["venueBookings"] == []


def test_each_booking_carries_its_own_venue_and_status(
    client, auth_header, organiser, coordinator, make_event
):
    event_id = make_event(organiser, status="planning", coordinator_id=coordinator)
    hall = _venue("Hall A", "East", 200)
    room = _venue("Breakout Room", "West", 30)
    _booking(event_id, hall, coordinator, status="approved")
    _booking(event_id, room, coordinator, status="pending",
             start=datetime(2026, 12, 1, 13), end=datetime(2026, 12, 1, 15))

    rows = {r["venueName"]: r for r in _get(client, auth_header, event_id)["venueBookings"]}

    assert set(rows) == {"Hall A", "Breakout Room"}
    assert (rows["Hall A"]["venueCapacity"], rows["Hall A"]["status"]) == (200, "approved")
    assert (rows["Breakout Room"]["venueCapacity"], rows["Breakout Room"]["status"]) == (30, "pending")


def test_held_booking_exposes_hold_expiry(
    client, auth_header, organiser, coordinator, make_event
):
    event_id = make_event(organiser, status="planning", coordinator_id=coordinator)
    expiry = (utcnow() + timedelta(hours=48)).replace(microsecond=0)
    _booking(event_id, _venue(), coordinator, status="held", hold_expires_at=expiry)

    [row] = _get(client, auth_header, event_id)["venueBookings"]

    assert row["status"] == "held"
    assert row["holdExpiresAt"] == expiry.isoformat()


def test_lapsed_hold_is_reported_as_expired(
    client, auth_header, organiser, coordinator, make_event
):
    # The panel hides "expired" bookings, so the API must report it even
    # before the scheduled expire_due_holds job has run.
    event_id = make_event(organiser, status="planning", coordinator_id=coordinator)
    _booking(event_id, _venue(), coordinator, status="held",
             hold_expires_at=utcnow() - timedelta(minutes=5))

    [row] = _get(client, auth_header, event_id)["venueBookings"]

    assert row["status"] == "expired"


def test_history_bookings_are_still_returned_for_the_panel_to_filter(
    client, auth_header, organiser, coordinator, make_event
):
    event_id = make_event(organiser, status="planning", coordinator_id=coordinator)
    venue = _venue()
    for status in ("rejected", "withdrawn", "cancelled", "released", "approved"):
        _booking(event_id, venue, coordinator, status=status)

    statuses = [r["status"] for r in _get(client, auth_header, event_id)["venueBookings"]]

    assert sorted(statuses) == ["approved", "cancelled", "rejected", "released", "withdrawn"]


def test_needs_reconsideration_flag_is_exposed_after_a_significant_edit(
    client, auth_header, organiser, coordinator, make_event
):
    event_id = make_event(organiser, status="planning", coordinator_id=coordinator,
                          expected_attendance=50, capacity_needed=60)
    _booking(event_id, _venue(), coordinator, status="approved")

    res = client.put(
        f"/api/events/{event_id}/update",
        json={"fields": {"expected_attendance": 55}, "offlineReviewConfirmed": True},
        headers=auth_header("coordinator@test.com"),
    )
    assert res.status_code == 200

    [row] = _get(client, auth_header, event_id)["venueBookings"]
    assert row["needsReconsideration"] is True


@pytest.mark.parametrize("email,role", [
    ("vstaff-view@test.com", "venue_staff"),
    ("tech-view@test.com", "technical_support_staff"),
    ("safety-view@test.com", "safety_officer"),
])
def test_internal_roles_see_venue_details(
    client, auth_header, make_user, organiser, coordinator, make_event, email, role
):
    make_user(email, [role])
    event_id = make_event(organiser, status="planning", coordinator_id=coordinator)
    _booking(event_id, _venue(), coordinator)

    [row] = _get(client, auth_header, event_id, email=email)["venueBookings"]

    assert row["venueName"] == "Main Hall"


def test_organiser_sees_venue_details_on_their_own_event(
    client, auth_header, organiser, coordinator, make_event
):
    event_id = make_event(organiser, status="planning", coordinator_id=coordinator)
    _booking(event_id, _venue(), coordinator)

    [row] = _get(client, auth_header, event_id, email="organiser@test.com")["venueBookings"]

    assert row["venueName"] == "Main Hall"