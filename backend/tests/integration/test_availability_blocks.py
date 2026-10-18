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