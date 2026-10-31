"""Unit tests for the Venue Availability Calendar service
(app/venues/services/availability.py) and booking conflict detection
(has_confirmed_conflict in app/venues/services/booking.py).
Covers Week 7 change #1 (setup/turnaround time counts as occupied time) and
change #2 (a venue becoming unavailable flags affected events instead of
cancelling them). Time arithmetic is tested without a database; the rest calls
the service functions directly against the in-memory test database.
"""
from datetime import datetime
from types import SimpleNamespace
import pytest
from app.extensions import db
from app.models.event import Event
from app.models.venue import (
    BOOKING_APPROVED,
    BOOKING_PENDING,
    BOOKING_REJECTED,
    Venue,
    VenueAvailabilityFlag,
    VenueBooking,
    VenueUnavailability,
)
from app.venues.services.availability import (
    add_flag_once,
    add_unavailability,
    compute_booking_window,
    flag_timing_conflicts,
    get_calendar,
    get_combined_calendar,
    list_flags_for_event,
    list_unresolved_flags_for_coordinator,
    pad_window,
    remove_unavailability,
    resolve_flag,
)
from app.venues.services.availability import (
    describe_flag,
    find_unavailability_overlap,
    resolve_flags_for_booking,
    update_unavailability,
)
from app.venues.services.booking import (
    approve_booking,
    cancel_booking,
    has_confirmed_conflict,
    manage_hold,
)
from app.models.venue import BOOKING_CANCELLED, BOOKING_HELD
from app.common.time import utcnow
from datetime import timedelta
DEFAULT_REASON = "Venue marked unavailable during this event's scheduled time"

def dt(day, hour, minute=0):
    return datetime(2026, 12, day, hour, minute)

def _venue(**overrides):
    data = {
        "name": "Hall",
        "location": "North Campus",
        "capacity": 100,
        "is_active": True,
        "setup_minutes": 0,
        "turnaround_minutes": 0,
    }
    data.update(overrides)
    venue = Venue(**data)
    db.session.add(venue)
    db.session.commit()
    return venue

def _booking(venue, start, end, status=BOOKING_APPROVED, coordinator_id=None):
    event = Event(
        name="Event",
        organiser_id=1,
        coordinator_id=coordinator_id,
        proposed_date=start.date(),
        proposed_time=start.time(),
    )
    db.session.add(event)
    db.session.flush()
    booking = VenueBooking(
        event_id=event.id,
        venue_id=venue.id,
        requested_by=1,
        status=status,
        start_datetime=start,
        end_datetime=end,
    )
    db.session.add(booking)
    db.session.commit()
    return booking
# ---------------------------------------------------------------------------
# Setup / turnaround padding (pure, no database)
# ---------------------------------------------------------------------------

class TestPadWindow:

    def test_week_7_example_10_to_12_with_30_and_45_occupies_0930_to_1245(self):
        venue = SimpleNamespace(setup_minutes=30, turnaround_minutes=45)
        start, end = pad_window(dt(1, 10), dt(1, 12), venue)
        assert (start, end) == (dt(1, 9, 30), dt(1, 12, 45))

    def test_zero_times_leave_the_window_unchanged(self):
        venue = SimpleNamespace(setup_minutes=0, turnaround_minutes=0)
        assert pad_window(dt(1, 10), dt(1, 12), venue) == (dt(1, 10), dt(1, 12))

    def test_missing_times_are_treated_as_zero(self):
        venue = SimpleNamespace(setup_minutes=None, turnaround_minutes=None)
        assert pad_window(dt(1, 10), dt(1, 12), venue) == (dt(1, 10), dt(1, 12))

    def test_setup_only_extends_the_start(self):
        venue = SimpleNamespace(setup_minutes=60, turnaround_minutes=0)
        assert pad_window(dt(1, 10), dt(1, 12), venue) == (dt(1, 9), dt(1, 12))

    def test_turnaround_only_extends_the_end(self):
        venue = SimpleNamespace(setup_minutes=0, turnaround_minutes=60)
        assert pad_window(dt(1, 10), dt(1, 12), venue) == (dt(1, 10), dt(1, 13))

    def test_padding_can_cross_midnight(self):
        venue = SimpleNamespace(setup_minutes=30, turnaround_minutes=45)
        start, end = pad_window(dt(1, 23), dt(2, 0, 30), venue)
        assert start == dt(1, 22, 30) and end == dt(2, 1, 15)

    def test_compute_booking_window_uses_the_bookings_own_times(self):
        venue = SimpleNamespace(setup_minutes=30, turnaround_minutes=45)
        booking = SimpleNamespace(start_datetime=dt(1, 10), end_datetime=dt(1, 12))
        assert compute_booking_window(booking, venue) == (dt(1, 9, 30), dt(1, 12, 45))
# ---------------------------------------------------------------------------
# add_unavailability: mark a venue unavailable (Week 7 change #2)
# ---------------------------------------------------------------------------

