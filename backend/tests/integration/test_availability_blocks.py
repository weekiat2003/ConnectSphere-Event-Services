"""Tests for the Venue Availability Calendar story
"Venue Staff mark a venue unavailable for operational reasons":
removing an unavailable period, plus the calendar view and layout matching.

Uses the project's tests/conftest.py fixtures: app, client, make_user, auth_header.
"""
from types import SimpleNamespace

import pytest

from app.extensions import db
from app.models.venue import Venue, VenueUnavailability
from app.venues.services.suitability import check_suitability
from app.venues.services.availability import add_flag_once

URL = "/api/venues"
RANGE = "start=2026-11-30T00:00:00&end=2026-12-03T00:00:00"


@pytest.fixture()
def staff_hdr(make_user, auth_header):
    make_user("avail-staff@test.com", ["venue_staff"])
    return auth_header("avail-staff@test.com")


@pytest.fixture()
def coord_hdr(make_user, auth_header):
    make_user("avail-coord@test.com", ["event_coordinator"])
    return auth_header("avail-coord@test.com")


def _make_venue(name="Hall"):
    venue = Venue(name=name, location="North Campus", capacity=100)
    db.session.add(venue)
    db.session.commit()
    return venue.id


@pytest.fixture()
def venue_id(app):
    return _make_venue()


