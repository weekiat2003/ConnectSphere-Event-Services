"""Unit tests for the Venue Catalogue service (app/venues/services/catalogue.py)
and the suitability check.

Stories covered: create / edit / deactivate a venue record, specify supported
layouts, and the validation rules from the acceptance criteria. Pure logic
(validation, list syncing, suitability) is tested without a database; the rest
calls the service functions directly against the in-memory test database.
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
    BOOKING_WITHDRAWN,
    Venue,
    VenueBooking,
)
from app.venues.services.catalogue import (
    _sync_names,
    _validate,
    create_venue,
    deactivate_venue,
    get_venue,
    list_venues,
    update_venue,
)
from app.venues.services.suitability import check_suitability

VALID = {"name": "Grand Hall", "capacity": 100}


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


def _booking(venue, start, end, status=BOOKING_APPROVED, **event_fields):
    event = Event(
        name="Event",
        organiser_id=1,
        proposed_date=start.date(),
        proposed_time=start.time(),
        **event_fields,
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
# _validate: create rules (pure, no database)
# ---------------------------------------------------------------------------
class TestValidateForCreate:
    def test_minimal_valid_input_gets_defaults(self):
        clean = _validate(VALID, partial=False)

        assert clean["name"] == "Grand Hall"
        assert clean["capacity"] == 100
        assert clean["setupMinutes"] == 0
        assert clean["turnaroundMinutes"] == 0
        assert clean["facilities"] == []
        assert clean["supportedLayouts"] == []
        assert clean["accessibilityFeatures"] == []

    def test_name_is_stripped(self):
        assert _validate({**VALID, "name": "  Hall  "}, partial=False)["name"] == "Hall"

    @pytest.mark.parametrize("name", ["", None, "   ", "\t\n", 123, ["Hall"]])
    def test_blank_or_non_text_name_rejected(self, name):
        with pytest.raises(ValueError, match="name"):
            _validate({**VALID, "name": name}, partial=False)

    def test_missing_name_rejected(self):
        with pytest.raises(ValueError, match="name"):
            _validate({"capacity": 10}, partial=False)

    @pytest.mark.parametrize("capacity", [0, -1, -500])
    def test_zero_or_negative_capacity_rejected(self, capacity):
        with pytest.raises(ValueError, match="greater than zero"):
            _validate({**VALID, "capacity": capacity}, partial=False)

    @pytest.mark.parametrize("capacity", [None, ""])
    def test_blank_capacity_rejected(self, capacity):
        with pytest.raises(ValueError, match="required"):
            _validate({**VALID, "capacity": capacity}, partial=False)

    @pytest.mark.parametrize("capacity", ["abc", "12", 12.5, True, [], {}])
    def test_non_integer_capacity_rejected(self, capacity):
        with pytest.raises(ValueError, match="whole number"):
            _validate({**VALID, "capacity": capacity}, partial=False)

    def test_capacity_of_one_is_the_smallest_allowed(self):
        assert _validate({**VALID, "capacity": 1}, partial=False)["capacity"] == 1

    @pytest.mark.parametrize("key", ["setupMinutes", "turnaroundMinutes"])
    def test_negative_times_rejected(self, key):
        with pytest.raises(ValueError, match="negative"):
            _validate({**VALID, key: -1}, partial=False)

    @pytest.mark.parametrize("key", ["setupMinutes", "turnaroundMinutes"])
    def test_zero_times_allowed(self, key):
        assert _validate({**VALID, key: 0}, partial=False)[key] == 0

    @pytest.mark.parametrize("key", ["setupMinutes", "turnaroundMinutes"])
    @pytest.mark.parametrize("value", ["abc", "5", 2.5, True])
    def test_non_integer_times_rejected(self, key, value):
        with pytest.raises(ValueError, match="whole number"):
            _validate({**VALID, key: value}, partial=False)

    def test_none_times_become_zero(self):
        clean = _validate({**VALID, "setupMinutes": None, "turnaroundMinutes": None}, partial=False)

        assert clean["setupMinutes"] == 0 and clean["turnaroundMinutes"] == 0


class TestValidateLists:
    def test_facilities_stripped_and_deduplicated_ignoring_case(self):
        clean = _validate({**VALID, "facilities": [" Wifi ", "wifi", "", "Projector"]}, partial=False)

        assert clean["facilities"] == ["Wifi", "Projector"]

    def test_layouts_are_lowercased_so_matching_is_consistent(self):
        clean = _validate({**VALID, "supportedLayouts": ["Theatre ", "THEATRE", "Banquet"]}, partial=False)

        assert clean["supportedLayouts"] == ["theatre", "banquet"]

    def test_none_list_becomes_empty(self):
        assert _validate({**VALID, "facilities": None}, partial=False)["facilities"] == []

    @pytest.mark.parametrize("value", ["wifi", 5, {"a": 1}, [1, 2], ["ok", 3]])
    def test_non_list_or_non_text_items_rejected(self, value):
        with pytest.raises(ValueError, match="list of text"):
            _validate({**VALID, "accessibilityFeatures": value}, partial=False)


class TestValidateForUpdate:
    def test_empty_update_is_valid_and_changes_nothing(self):
        assert _validate({}, partial=True) == {}

    def test_only_present_fields_are_checked(self):
        assert _validate({"capacity": 5}, partial=True) == {"capacity": 5}

    def test_present_but_blank_name_rejected(self):
        with pytest.raises(ValueError, match="name"):
            _validate({"name": "  "}, partial=True)

    def test_capacity_rules_apply_on_update(self):
        with pytest.raises(ValueError, match="greater than zero"):
            _validate({"capacity": 0}, partial=True)

    def test_negative_time_rejected_on_update(self):
        with pytest.raises(ValueError, match="Setup time"):
            _validate({"setupMinutes": -5}, partial=True)


# ---------------------------------------------------------------------------
# _sync_names: keeps a table-backed list equal to the requested names
# ---------------------------------------------------------------------------
class TestSyncNames:
    def test_adds_missing_names(self):
        items = ["a"]
        _sync_names(items, ["a", "b"])

        assert items == ["a", "b"]

    def test_removes_names_no_longer_wanted(self):
        items = ["a", "b", "c"]
        _sync_names(items, ["b"])

        assert items == ["b"]

    def test_keeps_unchanged_entries_in_place(self):
        items = ["a", "b"]
        _sync_names(items, ["b", "c"])

        assert sorted(items) == ["b", "c"]

    def test_comparison_ignores_case_so_nothing_is_duplicated(self):
        items = ["Wifi"]
        _sync_names(items, ["wifi", "Projector"])

        assert items == ["Wifi", "Projector"]

    def test_empty_target_clears_the_list(self):
        items = ["a", "b"]
        _sync_names(items, [])

        assert items == []

    def test_is_idempotent(self):
        items = ["a"]
        _sync_names(items, ["a", "b"])
        _sync_names(items, ["a", "b"])

        assert items == ["a", "b"]


# ---------------------------------------------------------------------------
# create_venue
# ---------------------------------------------------------------------------
class TestCreateVenue:
    def test_creates_an_active_venue_with_creator(self, app):
        venue = create_venue(7, {**VALID, "location": "Block A"})

        assert venue.id is not None
        assert venue.is_active is True
        assert venue.created_by == 7
        assert venue.location == "Block A"

    def test_input_cannot_make_the_venue_inactive(self, app):
        venue = create_venue(1, {**VALID, "isActive": False, "is_active": False})

        assert venue.is_active is True

    def test_optional_fields_default_to_empty(self, app):
        venue = create_venue(1, VALID)

        assert venue.location is None
        assert venue.operating_hours is None
        assert list(venue.facilities) == []
        assert list(venue.supported_layouts) == []
        assert list(venue.accessibility_features) == []

    def test_all_fields_are_stored(self, app):
        venue = create_venue(
            1,
            {
                "name": "Hall",
                "capacity": 80,
                "location": "Block A",
                "description": "Main hall",
                "operatingHours": "08:00-22:00",
                "setupMinutes": 30,
                "turnaroundMinutes": 45,
                "facilities": ["projector", "wifi"],
                "supportedLayouts": ["Theatre", "banquet"],
                "accessibilityFeatures": ["ramp"],
            },
        )

        assert venue.description == "Main hall"
        assert venue.operating_hours == "08:00-22:00"
        assert (venue.setup_minutes, venue.turnaround_minutes) == (30, 45)
        assert sorted(venue.facilities) == ["projector", "wifi"]
        assert sorted(venue.supported_layouts) == ["banquet", "theatre"]
        assert list(venue.accessibility_features) == ["ramp"]

    def test_duplicate_name_and_location_create_separate_records(self, app):
        first = create_venue(1, {**VALID, "location": "Block A"})
        second = create_venue(1, {**VALID, "location": "Block A"})

        assert first.id != second.id
        assert Venue.query.count() == 2

    @pytest.mark.parametrize(
        "bad",
        [
            {"name": ""},
            {"capacity": 0},
            {"capacity": -3},
            {"setupMinutes": -1},
            {"turnaroundMinutes": -1},
        ],
    )
    def test_invalid_input_saves_nothing(self, app, bad):
        with pytest.raises(ValueError):
            create_venue(1, {**VALID, **bad})

        assert Venue.query.count() == 0


# ---------------------------------------------------------------------------
# update_venue
# ---------------------------------------------------------------------------
class TestUpdateVenue:
    def test_changes_only_the_fields_sent(self, app):
        venue = _venue(name="Old", capacity=100, location="Block A")

        updated, flags = update_venue(venue, {"name": "New"})

        assert updated.name == "New"
        assert updated.capacity == 100 and updated.location == "Block A"
        assert flags == []

    def test_invalid_edit_is_rejected_and_nothing_changes(self, app):
        venue = _venue(name="Hall", capacity=100)

        with pytest.raises(ValueError):
            update_venue(venue, {"name": "Changed", "capacity": 0})

        db.session.refresh(venue)
        assert venue.name == "Hall" and venue.capacity == 100

    def test_replaces_lists_by_adding_and_removing_only_the_difference(self, app):
        venue = _venue()
        update_venue(venue, {"facilities": ["wifi", "projector"], "supportedLayouts": ["theatre"]})

        update_venue(venue, {"facilities": ["wifi", "stage"], "supportedLayouts": []})

        db.session.refresh(venue)
        assert sorted(venue.facilities) == ["stage", "wifi"]
        assert list(venue.supported_layouts) == []

    def test_can_clear_optional_text_fields(self, app):
        venue = _venue(operating_hours="08:00-22:00")

        update_venue(venue, {"operatingHours": None})

        assert venue.operating_hours is None

    def test_capacity_drop_flags_a_confirmed_event_that_no_longer_fits(self, app):
        venue = _venue(capacity=100)
        booking = _booking(
            venue, datetime(2026, 12, 1, 10), datetime(2026, 12, 1, 12), expected_attendance=80
        )

        _, flags = update_venue(venue, {"capacity": 50})

        assert len(flags) == 1
        assert flags[0].event_id == booking.event_id
        assert "capacity" in flags[0].reason
        # the event itself is flagged, never cancelled or removed
        assert VenueBooking.query.get(booking.id).status == BOOKING_APPROVED

    def test_capacity_drop_that_still_fits_raises_no_flag(self, app):
        venue = _venue(capacity=100)
        _booking(venue, datetime(2026, 12, 1, 10), datetime(2026, 12, 1, 12), expected_attendance=40)

        _, flags = update_venue(venue, {"capacity": 50})

        assert flags == []

    def test_pending_booking_is_not_flagged(self, app):
        venue = _venue(capacity=100)
        _booking(
            venue,
            datetime(2026, 12, 1, 10),
            datetime(2026, 12, 1, 12),
            status=BOOKING_PENDING,
            expected_attendance=80,
        )

        _, flags = update_venue(venue, {"capacity": 50})

        assert flags == []

    def test_removing_a_required_layout_flags_the_event(self, app):
        venue = _venue()
        update_venue(venue, {"supportedLayouts": ["theatre"]})
        _booking(
            venue, datetime(2026, 12, 1, 10), datetime(2026, 12, 1, 12), required_layout="theatre"
        )

        _, flags = update_venue(venue, {"supportedLayouts": ["banquet"]})

        assert len(flags) == 1 and "layout" in flags[0].reason

    def test_timing_change_flags_both_events_that_now_overlap(self, app):
        venue = _venue(setup_minutes=0, turnaround_minutes=0)
        first = _booking(venue, datetime(2026, 12, 1, 10), datetime(2026, 12, 1, 12))
        second = _booking(venue, datetime(2026, 12, 1, 13), datetime(2026, 12, 1, 15))

        _, flags = update_venue(venue, {"turnaroundMinutes": 90})

        assert {f.event_id for f in flags} == {first.event_id, second.event_id}

    def test_timing_change_with_enough_gap_raises_no_flag(self, app):
        venue = _venue()
        _booking(venue, datetime(2026, 12, 1, 10), datetime(2026, 12, 1, 12))
        _booking(venue, datetime(2026, 12, 1, 15), datetime(2026, 12, 1, 17))

        _, flags = update_venue(venue, {"setupMinutes": 30, "turnaroundMinutes": 45})

        assert flags == []

    def test_unchanged_values_raise_no_flags(self, app):
        venue = _venue(capacity=100)
        _booking(venue, datetime(2026, 12, 1, 10), datetime(2026, 12, 1, 12), expected_attendance=80)

        _, flags = update_venue(venue, {"capacity": 100})

        assert flags == []


# ---------------------------------------------------------------------------
# deactivate_venue, list_venues, get_venue
# ---------------------------------------------------------------------------
class TestDeactivateAndList:
    def test_deactivates_a_venue_with_no_bookings(self, app):
        venue = _venue()

        result = deactivate_venue(venue)

        assert result.is_active is False

    @pytest.mark.parametrize("status", [BOOKING_APPROVED, BOOKING_PENDING])
    def test_active_bookings_block_deactivation(self, app, status):
        venue = _venue()
        _booking(venue, datetime(2026, 12, 1, 10), datetime(2026, 12, 1, 12), status=status)

        with pytest.raises(ValueError, match="active bookings"):
            deactivate_venue(venue)

        assert venue.is_active is True

    @pytest.mark.parametrize("status", [BOOKING_WITHDRAWN, BOOKING_REJECTED])
    def test_finished_bookings_do_not_block_deactivation(self, app, status):
        venue = _venue()
        _booking(venue, datetime(2026, 12, 1, 10), datetime(2026, 12, 1, 12), status=status)

        assert deactivate_venue(venue).is_active is False

    def test_list_excludes_inactive_by_default_and_sorts_by_name(self, app):
        _venue(name="Zeta")
        _venue(name="Alpha")
        _venue(name="Retired", is_active=False)

        assert [v.name for v in list_venues()] == ["Alpha", "Zeta"]

    def test_list_can_include_inactive(self, app):
        _venue(name="Alpha")
        _venue(name="Retired", is_active=False)

        assert [v.name for v in list_venues(active_only=False)] == ["Alpha", "Retired"]

    def test_get_venue_returns_none_for_unknown_id(self, app):
        assert get_venue(9999) is None

    def test_get_venue_returns_the_record(self, app):
        venue = _venue(name="Findable")

        assert get_venue(venue.id).name == "Findable"


# ---------------------------------------------------------------------------
# check_suitability (pure): advisory flags for matching an event to a venue
# ---------------------------------------------------------------------------
def _event(**kw):
    base = {"expected_attendance": None, "required_layout": None, "accessibility_needs": None}
    base.update(kw)
    return SimpleNamespace(**base)


def _suit_venue(**kw):
    base = {"capacity": 100, "supported_layouts": [], "accessibility_features": []}
    base.update(kw)
    return SimpleNamespace(**base)


class TestSuitabilityCheck:
    def test_no_requirements_means_no_flags(self):
        assert check_suitability(_event(), _suit_venue()) == []

    def test_attendance_over_capacity_is_flagged(self):
        flags = check_suitability(_event(expected_attendance=101), _suit_venue(capacity=100))

        assert len(flags) == 1 and "exceeds" in flags[0]

    def test_attendance_equal_to_capacity_is_fine(self):
        assert check_suitability(_event(expected_attendance=100), _suit_venue(capacity=100)) == []

    @pytest.mark.parametrize("required", ["theatre", "Theatre", "THEATRE", "  theatre "])
    def test_layout_match_ignores_case_and_spaces(self, required):
        venue = _suit_venue(supported_layouts=["theatre"])

        assert check_suitability(_event(required_layout=required), venue) == []

    def test_unsupported_layout_is_flagged(self):
        flags = check_suitability(
            _event(required_layout="classroom"), _suit_venue(supported_layouts=["theatre"])
        )

        assert len(flags) == 1 and "classroom" in flags[0]

    def test_accessibility_need_without_venue_features_is_flagged(self):
        flags = check_suitability(_event(accessibility_needs="wheelchair access"), _suit_venue())

        assert len(flags) == 1 and "accessibility" in flags[0]

    def test_accessibility_need_with_venue_features_is_fine(self):
        venue = _suit_venue(accessibility_features=["ramp"])

        assert check_suitability(_event(accessibility_needs="wheelchair access"), venue) == []

    @pytest.mark.parametrize("need", ["none", "None", "N/A", ""])
    def test_no_real_accessibility_need_is_not_flagged(self, need):
        assert check_suitability(_event(accessibility_needs=need), _suit_venue()) == []

    def test_several_problems_give_several_flags(self):
        flags = check_suitability(
            _event(expected_attendance=500, required_layout="banquet", accessibility_needs="ramp"),
            _suit_venue(capacity=100),
        )

        assert len(flags) == 3

# ---------------------------------------------------------------------------
# Operating hours as a suitability factor (advisory flag, event start time only:
# an Event stores a start time but no end time).

from datetime import time  # noqa: E402


class TestSuitabilityOperatingHours:
    HOURS = "08:00-22:00"

    def _flags(self, start, hours=HOURS, **venue_extra):
        return check_suitability(
            _event(proposed_time=start), _suit_venue(operating_hours=hours, **venue_extra)
        )

    def test_start_inside_hours_is_fine(self):
        assert self._flags(time(10)) == []

    def test_start_exactly_at_opening_is_fine(self):
        assert self._flags(time(8)) == []

    def test_start_before_opening_is_flagged_with_the_hours_in_the_message(self):
        flags = self._flags(time(7, 59))

        assert len(flags) == 1
        assert "07:59" in flags[0] and "08:00-22:00" in flags[0]

    def test_start_exactly_at_closing_is_flagged(self):
        assert len(self._flags(time(22))) == 1

    def test_start_after_closing_is_flagged(self):
        assert len(self._flags(time(23))) == 1

    def test_event_without_a_start_time_is_not_checked(self):
        assert check_suitability(_event(), _suit_venue(operating_hours=self.HOURS)) == []
        assert check_suitability(_event(proposed_time=None), _suit_venue(operating_hours=self.HOURS)) == []

    @pytest.mark.parametrize("hours", [None, "", "9am-5pm", "25:00-26:00", "22:00-06:00"])
    def test_venue_without_usable_hours_is_never_flagged(self, hours):
        assert self._flags(time(3), hours=hours) == []

    def test_setup_and_turnaround_time_are_not_counted_against_opening_hours(self):
        """Team decision: only the event's own start time is compared with the
        hours, so an 08:00 start at a venue opening at 08:00 is fine even with
        30 minutes of setup."""
        assert self._flags(time(8), setup_minutes=30, turnaround_minutes=45) == []

    def test_hours_flag_is_added_next_to_the_other_flags(self):
        flags = check_suitability(
            _event(expected_attendance=500, proposed_time=time(6)),
            _suit_venue(capacity=100, operating_hours=self.HOURS),
        )

        assert len(flags) == 2
        assert any("exceeds" in f for f in flags) and any("operating hours" in f for f in flags)