class TestAddUnavailability:

    def test_records_the_block_with_reason_and_creator(self, app):
        venue = _venue()
        block, flags = add_unavailability(venue, 5, dt(5, 9), dt(5, 17), "Maintenance")
        assert block.id is not None
        assert (block.start_datetime, block.end_datetime) == (dt(5, 9), dt(5, 17))
        assert block.reason == "Maintenance"
        assert block.created_by == 5
        assert flags == []

    def test_reason_is_optional(self, app):
        block, _ = add_unavailability(_venue(), 1, dt(5, 9), dt(5, 17))
        assert block.reason is None
    @pytest.mark.parametrize("end", [dt(5, 9), dt(5, 8)])

    def test_end_must_be_after_start(self, app, end):
        venue = _venue()
        with pytest.raises(ValueError, match="after start"):
            add_unavailability(venue, 1, dt(5, 9), end)
            assert VenueUnavailability.query.count() == 0
    @pytest.mark.parametrize("start,end", [("2026-12-05T09:00", dt(5, 17)), (None, None)])

    def test_start_and_end_must_be_datetimes(self, app, start, end):
        with pytest.raises(ValueError, match="ISO datetimes"):
            add_unavailability(_venue(), 1, start, end)

    def test_overlapping_approved_booking_is_flagged_and_rejected(self, app):
        venue = _venue()
        booking = _booking(venue, dt(5, 10), dt(5, 12))
        event = db.session.get(Event, booking.event_id)
        status_before = event.status

        _, flags = add_unavailability(
            venue, 1, dt(5, 9), dt(5, 17), "Renovation"
        )

        assert len(flags) == 1
        assert flags[0].event_id == booking.event_id
        assert flags[0].reason == "Renovation"
        assert VenueBooking.query.get(booking.id).status == BOOKING_REJECTED

        db.session.refresh(event)
        assert event.status == status_before

    def test_default_reason_is_used_for_the_flag_when_none_given(self, app):
        venue = _venue()
        _booking(venue, dt(5, 10), dt(5, 12))
        _, flags = add_unavailability(venue, 1, dt(5, 9), dt(5, 17))
        assert flags[0].reason == DEFAULT_REASON
    @pytest.mark.parametrize("status", [BOOKING_PENDING, BOOKING_REJECTED])

    def test_only_approved_bookings_are_flagged(self, app, status):
        venue = _venue()
        _booking(venue, dt(5, 10), dt(5, 12), status=status)
        _, flags = add_unavailability(venue, 1, dt(5, 9), dt(5, 17))
        assert flags == []

    def test_booking_outside_the_block_is_not_flagged(self, app):
        venue = _venue()
        _booking(venue, dt(6, 10), dt(6, 12))
        _, flags = add_unavailability(venue, 1, dt(5, 9), dt(5, 17))
        assert flags == []

    def test_block_touching_the_end_of_a_booking_does_not_flag_it(self, app):
        venue = _venue()
        _booking(venue, dt(5, 10), dt(5, 12))
        _, flags = add_unavailability(venue, 1, dt(5, 12), dt(5, 17))
        assert flags == []

    def test_block_during_turnaround_flags_the_booking(self, app):
        venue = _venue(turnaround_minutes=45)
        _booking(venue, dt(5, 10), dt(5, 12))  # occupies the venue until 12:45
        _, flags = add_unavailability(venue, 1, dt(5, 12, 30), dt(5, 14))
        assert len(flags) == 1

    def test_block_during_setup_flags_the_booking(self, app):
        venue = _venue(setup_minutes=30)
        _booking(venue, dt(5, 10), dt(5, 12))  # occupies the venue from 09:30
        _, flags = add_unavailability(venue, 1, dt(5, 8), dt(5, 9, 45))
        assert len(flags) == 1

    def test_same_block_added_twice_flags_the_event_once(self, app):
        venue = _venue()
        _booking(venue, dt(5, 10), dt(5, 12))
        add_unavailability(venue, 1, dt(5, 9), dt(5, 17), "Maintenance")
        _, second_flags = add_unavailability(venue, 1, dt(5, 9), dt(5, 17), "Maintenance")
        assert second_flags == []
        assert VenueAvailabilityFlag.query.count() == 1

    def test_flags_for_other_venues_events_are_not_raised(self, app):
        venue, other = _venue(name="A"), _venue(name="B")
        _booking(other, dt(5, 10), dt(5, 12))
        _, flags = add_unavailability(venue, 1, dt(5, 9), dt(5, 17))
        assert flags == []

class TestRemoveUnavailability:

    def test_removes_only_the_chosen_block(self, app):
        venue = _venue()
        keep, _ = add_unavailability(venue, 1, dt(6, 9), dt(6, 12))
        drop, _ = add_unavailability(venue, 1, dt(5, 9), dt(5, 12))
        remove_unavailability(venue, drop.id)
        assert [b.id for b in VenueUnavailability.query.all()] == [keep.id]

    def test_unknown_block_raises_lookup_error(self, app):
        with pytest.raises(LookupError):
            remove_unavailability(_venue(), 9999)

    def test_block_of_another_venue_cannot_be_removed(self, app):
        venue, other = _venue(name="A"), _venue(name="B")
        block, _ = add_unavailability(other, 1, dt(5, 9), dt(5, 12))
        with pytest.raises(LookupError):
            remove_unavailability(venue, block.id)
            assert VenueUnavailability.query.count() == 1

    def test_removal_does_not_resolve_existing_flags(self, app):
        venue = _venue()
        _booking(venue, dt(5, 10), dt(5, 12))
        block, _ = add_unavailability(venue, 1, dt(5, 9), dt(5, 17))
        remove_unavailability(venue, block.id)
        assert VenueAvailabilityFlag.query.filter_by(resolved=False).count() == 1