def _add_block(client, headers, venue_id, start="2026-12-01T09:00:00", end="2026-12-01T17:00:00"):
    resp = client.post(
        f"{URL}/{venue_id}/unavailability",
        json={"start": start, "end": end, "reason": "Maintenance"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.get_json()
    return resp.get_json()["unavailability"]["id"]


def _block_count():
    return VenueUnavailability.query.count()


class TestRemoveUnavailability:
    def test_staff_can_remove_a_block(self, client, staff_hdr, venue_id):
        block_id = _add_block(client, staff_hdr, venue_id)

        resp = client.delete(f"{URL}/{venue_id}/unavailability/{block_id}", headers=staff_hdr)

        assert resp.status_code == 204
        assert _block_count() == 0

    def test_removed_block_disappears_from_calendar(self, client, staff_hdr, venue_id):
        block_id = _add_block(client, staff_hdr, venue_id)
        before = client.get(f"{URL}/{venue_id}/calendar?{RANGE}", headers=staff_hdr).get_json()
        assert len(before["unavailability"]) == 1

        client.delete(f"{URL}/{venue_id}/unavailability/{block_id}", headers=staff_hdr)

        after = client.get(f"{URL}/{venue_id}/calendar?{RANGE}", headers=staff_hdr).get_json()
        assert after["unavailability"] == []

    def test_only_the_chosen_block_is_removed(self, client, staff_hdr, venue_id):
        keep = _add_block(client, staff_hdr, venue_id, "2026-12-02T09:00:00", "2026-12-02T12:00:00")
        drop = _add_block(client, staff_hdr, venue_id)

        client.delete(f"{URL}/{venue_id}/unavailability/{drop}", headers=staff_hdr)

        assert [b.id for b in VenueUnavailability.query.all()] == [keep]

    def test_unknown_block_returns_404(self, client, staff_hdr, venue_id):
        resp = client.delete(f"{URL}/{venue_id}/unavailability/9999", headers=staff_hdr)

        assert resp.status_code == 404

    def test_unknown_venue_returns_404(self, client, staff_hdr):
        resp = client.delete(f"{URL}/9999/unavailability/1", headers=staff_hdr)

        assert resp.status_code == 404

    def test_block_cannot_be_removed_through_another_venue(self, client, staff_hdr, venue_id):
        block_id = _add_block(client, staff_hdr, venue_id)
        other_venue = _make_venue("Other Hall")

        resp = client.delete(f"{URL}/{other_venue}/unavailability/{block_id}", headers=staff_hdr)

        assert resp.status_code == 404
        assert _block_count() == 1  # still there

    def test_event_coordinator_cannot_remove(self, client, staff_hdr, coord_hdr, venue_id):
        block_id = _add_block(client, staff_hdr, venue_id)

        resp = client.delete(f"{URL}/{venue_id}/unavailability/{block_id}", headers=coord_hdr)

        assert resp.status_code == 403
        assert _block_count() == 1

    def test_unauthenticated_cannot_remove(self, client, staff_hdr, venue_id):
        block_id = _add_block(client, staff_hdr, venue_id)

        resp = client.delete(f"{URL}/{venue_id}/unavailability/{block_id}")

        assert resp.status_code == 401
        assert _block_count() == 1


class TestCalendarViews:
    def test_per_venue_calendar_shows_block(self, client, staff_hdr, venue_id):
        _add_block(client, staff_hdr, venue_id)

        body = client.get(f"{URL}/{venue_id}/calendar?{RANGE}", headers=staff_hdr).get_json()

        assert len(body["unavailability"]) == 1
        assert body["unavailability"][0]["reason"] == "Maintenance"

    def test_combined_calendar_lists_every_venue(self, client, staff_hdr, coord_hdr, venue_id):
        _make_venue("Second Hall")
        _add_block(client, staff_hdr, venue_id)

        body = client.get(f"{URL}/calendar?{RANGE}", headers=coord_hdr).get_json()

        assert {row["venue"]["name"] for row in body} == {"Hall", "Second Hall"}
        by_name = {row["venue"]["name"]: row for row in body}
        assert len(by_name["Hall"]["unavailability"]) == 1
        assert by_name["Second Hall"]["unavailability"] == []

    def test_calendar_for_unknown_venue_is_404(self, client, staff_hdr):
        assert client.get(f"{URL}/9999/calendar?{RANGE}", headers=staff_hdr).status_code == 404

    def test_calendar_rejects_bad_dates(self, client, staff_hdr, venue_id):
        resp = client.get(f"{URL}/{venue_id}/calendar?start=nope&end=2026-12-03T00:00:00", headers=staff_hdr)

        assert resp.status_code == 400

    def test_block_end_must_be_after_start(self, client, staff_hdr, venue_id):
        resp = client.post(
            f"{URL}/{venue_id}/unavailability",
            json={"start": "2026-12-01T17:00:00", "end": "2026-12-01T09:00:00"},
            headers=staff_hdr,
        )

        assert resp.status_code == 400
        assert _block_count() == 0


class TestLayoutMatching:
    """Layouts are picked from checkboxes (lowercase) but an event's required
    layout is free text, so matching must ignore case and stray spaces."""

    @staticmethod
    def _flags(required_layout, supported):
        event = SimpleNamespace(expected_attendance=10, required_layout=required_layout, accessibility_needs=None)
        venue = SimpleNamespace(capacity=100, supported_layouts=supported, accessibility_features=[])
        return check_suitability(event, venue)

    @pytest.mark.parametrize("required", ["theatre", "Theatre", "THEATRE", "  theatre "])
    def test_matching_ignores_case_and_spaces(self, required):
        assert self._flags(required, ["theatre", "banquet"]) == []

    def test_unsupported_layout_is_flagged(self):
        flags = self._flags("classroom", ["theatre"])

        assert len(flags) == 1 and "classroom" in flags[0]

    def test_venue_with_no_layouts_is_flagged(self):
        assert self._flags("theatre", []) != []

# ---------------------------------------------------------------------------
# Operating hours in the suitability endpoint and in venue edits
# ---------------------------------------------------------------------------
from datetime import date, datetime, time  # noqa: E402

from app.models.event import Event  # noqa: E402
from app.models.venue import BOOKING_APPROVED, VenueAvailabilityFlag, VenueBooking  # noqa: E402


def _hours_event(organiser_id, start, **extra):
    event = Event(
        name="Hours event",
        organiser_id=organiser_id,
        proposed_date=date(2026, 12, 1),
        proposed_time=start,
        expected_attendance=10,
        **extra,
    )
    db.session.add(event)
    db.session.commit()
    return event.id


class TestSuitabilityOperatingHours:
    def _check(self, client, coord_hdr, venue_id, event_id):
        resp = client.get(f"{URL}/{venue_id}/suitability/{event_id}", headers=coord_hdr)
        assert resp.status_code == 200, resp.get_json()
        return resp.get_json()

    def test_event_starting_before_opening_is_flagged_not_blocked(
        self, client, coord_hdr, venue_id, make_user
    ):
        organiser = make_user("hours-org@test.com", ["event_organiser"])
        venue = db.session.get(Venue, venue_id)
        venue.operating_hours = "08:00-22:00"
        db.session.commit()
        event_id = _hours_event(organiser, time(7, 0))

        body = self._check(client, coord_hdr, venue_id, event_id)

        assert body["suitable"] is False
        assert any("operating hours" in flag for flag in body["flags"])

    def test_event_inside_opening_hours_is_suitable(self, client, coord_hdr, venue_id, make_user):
        organiser = make_user("hours-org@test.com", ["event_organiser"])
        venue = db.session.get(Venue, venue_id)
        venue.operating_hours = "08:00-22:00"
        db.session.commit()
        event_id = _hours_event(organiser, time(10, 0))

        body = self._check(client, coord_hdr, venue_id, event_id)

        assert body == {"suitable": True, "flags": []}

    def test_venue_without_hours_never_gets_an_hours_flag(self, client, coord_hdr, venue_id, make_user):
        organiser = make_user("hours-org@test.com", ["event_organiser"])
        event_id = _hours_event(organiser, time(3, 0))

        assert self._check(client, coord_hdr, venue_id, event_id)["suitable"] is True


class TestChangingOperatingHoursFlagsBookedEvents:
    def _approved_booking(self, venue_id, organiser_id, coordinator_id, start):
        event_id = _hours_event(organiser_id, start.time())
        booking = VenueBooking(
            event_id=event_id,
            venue_id=venue_id,
            requested_by=coordinator_id,
            status=BOOKING_APPROVED,
            start_datetime=start,
            end_datetime=start.replace(hour=start.hour + 2),
        )
        db.session.add(booking)
        db.session.commit()
        return event_id

    def test_new_hours_that_exclude_an_approved_event_raise_a_flag(
        self, client, staff_hdr, venue_id, make_user
    ):
        organiser = make_user("hours-org@test.com", ["event_organiser"])
        coordinator = make_user("hours-coord@test.com", ["event_coordinator"])
        event_id = self._approved_booking(venue_id, organiser, coordinator, datetime(2026, 12, 1, 7, 0))

        resp = client.put(
            f"{URL}/{venue_id}", json={"operatingHours": "09:00-18:00"}, headers=staff_hdr
        )

        assert resp.status_code == 200, resp.get_json()
        assert len(resp.get_json()["flagsRaised"]) == 1
        flag = VenueAvailabilityFlag.query.filter_by(event_id=event_id).one()
        assert "operating hours" in flag.reason

    def test_new_hours_that_still_fit_the_event_raise_no_flag(
        self, client, staff_hdr, venue_id, make_user
    ):
        organiser = make_user("hours-org@test.com", ["event_organiser"])
        coordinator = make_user("hours-coord@test.com", ["event_coordinator"])
        self._approved_booking(venue_id, organiser, coordinator, datetime(2026, 12, 1, 10, 0))

        resp = client.put(
            f"{URL}/{venue_id}", json={"operatingHours": "09:00-18:00"}, headers=staff_hdr
        )

        assert resp.status_code == 200
        assert resp.get_json()["flagsRaised"] == []

# ---------------------------------------------------------------------------
# Week 7 change #2, part 2 (over HTTP)
# ---------------------------------------------------------------------------
@pytest.fixture()
def owner(make_user, auth_header):
    """Venue Staff who created the venue (only they may approve / cancel its bookings)."""
    user_id = make_user("owner-staff@test.com", ["venue_staff"])
    return {"id": user_id, "hdr": auth_header("owner-staff@test.com")}


@pytest.fixture()
def coordinators(make_user, auth_header):
    mine = make_user("coord-mine@test.com", ["event_coordinator"])
    make_user("coord-other@test.com", ["event_coordinator"])
    return {
        "id": mine,
        "mine": auth_header("coord-mine@test.com"),
        "other": auth_header("coord-other@test.com"),
    }


def _owned_venue(owner, name="Hall"):
    venue = Venue(name=name, location="North Campus", capacity=100, created_by=owner["id"])
    db.session.add(venue)
    db.session.commit()
    return venue


def _booking_at(venue, coordinator_id, status="approved", day=5, start_hour=10, end_hour=12):
    event = Event(
        name="Annual Conference",
        organiser_id=1,
        coordinator_id=coordinator_id,
        proposed_date=datetime(2026, 12, day).date(),
        proposed_time=datetime(2026, 12, day, start_hour).time(),
        expected_attendance=10,
        status="planning",
    )
    db.session.add(event)
    db.session.flush()
    booking = VenueBooking(
        event_id=event.id,
        venue_id=venue.id,
        requested_by=coordinator_id,
        status=status,
        start_datetime=datetime(2026, 12, day, start_hour),
        end_datetime=datetime(2026, 12, day, end_hour),
    )
    db.session.add(booking)
    db.session.commit()
    return booking


def _block_for(client, headers, venue_id, start="2026-12-05T09:00:00", end="2026-12-05T17:00:00", reason="Roof repairs"):
    resp = client.post(f"{URL}/{venue_id}/unavailability", json={"start": start, "end": end, "reason": reason}, headers=headers)
    assert resp.status_code == 201, resp.get_json()
    return resp.get_json()


class TestEditUnavailabilityRoute:
    def test_staff_can_shorten_a_period(self, client, owner):
        venue = _owned_venue(owner)
        block_id = _block_for(client, owner["hdr"], venue.id)["unavailability"]["id"]

        resp = client.put(f"{URL}/{venue.id}/unavailability/{block_id}", json={"end": "2026-12-05T12:00:00"}, headers=owner["hdr"])

        assert resp.status_code == 200
        assert resp.get_json()["unavailability"]["end"] == "2026-12-05T12:00:00"
        calendar = client.get(f"{URL}/{venue.id}/calendar?start=2026-12-05T00:00:00&end=2026-12-06T00:00:00", headers=owner["hdr"]).get_json()
        assert calendar["unavailability"][0]["end"] == "2026-12-05T12:00:00"

    def test_extending_a_period_flags_newly_affected_events(self, client, owner, coordinators):
        venue = _owned_venue(owner)
        _booking_at(venue, coordinators["id"], start_hour=14, end_hour=16)
        block_id = _block_for(client, owner["hdr"], venue.id, end="2026-12-05T12:00:00")["unavailability"]["id"]

        resp = client.put(f"{URL}/{venue.id}/unavailability/{block_id}", json={"end": "2026-12-05T17:00:00"}, headers=owner["hdr"])

        assert len(resp.get_json()["flagsRaised"]) == 1

    @pytest.mark.parametrize(
        "body",
        [{"end": "2026-12-05T08:00:00"}, {"end": "not-a-date"}, {"start": "2026-12-06T00:00:00"}, {"reason": "x" * 300}],
    )
    def test_invalid_edits_return_400_and_change_nothing(self, client, owner, body):
        venue = _owned_venue(owner)
        block_id = _block_for(client, owner["hdr"], venue.id)["unavailability"]["id"]

        resp = client.put(f"{URL}/{venue.id}/unavailability/{block_id}", json=body, headers=owner["hdr"])

        assert resp.status_code == 400
        assert VenueUnavailability.query.get(block_id).end_datetime == datetime(2026, 12, 5, 17)

    def test_unknown_period_or_venue_returns_404(self, client, owner):
        venue = _owned_venue(owner)

        assert client.put(f"{URL}/{venue.id}/unavailability/9999", json={"end": "2026-12-05T12:00:00"}, headers=owner["hdr"]).status_code == 404
        assert client.put(f"{URL}/9999/unavailability/1", json={"end": "2026-12-05T12:00:00"}, headers=owner["hdr"]).status_code == 404

    def test_coordinator_cannot_edit_and_anonymous_is_unauthorised(self, client, owner, coordinators):
        venue = _owned_venue(owner)
        block_id = _block_for(client, owner["hdr"], venue.id)["unavailability"]["id"]
        url = f"{URL}/{venue.id}/unavailability/{block_id}"

        assert client.put(url, json={"end": "2026-12-05T12:00:00"}, headers=coordinators["mine"]).status_code == 403
        assert client.put(url, json={"end": "2026-12-05T12:00:00"}).status_code == 401
        assert VenueUnavailability.query.get(block_id).end_datetime == datetime(2026, 12, 5, 17)


class TestApprovalBlockedByUnavailability:
    def test_pending_request_in_a_blocked_period_is_refused_with_the_reason(self, client, owner, coordinators):
        venue = _owned_venue(owner)
        pending = _booking_at(venue, coordinators["id"], status="pending")
        _block_for(client, owner["hdr"], venue.id)

        resp = client.post(f"{URL}/bookings/{pending.id}/approve", headers=owner["hdr"])

        assert resp.status_code == 409
        assert "Roof repairs" in resp.get_json()["error"]
        assert VenueBooking.query.get(pending.id).status == "pending"

    def test_approval_works_again_once_the_period_is_removed(self, client, owner, coordinators):
        venue = _owned_venue(owner)
        pending = _booking_at(venue, coordinators["id"], status="pending")
        block_id = _block_for(client, owner["hdr"], venue.id)["unavailability"]["id"]
        client.delete(f"{URL}/{venue.id}/unavailability/{block_id}", headers=owner["hdr"])

        assert client.post(f"{URL}/bookings/{pending.id}/approve", headers=owner["hdr"]).status_code == 200


class TestFlagsForCoordinators:
    def test_flag_tells_the_coordinator_what_to_do(self, client, owner, coordinators):
        venue = _owned_venue(owner, "Main Hall")
        booking = _booking_at(venue, coordinators["id"])
        _block_for(client, owner["hdr"], venue.id)

        flags = client.get(f"{URL}/flags/mine", headers=coordinators["mine"]).get_json()

        assert len(flags) == 1
        flag = flags[0]
        assert (flag["eventName"], flag["venueName"], flag["reason"]) == ("Annual Conference", "Main Hall", "Roof repairs")
        assert flag["bookingId"] == booking.id
        assert flag["unavailablePeriods"][0]["start"] == "2026-12-05T09:00:00"
        # The booking is rejected, but the event itself is not cancelled.
        assert VenueBooking.query.get(booking.id).status == "rejected"

    def test_other_coordinators_do_not_see_it(self, client, owner, coordinators):
        venue = _owned_venue(owner)
        _booking_at(venue, coordinators["id"])
        _block_for(client, owner["hdr"], venue.id)

        assert client.get(f"{URL}/flags/mine", headers=coordinators["other"]).get_json() == []

    def test_only_the_events_coordinator_can_resolve_its_flag(self, client, owner, coordinators):
        venue = _owned_venue(owner)
        _booking_at(venue, coordinators["id"])
        _block_for(client, owner["hdr"], venue.id)
        flag_id = VenueAvailabilityFlag.query.one().id

        assert client.post(f"{URL}/flags/{flag_id}/resolve", headers=coordinators["other"]).status_code == 403
        assert VenueAvailabilityFlag.query.get(flag_id).resolved is False
        assert client.post(f"{URL}/flags/{flag_id}/resolve", headers=coordinators["mine"]).status_code == 200
        assert client.get(f"{URL}/flags/mine", headers=coordinators["mine"]).get_json() == []

    def test_unknown_flag_returns_404(self, client, coordinators):
        assert client.post(f"{URL}/flags/9999/resolve", headers=coordinators["mine"]).status_code == 404


class TestReleasingTheOriginalBooking:
    def test_staff_cancel_frees_the_venue_and_closes_the_flag(
        self, client, owner, coordinators
    ):
        venue = _owned_venue(owner)
        booking = _booking_at(venue, coordinators["id"])

        # Create a flag without marking the venue unavailable.
        # This keeps the booking approved so staff can cancel it.
        add_flag_once(
            booking.event_id,
            venue.id,
            "Venue unavailable",
        )
        db.session.commit()

        resp = client.post(
            f"{URL}/bookings/{booking.id}/cancel",
            json={"reason": "Venue unavailable"},
            headers=owner["hdr"],
        )

        assert resp.status_code == 200
        assert VenueBooking.query.get(booking.id).status == "cancelled"
        assert client.get(
            f"{URL}/flags/mine",
            headers=coordinators["mine"],
        ).get_json() == []

        event = Event.query.get(booking.event_id)
        assert event.status != "cancelled"
        assert event.name == "Annual Conference"

    def test_another_staff_member_cannot_cancel_this_venues_booking(self, client, owner, coordinators, make_user, auth_header):
        make_user("intruder@test.com", ["venue_staff"])
        venue = _owned_venue(owner)
        booking = _booking_at(venue, coordinators["id"])

        resp = client.post(f"{URL}/bookings/{booking.id}/cancel", json={}, headers=auth_header("intruder@test.com"))

        assert resp.status_code == 403
        assert VenueBooking.query.get(booking.id).status == "approved"

    def test_a_replacement_venue_can_be_requested_for_the_same_event(self, client, owner, coordinators):
        original, replacement = _owned_venue(owner, "Original"), _owned_venue(owner, "Replacement")
        booking = _booking_at(original, coordinators["id"])
        _block_for(client, owner["hdr"], original.id)

        resp = client.post(
            f"{URL}/bookings",
            json={"eventId": booking.event_id, "venues": [{"venueId": replacement.id, "date": "2026-12-05", "startTime": "10:00", "endTime": "12:00"}]},
            headers=coordinators["mine"],
        )

        assert resp.status_code == 201, resp.get_json()
        assert VenueBooking.query.filter_by(event_id=booking.event_id).count() == 2