# ---------------------------------------------------------------------------
# get_calendar / get_combined_calendar
# ---------------------------------------------------------------------------

class TestCalendar:

    def test_unknown_venue_raises_lookup_error(self, app):
        with pytest.raises(LookupError):
            get_calendar(9999, dt(1, 0), dt(2, 0))

    def test_empty_venue_returns_empty_lists(self, app):
        venue = _venue()
        assert get_calendar(venue.id, dt(1, 0), dt(8, 0)) == {
            "confirmedBookings": [],
            "heldBookings": [],
            "unavailability": [],
        }

    def test_approved_booking_appears_with_its_effective_window(self, app):
        venue = _venue(setup_minutes=30, turnaround_minutes=45)
        _booking(venue, dt(1, 10), dt(1, 12))
        result = get_calendar(venue.id, dt(1, 0), dt(2, 0))
        assert len(result["confirmedBookings"]) == 1
        entry = result["confirmedBookings"][0]
        assert entry["effectiveStart"] == "2026-12-01T09:30:00"
        assert entry["effectiveEnd"] == "2026-12-01T12:45:00"

    def test_only_bookings_in_the_requested_range_are_returned(self, app):
        venue = _venue()
        inside = _booking(venue, dt(1, 10), dt(1, 12))
        _booking(venue, dt(10, 10), dt(10, 12))
        result = get_calendar(venue.id, dt(1, 0), dt(2, 0))
        assert [b["id"] for b in result["confirmedBookings"]] == [inside.id]
    @pytest.mark.parametrize("status", [BOOKING_PENDING, BOOKING_REJECTED])

    def test_only_approved_bookings_count_as_unavailable(self, app, status):
        venue = _venue()
        _booking(venue, dt(1, 10), dt(1, 12), status=status)
        assert get_calendar(venue.id, dt(1, 0), dt(2, 0))["confirmedBookings"] == []

    def test_setup_time_can_pull_a_booking_into_the_range(self, app):
        venue = _venue(setup_minutes=30)
        _booking(venue, dt(1, 10), dt(1, 12))  # busy from 09:30
        assert len(get_calendar(venue.id, dt(1, 0), dt(1, 9, 45))["confirmedBookings"]) == 1
        assert get_calendar(venue.id, dt(1, 0), dt(1, 9, 15))["confirmedBookings"] == []

    def test_booking_whose_padded_window_ended_before_the_range_is_excluded(self, app):
# 10:00-12:00 with 30 min setup and 45 min turnaround is busy 09:30-12:45.
# The SQL pre-filter is deliberately generous, so this checks the exact window.
        venue = _venue(setup_minutes=30, turnaround_minutes=45)
        _booking(venue, dt(1, 10), dt(1, 12))
        assert get_calendar(venue.id, dt(1, 12, 50), dt(1, 14))["confirmedBookings"] == []
        assert len(get_calendar(venue.id, dt(1, 12, 40), dt(1, 14))["confirmedBookings"]) == 1

    def test_bookings_are_sorted_by_start_time(self, app):
        venue = _venue()
        late = _booking(venue, dt(1, 15), dt(1, 17))
        early = _booking(venue, dt(1, 9), dt(1, 11))
        ids = [b["id"] for b in get_calendar(venue.id, dt(1, 0), dt(2, 0))["confirmedBookings"]]
        assert ids == [early.id, late.id]

    def test_unavailability_in_range_is_returned_and_outside_is_not(self, app):
        venue = _venue()
        add_unavailability(venue, 1, dt(1, 9), dt(1, 12), "Inside")
        add_unavailability(venue, 1, dt(20, 9), dt(20, 12), "Outside")
        reasons = [u["reason"] for u in get_calendar(venue.id, dt(1, 0), dt(2, 0))["unavailability"]]
        assert reasons == ["Inside"]

    def test_combined_calendar_lists_active_venues_only(self, app):
        a = _venue(name="A")
        b = _venue(name="B")
        _venue(name="Retired", is_active=False)
        add_unavailability(a, 1, dt(1, 9), dt(1, 12))
        rows = get_combined_calendar(dt(1, 0), dt(2, 0))
        assert {r["venue"]["name"] for r in rows} == {"A", "B"}
        by_name = {r["venue"]["name"]: r for r in rows}
        assert len(by_name["A"]["unavailability"]) == 1
        assert by_name["B"]["unavailability"] == []
        assert by_name["A"]["heldBookings"] == []
        assert by_name["B"]["heldBookings"] == []
        assert set(by_name["A"]) == {"venue", "confirmedBookings", "heldBookings", "unavailability"}
        assert b.id in {r["venue"]["id"] for r in rows}
# ---------------------------------------------------------------------------
# Flags: add once, list for a coordinator, resolve
# ---------------------------------------------------------------------------

class TestFlags:

    def test_add_flag_once_ignores_an_identical_unresolved_flag(self, app):
        venue = _venue()
        booking = _booking(venue, dt(1, 10), dt(1, 12))
        first = add_flag_once(booking.event_id, venue.id, "Maintenance")
        db.session.commit()
        second = add_flag_once(booking.event_id, venue.id, "Maintenance")
        assert first is not None and second is None

    def test_a_different_reason_creates_a_new_flag(self, app):
        venue = _venue()
        booking = _booking(venue, dt(1, 10), dt(1, 12))
        add_flag_once(booking.event_id, venue.id, "Maintenance")
        db.session.commit()
        other = add_flag_once(booking.event_id, venue.id, "Fire inspection")
        assert other is not None

    def test_a_resolved_flag_can_be_raised_again(self, app):
        venue = _venue()
        booking = _booking(venue, dt(1, 10), dt(1, 12))
        flag = add_flag_once(booking.event_id, venue.id, "Maintenance")
        db.session.commit()
        resolve_flag(flag)
        assert add_flag_once(booking.event_id, venue.id, "Maintenance") is not None

    def test_coordinator_only_sees_flags_for_their_own_events(self, app):
        venue = _venue()
        mine = _booking(venue, dt(1, 10), dt(1, 12), coordinator_id=7)
        theirs = _booking(venue, dt(2, 10), dt(2, 12), coordinator_id=8)
        add_flag_once(mine.event_id, venue.id, "Maintenance")
        add_flag_once(theirs.event_id, venue.id, "Maintenance")
        db.session.commit()
        flags = list_unresolved_flags_for_coordinator(7)
        assert [f.event_id for f in flags] == [mine.event_id]

    def test_resolving_marks_the_flag_and_removes_it_from_the_list(self, app):
        venue = _venue()
        booking = _booking(venue, dt(1, 10), dt(1, 12), coordinator_id=7)
        flag = add_flag_once(booking.event_id, venue.id, "Maintenance")
        db.session.commit()
        resolved = resolve_flag(flag)
        assert resolved.resolved is True and resolved.resolved_at is not None
        assert list_unresolved_flags_for_coordinator(7) == []

    def test_list_flags_for_event_includes_resolved_ones(self, app):
        venue = _venue()
        booking = _booking(venue, dt(1, 10), dt(1, 12))
        flag = add_flag_once(booking.event_id, venue.id, "Maintenance")
        db.session.commit()
        resolve_flag(flag)
        assert len(list_flags_for_event(booking.event_id)) == 1
# ---------------------------------------------------------------------------
# flag_timing_conflicts (Week 7 change #1: existing bookings become problematic)
# ---------------------------------------------------------------------------

class TestFlagTimingConflicts:

    def test_back_to_back_bookings_conflict_once_padding_is_added(self, app):
        venue = _venue(turnaround_minutes=30)
        first = _booking(venue, dt(1, 10), dt(1, 12))
        second = _booking(venue, dt(1, 12, 15), dt(1, 14))  # starts 15 min after first ends
        flags = flag_timing_conflicts(venue, "Timing changed")
        db.session.commit()
        assert {f.event_id for f in flags} == {first.event_id, second.event_id}

    def test_enough_gap_means_no_flags(self, app):
        venue = _venue(setup_minutes=15, turnaround_minutes=15)
        _booking(venue, dt(1, 10), dt(1, 12))
        _booking(venue, dt(1, 13), dt(1, 14))
        assert flag_timing_conflicts(venue, "Timing changed") == []

    def test_bookings_on_other_days_never_conflict(self, app):
        venue = _venue(setup_minutes=60, turnaround_minutes=60)
        _booking(venue, dt(1, 10), dt(1, 12))
        _booking(venue, dt(2, 10), dt(2, 12))
        assert flag_timing_conflicts(venue, "Timing changed") == []

    def test_pending_bookings_are_ignored(self, app):
        venue = _venue(turnaround_minutes=60)
        _booking(venue, dt(1, 10), dt(1, 12))
        _booking(venue, dt(1, 12, 15), dt(1, 14), status=BOOKING_PENDING)
        assert flag_timing_conflicts(venue, "Timing changed") == []
# ---------------------------------------------------------------------------
# has_confirmed_conflict (booking conflict detection including padding)
# ---------------------------------------------------------------------------

def _candidate(venue, start, end):
    """A booking that has not been saved: the thing being approved."""
    return VenueBooking(
        event_id=0,
        venue_id=venue.id,
        requested_by=1,
        status=BOOKING_PENDING,
        start_datetime=start,
        end_datetime=end,
    )

class TestHasConfirmedConflict:

    def test_overlapping_approved_booking_conflicts(self, app):
        venue = _venue()
        _booking(venue, dt(1, 10), dt(1, 12))
        assert has_confirmed_conflict(venue.id, _candidate(venue, dt(1, 11), dt(1, 13))) is True

    def test_no_overlap_means_no_conflict(self, app):
        venue = _venue()
        _booking(venue, dt(1, 10), dt(1, 12))
        assert has_confirmed_conflict(venue.id, _candidate(venue, dt(1, 14), dt(1, 16))) is False

    def test_back_to_back_with_no_padding_is_allowed(self, app):
        venue = _venue()
        _booking(venue, dt(1, 10), dt(1, 12))
        assert has_confirmed_conflict(venue.id, _candidate(venue, dt(1, 12), dt(1, 14))) is False

    def test_turnaround_time_blocks_an_early_next_booking(self, app):
        venue = _venue(turnaround_minutes=30)
        _booking(venue, dt(1, 10), dt(1, 12))  # busy until 12:30
        assert has_confirmed_conflict(venue.id, _candidate(venue, dt(1, 12, 15), dt(1, 13))) is True
        assert has_confirmed_conflict(venue.id, _candidate(venue, dt(1, 12, 30), dt(1, 13))) is False

    def test_setup_time_of_the_candidate_counts(self, app):
        venue = _venue(setup_minutes=30)
        _booking(venue, dt(1, 10), dt(1, 12))  # setup 09:30; busy until 12:00
# candidate 12:15-13:00 needs setup from 11:45, which overlaps the first booking
        assert has_confirmed_conflict(venue.id, _candidate(venue, dt(1, 12, 15), dt(1, 13))) is True
        assert has_confirmed_conflict(venue.id, _candidate(venue, dt(1, 12, 30), dt(1, 13))) is False

    def test_week_7_example_window_blocks_0930_to_1245(self, app):
        venue = _venue(setup_minutes=30, turnaround_minutes=45)
        _booking(venue, dt(1, 10), dt(1, 12))  # occupies 09:30-12:45
# a candidate whose own padded window ends at 09:30 or starts at 12:45 is fine
        assert has_confirmed_conflict(venue.id, _candidate(venue, dt(1, 6), dt(1, 8, 15))) is False
        assert has_confirmed_conflict(venue.id, _candidate(venue, dt(1, 13, 15), dt(1, 15))) is False
        assert has_confirmed_conflict(venue.id, _candidate(venue, dt(1, 6), dt(1, 9))) is True
    @pytest.mark.parametrize("status", [BOOKING_PENDING, BOOKING_REJECTED])

    def test_only_approved_bookings_cause_conflicts(self, app, status):
        venue = _venue()
        _booking(venue, dt(1, 10), dt(1, 12), status=status)
        assert has_confirmed_conflict(venue.id, _candidate(venue, dt(1, 10), dt(1, 12))) is False

    def test_other_venues_bookings_are_ignored(self, app):
        venue, other = _venue(name="A"), _venue(name="B")
        _booking(other, dt(1, 10), dt(1, 12))
        assert has_confirmed_conflict(venue.id, _candidate(venue, dt(1, 10), dt(1, 12))) is False

    def test_a_booking_does_not_conflict_with_itself_when_excluded(self, app):
        venue = _venue()
        existing = _booking(venue, dt(1, 10), dt(1, 12))
        assert has_confirmed_conflict(venue.id, existing, exclude_booking_id=existing.id) is False
        assert has_confirmed_conflict(venue.id, existing) is True

    def test_unknown_venue_has_no_conflict(self, app):
        venue = _venue()
        assert has_confirmed_conflict(9999, _candidate(venue, dt(1, 10), dt(1, 12))) is False
# ---------------------------------------------------------------------------
# Operating-hours helpers (shared by venue search and the suitability check)
# ---------------------------------------------------------------------------
from datetime import time  # noqa: E402
from app.venues.services.availability import fits_operating_hours, parse_operating_hours  # noqa: E402

def _hours_venue(text):
    return SimpleNamespace(operating_hours=text)
@pytest.mark.parametrize(
    "text,expected",
    [
        ("08:00-22:00", (time(8), time(22))),
        ("8:00 - 22:00", (time(8), time(22))),
        ("08:00–22:00", (time(8), time(22))),
        ("08:30-17:45", (time(8, 30), time(17, 45))),
    ],
)

def test_parse_operating_hours_understands_common_formats(text, expected):
    assert parse_operating_hours(_hours_venue(text)) == expected
@pytest.mark.parametrize(
    "text", [None, "", "   ", "9am-5pm", "closed", "25:00-26:00", "08:60-10:00", "22:00-06:00", "08:00-08:00"]
)

def test_parse_operating_hours_returns_none_when_there_is_no_usable_restriction(text):
    assert parse_operating_hours(_hours_venue(text)) is None

def test_parse_operating_hours_tolerates_objects_without_the_attribute():
    assert parse_operating_hours(SimpleNamespace()) is None
@pytest.mark.parametrize(
    "start,end,expected",
    [
        (time(8), time(22), True),         # exactly the opening hours
        (time(10), time(12), True),
        (time(7, 59), time(10), False),    # starts before opening
        (time(20), time(22, 1), False),    # ends after closing
        (time(22), time(23), False),       # entirely after closing
    ],
)

def test_fits_operating_hours_with_a_start_and_an_end(start, end, expected):
    assert fits_operating_hours(_hours_venue("08:00-22:00"), start, end) is expected
@pytest.mark.parametrize(
    "start,expected",
    [(time(7, 59), False), (time(8), True), (time(21, 59), True), (time(22), False)],
)

def test_fits_operating_hours_with_only_a_start_checks_open_inclusive_close_exclusive(start, expected):
    assert fits_operating_hours(_hours_venue("08:00-22:00"), start) is expected

def test_fits_operating_hours_is_always_true_without_usable_hours():
    assert fits_operating_hours(_hours_venue(None), time(3), time(4)) is True
    assert fits_operating_hours(_hours_venue(None), time(3)) is True


# ---------------------------------------------------------------------------
# Week 7 change #2, part 2: edit a period, block-aware approval, richer flags
# ---------------------------------------------------------------------------
class TestUpdateUnavailability:
    def test_shortening_a_period_keeps_its_start_and_reason(self, app):
        venue = _venue()
        block, _ = add_unavailability(venue, 1, dt(5, 9), dt(5, 17), "Repairs")

        updated, flags = update_unavailability(venue, block.id, end=dt(5, 12))

        assert (updated.start_datetime, updated.end_datetime) == (dt(5, 9), dt(5, 12))
        assert updated.reason == "Repairs"
        assert flags == []

    def test_extending_over_an_approved_booking_flags_it(self, app):
        venue = _venue()
        booking = _booking(venue, dt(5, 14), dt(5, 16))
        block, _ = add_unavailability(venue, 1, dt(5, 9), dt(5, 12), "Repairs")

        _, flags = update_unavailability(venue, block.id, end=dt(5, 17))

        assert [f.event_id for f in flags] == [booking.event_id]
        assert VenueBooking.query.get(booking.id).status == BOOKING_APPROVED

    def test_extending_twice_does_not_duplicate_the_flag(self, app):
        venue = _venue()
        _booking(venue, dt(5, 14), dt(5, 16))
        block, _ = add_unavailability(venue, 1, dt(5, 9), dt(5, 12), "Repairs")
        update_unavailability(venue, block.id, end=dt(5, 17))

        _, second = update_unavailability(venue, block.id, end=dt(5, 18))

        assert second == [] and VenueAvailabilityFlag.query.count() == 1

    def test_reason_can_be_changed_and_cleared(self, app):
        venue = _venue()
        block, _ = add_unavailability(venue, 1, dt(5, 9), dt(5, 17), "Repairs")

        assert update_unavailability(venue, block.id, reason="  Fire drill ")[0].reason == "Fire drill"
        assert update_unavailability(venue, block.id, reason="   ")[0].reason is None
        assert update_unavailability(venue, block.id, reason=None)[0].reason is None

    @pytest.mark.parametrize("kwargs", [{"end": dt(5, 9)}, {"end": dt(5, 8)}, {"start": dt(5, 18)}])
    def test_end_must_stay_after_start_and_nothing_changes(self, app, kwargs):
        venue = _venue()
        block, _ = add_unavailability(venue, 1, dt(5, 9), dt(5, 17))

        with pytest.raises(ValueError, match="after start"):
            update_unavailability(venue, block.id, **kwargs)

        db.session.refresh(block)
        assert (block.start_datetime, block.end_datetime) == (dt(5, 9), dt(5, 17))

    def test_non_datetime_values_are_rejected(self, app):
        venue = _venue()
        block, _ = add_unavailability(venue, 1, dt(5, 9), dt(5, 17))

        with pytest.raises(ValueError, match="ISO datetimes"):
            update_unavailability(venue, block.id, end="2026-12-05T12:00")

    @pytest.mark.parametrize("reason", [123, ["x"], "x" * 256])
    def test_invalid_reason_is_rejected(self, app, reason):
        venue = _venue()
        block, _ = add_unavailability(venue, 1, dt(5, 9), dt(5, 17))

        with pytest.raises(ValueError):
            update_unavailability(venue, block.id, reason=reason)

    def test_unknown_or_other_venues_period_raises_lookup_error(self, app):
        venue, other = _venue(name="A"), _venue(name="B")
        block, _ = add_unavailability(other, 1, dt(5, 9), dt(5, 17))

        with pytest.raises(LookupError):
            update_unavailability(venue, block.id, end=dt(5, 12))
        with pytest.raises(LookupError):
            update_unavailability(venue, 9999, end=dt(5, 12))


class TestFindUnavailabilityOverlap:
    def test_overlapping_period_is_found(self, app):
        venue = _venue()
        block, _ = add_unavailability(venue, 1, dt(5, 9), dt(5, 17))

        assert find_unavailability_overlap(venue.id, dt(5, 16), dt(5, 18)).id == block.id

    def test_touching_boundaries_do_not_overlap(self, app):
        venue = _venue()
        add_unavailability(venue, 1, dt(5, 9), dt(5, 17))

        assert find_unavailability_overlap(venue.id, dt(5, 17), dt(5, 19)) is None
        assert find_unavailability_overlap(venue.id, dt(5, 7), dt(5, 9)) is None

    def test_other_venues_periods_are_ignored(self, app):
        venue, other = _venue(name="A"), _venue(name="B")
        add_unavailability(other, 1, dt(5, 9), dt(5, 17))

        assert find_unavailability_overlap(venue.id, dt(5, 10), dt(5, 12)) is None

    def test_earliest_overlapping_period_is_returned(self, app):
        venue = _venue()
        add_unavailability(venue, 1, dt(5, 14), dt(5, 16), "Later")
        add_unavailability(venue, 1, dt(5, 9), dt(5, 11), "Earlier")

        assert find_unavailability_overlap(venue.id, dt(5, 8), dt(5, 18)).reason == "Earlier"


class TestApprovalRespectsUnavailability:
    def test_pending_request_inside_a_blocked_period_is_refused(self, app):
        venue = _venue(created_by=7)
        booking = _booking(venue, dt(5, 10), dt(5, 12), status=BOOKING_PENDING)
        add_unavailability(venue, 1, dt(5, 9), dt(5, 17), "Roof repairs")

        with pytest.raises(ValueError, match="unavailable.*Roof repairs"):
            approve_booking(booking, decided_by=7)

        assert VenueBooking.query.get(booking.id).status == BOOKING_PENDING

    def test_request_outside_the_blocked_period_is_approved(self, app):
        venue = _venue(created_by=7)
        booking = _booking(venue, dt(6, 10), dt(6, 12), status=BOOKING_PENDING)
        add_unavailability(venue, 1, dt(5, 9), dt(5, 17))

        assert approve_booking(booking, decided_by=7).status == BOOKING_APPROVED

    def test_setup_time_counts_towards_the_blocked_period(self, app):
        venue = _venue(created_by=7, setup_minutes=30)
        clash = _booking(venue, dt(5, 10, 30), dt(5, 12), status=BOOKING_PENDING)  # needs the room from 10:00
        add_unavailability(venue, 1, dt(5, 9), dt(5, 10, 15))

        with pytest.raises(ValueError, match="unavailable"):
            approve_booking(clash, decided_by=7)

    def test_a_period_ending_exactly_when_setup_starts_is_fine(self, app):
        venue = _venue(created_by=7, setup_minutes=30)
        fine = _booking(venue, dt(5, 10, 30), dt(5, 12), status=BOOKING_PENDING)  # needs the room from 10:00
        add_unavailability(venue, 1, dt(5, 9), dt(5, 10))

        assert approve_booking(fine, decided_by=7).status == BOOKING_APPROVED

    def test_removing_the_period_allows_approval_again(self, app):
        venue = _venue(created_by=7)
        booking = _booking(venue, dt(5, 10), dt(5, 12), status=BOOKING_PENDING)
        block, _ = add_unavailability(venue, 1, dt(5, 9), dt(5, 17))
        remove_unavailability(venue, block.id)

        assert approve_booking(booking, decided_by=7).status == BOOKING_APPROVED


class TestDescribeFlag:
    def _flagged(self, coordinator_id=None):
        venue = _venue(name="Main Hall")
        booking = _booking(venue, dt(5, 10), dt(5, 12), coordinator_id=coordinator_id)
        block, flags = add_unavailability(venue, 1, dt(5, 9), dt(5, 17), "Roof repairs")
        return venue, booking, block, flags[0]

    def test_includes_event_venue_booking_and_the_unavailable_period(self, app):
        venue, booking, block, flag = self._flagged()

        info = describe_flag(flag)

        assert info["eventName"] == "Event" and info["venueName"] == "Main Hall"
        assert info["bookingId"] == booking.id
        assert (info["bookingStart"], info["bookingEnd"]) == ("2026-12-05T10:00:00", "2026-12-05T12:00:00")
        assert info["reason"] == "Roof repairs"
        assert [p["id"] for p in info["unavailablePeriods"]] == [block.id]

    def test_only_periods_that_overlap_the_booking_are_listed(self, app):
        venue, _, block, flag = self._flagged()
        add_unavailability(venue, 1, dt(20, 9), dt(20, 17), "Unrelated")

        assert [p["id"] for p in describe_flag(flag)["unavailablePeriods"]] == [block.id]

    def test_period_disappears_once_it_is_removed(self, app):
        venue, _, block, flag = self._flagged()
        remove_unavailability(venue, block.id)

        assert describe_flag(flag)["unavailablePeriods"] == []

    def test_flag_still_describes_itself_after_the_booking_is_gone(self, app):
        venue, booking, _, flag = self._flagged()
        VenueBooking.query.filter_by(id=booking.id).update({"status": BOOKING_CANCELLED})
        db.session.commit()

        info = describe_flag(flag)

        assert info["bookingId"] is None and info["unavailablePeriods"] == []
        assert info["eventName"] == "Event"


class TestFlagsResolvedWhenBookingIsCancelled:
    def test_resolve_flags_for_booking_only_touches_that_event_and_venue(self, app):
        venue = _venue()
        mine = _booking(venue, dt(5, 10), dt(5, 12))
        other = _booking(venue, dt(6, 10), dt(6, 12))
        add_flag_once(mine.event_id, venue.id, "Repairs")
        add_flag_once(other.event_id, venue.id, "Repairs")
        db.session.commit()

        assert resolve_flags_for_booking(mine.event_id, venue.id) == 1
        db.session.commit()

        assert VenueAvailabilityFlag.query.filter_by(event_id=mine.event_id).one().resolved is True
        assert VenueAvailabilityFlag.query.filter_by(event_id=other.event_id).one().resolved is False

    def test_cancelling_the_booking_closes_its_flags_and_frees_the_venue(self, app):
        venue = _venue(created_by=7)
        booking = _booking(venue, dt(5, 10), dt(5, 12), coordinator_id=3)

        # Create a flag independently so the booking remains approved
        # and can be cancelled through the normal cancellation process.
        add_flag_once(booking.event_id, venue.id, "Roof repairs")
        db.session.commit()

        assert len(list_unresolved_flags_for_coordinator(3)) == 1

        cancel_booking(booking, decided_by=7, reason="Venue unavailable")

        assert VenueBooking.query.get(booking.id).status == BOOKING_CANCELLED
        assert list_unresolved_flags_for_coordinator(3) == []
        assert get_calendar(venue.id, dt(5, 0), dt(6, 0))["confirmedBookings"] == []

    def test_event_information_is_preserved_when_the_booking_is_cancelled(self, app):
        venue = _venue(created_by=7)
        booking = _booking(venue, dt(5, 10), dt(5, 12), coordinator_id=3)
        event = db.session.get(Event, booking.event_id)
        name, date_before = event.name, event.proposed_date

        cancel_booking(booking, decided_by=7)

        db.session.refresh(event)
        assert event.name == name and event.proposed_date == date_before
        assert event.status != "cancelled"


class TestHoldsRespectUnavailability:
    """Tentative holds (Week 7 change #4) must not be able to reserve a closed venue."""

    def test_a_hold_cannot_be_placed_inside_an_unavailable_period(self, app):
        venue = _venue(created_by=7)
        booking = _booking(venue, dt(5, 10), dt(5, 12), status=BOOKING_PENDING)
        add_unavailability(venue, 1, dt(5, 9), dt(5, 17), "Roof repairs")

        with pytest.raises(ValueError, match="unavailable.*Roof repairs"):
            manage_hold(booking.id, 7, "place", utcnow() + timedelta(days=1))

        assert VenueBooking.query.get(booking.id).status == BOOKING_PENDING

    def test_a_hold_outside_the_period_is_still_allowed(self, app):
        venue = _venue(created_by=7)
        booking = _booking(venue, dt(6, 10), dt(6, 12), status=BOOKING_PENDING)
        add_unavailability(venue, 1, dt(5, 9), dt(5, 17))

        held = manage_hold(booking.id, 7, "place", utcnow() + timedelta(days=1))

        assert held.status == BOOKING_HELD

    def test_a_held_booking_cannot_be_approved_once_its_time_is_blocked(self, app):
        venue = _venue(created_by=7)
        booking = _booking(venue, dt(5, 10), dt(5, 12), status=BOOKING_PENDING)
        manage_hold(booking.id, 7, "place", utcnow() + timedelta(days=1))
        add_unavailability(venue, 1, dt(5, 9), dt(5, 17), "Roof repairs")

        with pytest.raises(ValueError, match="unavailable"):
            approve_booking(booking, decided_by=7)

        assert VenueBooking.query.get(booking.id).status == BOOKING_HELD



# ---------------------------------------------------------------------------
# Week 7 change #1: approving a booking counts setup and turnaround time
# ---------------------------------------------------------------------------
class TestApprovalUsesSetupAndTurnaround:
    def test_a_booking_starting_inside_the_previous_turnaround_is_refused(self, app):
        venue = _venue(created_by=7, turnaround_minutes=30)
        _booking(venue, dt(1, 10), dt(1, 12))  # venue is busy until 12:30
        too_early = _booking(venue, dt(1, 12, 15), dt(1, 13), status=BOOKING_PENDING)

        with pytest.raises(ValueError, match="Conflicts"):
            approve_booking(too_early, decided_by=7)

        assert VenueBooking.query.get(too_early.id).status == BOOKING_PENDING

    def test_a_booking_starting_when_the_turnaround_ends_is_approved(self, app):
        venue = _venue(created_by=7, turnaround_minutes=30)
        _booking(venue, dt(1, 10), dt(1, 12))
        on_time = _booking(venue, dt(1, 12, 30), dt(1, 13), status=BOOKING_PENDING)

        assert approve_booking(on_time, decided_by=7).status == BOOKING_APPROVED

    def test_the_new_bookings_own_setup_time_counts(self, app):
        venue = _venue(created_by=7, setup_minutes=30)
        _booking(venue, dt(1, 10), dt(1, 12))
        clash = _booking(venue, dt(1, 12, 15), dt(1, 13), status=BOOKING_PENDING)  # needs the room from 11:45

        with pytest.raises(ValueError, match="Conflicts"):
            approve_booking(clash, decided_by=7)

    def test_the_week_7_example_blocks_0930_to_1245(self, app):
        venue = _venue(created_by=7, setup_minutes=30, turnaround_minutes=45)
        _booking(venue, dt(1, 10), dt(1, 12))  # occupies the venue 09:30-12:45
        inside = _booking(venue, dt(1, 13), dt(1, 14), status=BOOKING_PENDING)  # needs it from 12:30
        clear = _booking(venue, dt(1, 13, 30), dt(1, 14), status=BOOKING_PENDING)  # needs it from 13:00

        with pytest.raises(ValueError, match="Conflicts"):
            approve_booking(inside, decided_by=7)
        assert approve_booking(clear, decided_by=7).status == BOOKING_APPROVED

    def test_bookings_that_exactly_touch_are_both_approved(self, app):
        venue = _venue(created_by=7)
        _booking(venue, dt(1, 10), dt(1, 12))
        next_one = _booking(venue, dt(1, 12), dt(1, 14), status=BOOKING_PENDING)

        assert approve_booking(next_one, decided_by=7).status == BOOKING_APPROVED