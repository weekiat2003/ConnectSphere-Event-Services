from datetime import date, datetime

import pytest

from app.extensions import db
from app.models.event import Event
from app.models.venue import (
    BOOKING_APPROVED,
    BOOKING_PENDING,
    Venue,
    VenueBooking,
    VenueUnavailability,
)
from app.venues.services import search as search_service

SEARCH_DATE = date(2026, 10, 8)
VALID_PARAMS = {
    "date": SEARCH_DATE.isoformat(),
    "start_time": "10:00",
    "end_time": "12:00",
    "attendance": "50",
}


def _create_venue(app, name, capacity=50, **overrides):
    with app.app_context():
        values = {
            "location": "North Campus",
            "capacity": capacity,
            "is_active": True,
        }
        values.update(overrides)
        venue = Venue(
            name=name,
            **values,
        )
        db.session.add(venue)
        db.session.commit()
        return venue.id


def _create_booking(
    app, venue_id, coordinator_id, status, start, end
):
    with app.app_context():
        event = Event(
            name=f"{status.title()} event",
            organiser_id=coordinator_id,
            proposed_date=start.date(),
            proposed_time=start.time(),
        )
        db.session.add(event)
        db.session.flush()
        booking = VenueBooking(
            event_id=event.id,
            venue_id=venue_id,
            requested_by=coordinator_id,
            status=status,
            start_datetime=start,
            end_datetime=end,
        )
        db.session.add(booking)
        db.session.commit()
        return booking.id


def _request(client, auth_header, params=None):
    return client.get(
        "/api/venues/search",
        query_string=params if params is not None else VALID_PARAMS,
        headers=auth_header("coordinator@test.com", "password"),
    )


def test_search_endpoint_returns_only_available_suitable_venues_with_details(
    app, client, coordinator, auth_header
):
    exact_capacity_id = _create_venue(app, "Exact capacity", capacity=50)
    _create_venue(app, "Below capacity", capacity=49)
    blocked_id = _create_venue(app, "Approved booking")
    pending_id = _create_venue(app, "Pending booking")
    _create_booking(
        app,
        blocked_id,
        coordinator,
        BOOKING_APPROVED,
        datetime(2026, 10, 8, 11),
        datetime(2026, 10, 8, 13),
    )
    _create_booking(
        app,
        pending_id,
        coordinator,
        BOOKING_PENDING,
        datetime(2026, 10, 8, 11),
        datetime(2026, 10, 8, 13),
    )

    response = _request(client, auth_header)

    assert response.status_code == 200
    venues = response.get_json()
    assert [venue["id"] for venue in venues] == [exact_capacity_id, pending_id]
    assert venues[0]["name"] == "Exact capacity"
    assert venues[0]["location"] == "North Campus"
    assert venues[0]["capacity"] == 50


def test_search_endpoint_excludes_recorded_unavailability_and_returns_empty_array(
    app, client, coordinator, auth_header
):
    venue_id = _create_venue(app, "Maintenance")
    with app.app_context():
        db.session.add(
            VenueUnavailability(
                venue_id=venue_id,
                start_datetime=datetime(2026, 10, 8, 11),
                end_datetime=datetime(2026, 10, 8, 13),
                reason="Maintenance",
            )
        )
        db.session.commit()

    response = _request(client, auth_header)
    assert response.status_code == 200
    assert response.get_json() == []

    with app.app_context():
        VenueUnavailability.query.delete()
        db.session.commit()
    no_capacity_match = _request(
        client, auth_header, {**VALID_PARAMS, "attendance": "51"}
    )
    assert no_capacity_match.status_code == 200
    assert no_capacity_match.get_json() == []


def test_search_endpoint_combines_catalogue_filters_and_keeps_attendance_rule(
    app, client, coordinator, auth_header
):
    matching_id = _create_venue(
        app,
        "Matching",
        capacity=60,
        location="East Campus",
        facilities=["Projector", "Wi-Fi"],
        accessibility_features=["Step-free access", "Hearing loop"],
    )
    _create_venue(
        app,
        "Wrong location",
        capacity=60,
        location="West Campus",
        facilities=["Projector", "Wi-Fi"],
        accessibility_features=["Step-free access", "Hearing loop"],
    )
    _create_venue(
        app,
        "Missing required facility",
        capacity=60,
        location="East Campus",
        facilities=["Projector"],
        accessibility_features=["Step-free access", "Hearing loop"],
    )
    _create_venue(
        app,
        "Above maximum",
        capacity=81,
        location="East Campus",
        facilities=["Projector", "Wi-Fi"],
        accessibility_features=["Step-free access", "Hearing loop"],
    )
    _create_venue(
        app,
        "Below attendance",
        capacity=49,
        location="East Campus",
        facilities=["Projector", "Wi-Fi"],
        accessibility_features=["Step-free access", "Hearing loop"],
    )

    response = _request(
        client,
        auth_header,
        {
            **VALID_PARAMS,
            "location": "East Campus",
            "max_capacity": "80",
            "accessibility": ["Step-free access", "Hearing loop"],
            "facilities": ["Projector", "Wi-Fi"],
        },
    )

    assert response.status_code == 200
    venues = response.get_json()
    assert [venue["id"] for venue in venues] == [matching_id]
    assert venues[0]["facilities"] == ["Projector", "Wi-Fi"]
    assert venues[0]["accessibilityFeatures"] == ["Hearing loop", "Step-free access"]


def test_search_endpoint_rejects_maximum_below_attendance_instead_of_empty_results(
    client, coordinator, auth_header
):
    response = _request(
        client, auth_header, {**VALID_PARAMS, "max_capacity": "49"}
    )

    assert response.status_code == 400
    assert "maximum capacity" in response.get_json()["errors"]["max_capacity"].lower()


def test_search_endpoint_checks_maximum_against_out_of_range_attendance(
    client, coordinator, auth_header
):
    response = _request(
        client,
        auth_header,
        {
            **VALID_PARAMS,
            "attendance": "4294967296",
            "max_capacity": "4294967295",
        },
    )

    assert response.status_code == 400
    assert "max_capacity" in response.get_json()["errors"]


@pytest.mark.parametrize("max_capacity", ["0", "-1", "50.5", "abc"])
def test_search_endpoint_rejects_invalid_maximum_capacity(
    client, coordinator, auth_header, max_capacity
):
    response = _request(
        client, auth_header, {**VALID_PARAMS, "max_capacity": max_capacity}
    )

    assert response.status_code == 400
    assert "max_capacity" in response.get_json()["errors"]


def test_search_filter_options_come_from_active_venue_catalogue(
    app, client, coordinator, auth_header
):
    _create_venue(
        app,
        "First",
        location="East Campus",
        facilities=["Projector", "Wi-Fi"],
        accessibility_features=["Lift access"],
    )
    _create_venue(
        app,
        "Second",
        location="East Campus",
        facilities=["Projector", "Microphone"],
        accessibility_features=["Hearing loop"],
    )
    _create_venue(
        app,
        "Inactive",
        location="Closed Campus",
        is_active=False,
        facilities=["Unused"],
        accessibility_features=["Unused"],
    )

    response = client.get(
        "/api/venues/search/options",
        headers=auth_header("coordinator@test.com", "password"),
    )

    assert response.status_code == 200
    assert response.get_json() == {
        "locations": ["East Campus"],
        "facilities": ["Microphone", "Projector", "Wi-Fi"],
        "accessibilityFeatures": ["Hearing loop", "Lift access"],
        "layouts": [],

    }


def test_clearing_query_filters_returns_the_original_attendance_matches(
    app, client, coordinator, auth_header
):
    wanted_id = _create_venue(
        app,
        "Filtered venue",
        capacity=60,
        location="East Campus",
        facilities=["Projector"],
    )
    other_id = _create_venue(
        app,
        "Other venue",
        capacity=60,
        location="North Campus",
        facilities=["Whiteboard"],
    )

    filtered = _request(
        client,
        auth_header,
        {**VALID_PARAMS, "location": "East Campus", "facilities": ["Projector"]},
    )
    cleared = _request(client, auth_header, VALID_PARAMS)

    assert [venue["id"] for venue in filtered.get_json()] == [wanted_id]
    assert {venue["id"] for venue in cleared.get_json()} == {wanted_id, other_id}


@pytest.mark.parametrize("missing_field", ["date", "start_time", "end_time", "attendance"])
def test_search_endpoint_rejects_each_missing_required_field_without_search(
    client, coordinator, auth_header, monkeypatch, missing_field
):
    params = dict(VALID_PARAMS)
    params.pop(missing_field)
    monkeypatch.setattr(
        search_service,
        "search_venues",
        lambda *args, **kwargs: pytest.fail("search service must not run"),
    )

    response = _request(client, auth_header, params)

    assert response.status_code == 400
    assert missing_field in response.get_json()["errors"]


@pytest.mark.parametrize("blank_field", ["date", "start_time", "end_time", "attendance"])
def test_search_endpoint_rejects_blank_required_fields_without_search(
    client, coordinator, auth_header, monkeypatch, blank_field
):
    params = {**VALID_PARAMS, blank_field: "   "}
    monkeypatch.setattr(
        search_service,
        "search_venues",
        lambda *args, **kwargs: pytest.fail("search service must not run"),
    )

    response = _request(client, auth_header, params)

    assert response.status_code == 400
    assert blank_field in response.get_json()["errors"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("date", "not-a-date"),
        ("date", "2026-02-30"),
        ("start_time", "25:00"),
        ("end_time", "not-a-time"),
    ],
)
def test_search_endpoint_rejects_malformed_date_and_times(
    client, coordinator, auth_header, monkeypatch, field, value
):
    params = {**VALID_PARAMS, field: value}
    monkeypatch.setattr(
        search_service,
        "search_venues",
        lambda *args, **kwargs: pytest.fail("search service must not run"),
    )

    response = _request(client, auth_header, params)

    assert response.status_code == 400
    assert field in response.get_json()["errors"]


@pytest.mark.parametrize("end_time", ["10:00", "09:59"])
def test_search_endpoint_requires_end_time_strictly_after_start(
    client, coordinator, auth_header, monkeypatch, end_time
):
    monkeypatch.setattr(
        search_service,
        "search_venues",
        lambda *args, **kwargs: pytest.fail("search service must not run"),
    )

    response = _request(
        client,
        auth_header,
        {**VALID_PARAMS, "start_time": "10:00", "end_time": end_time},
    )

    assert response.status_code == 400
    assert "end_time" in response.get_json()["errors"]


@pytest.mark.parametrize("attendance", ["", "0", "-1", "50.5", "abc"])
def test_search_endpoint_rejects_missing_or_non_positive_integer_attendance(
    client, coordinator, auth_header, monkeypatch, attendance
):
    monkeypatch.setattr(
        search_service,
        "search_venues",
        lambda *args, **kwargs: pytest.fail("search service must not run"),
    )

    response = _request(
        client, auth_header, {**VALID_PARAMS, "attendance": attendance}
    )

    assert response.status_code == 400
    assert "attendance" in response.get_json()["errors"]


def test_search_endpoint_accepts_positive_attendance_above_arbitrary_old_cap(
    client, coordinator, auth_header
):
    response = _request(
        client, auth_header, {**VALID_PARAMS, "attendance": "100001"}
    )

    assert response.status_code == 200
    assert response.get_json() == []


@pytest.mark.parametrize(
    "attendance",
    ["9223372036854775808", "9" * 5000],
)
def test_search_endpoint_returns_no_matches_for_attendance_above_database_capacity_range(
    client, coordinator, auth_header, attendance
):
    response = _request(
        client,
        auth_header,
        {**VALID_PARAMS, "attendance": attendance},
    )

    assert response.status_code == 200
    assert response.get_json() == []


def test_search_endpoint_requires_coordinator_authentication(client):
    response = client.get("/api/venues/search", query_string=VALID_PARAMS)

    assert response.status_code == 401

# =====================================================================
# Story 2 follow-up fixes (integration): paste at the bottom of
# tests/integration/test_venue_search_api.py
# =====================================================================
@pytest.mark.parametrize("param", ["facilities", "accessibility", "layout"])
@pytest.mark.parametrize("blank", ["", "   "])
def test_s2_blank_filter_values_are_ignored_not_treated_as_no_match(
    app, client, coordinator, auth_header, param, blank
):
    _create_venue(app, "Hall", facilities=["Projector"], accessibility_features=["Lift"])

    response = _request(client, auth_header, {**VALID_PARAMS, param: blank})

    assert [v["name"] for v in response.get_json()] == ["Hall"]


def test_s2_filter_values_are_trimmed_and_deduplicated(
    app, client, coordinator, auth_header
):
    _create_venue(app, "Hall", facilities=["Projector"])

    response = _request(
        client, auth_header, {**VALID_PARAMS, "facilities": [" Projector", "Projector "]}
    )

    assert [v["name"] for v in response.get_json()] == ["Hall"]


def test_s2_api_free_text_accessibility_info_is_not_offered_as_an_option(
    app, client, coordinator, auth_header
):
    _create_venue(app, "Text only", accessibility_info="Wheelchair accessible, hearing loop")
    _create_venue(app, "Structured", accessibility_features=["Lift access"])

    response = client.get(
        "/api/venues/search/options",
        headers=auth_header("coordinator@test.com", "password"),
    )

    assert response.get_json()["accessibilityFeatures"] == ["Lift access"]


def test_s2_api_filtering_is_case_insensitive(app, client, coordinator, auth_header):
    _create_venue(app, "Hall", facilities=["Projector"], location="North Campus")

    response = _request(
        client, auth_header,
        {**VALID_PARAMS, "facilities": "projector", "location": "NORTH CAMPUS"},
    )

    assert [v["name"] for v in response.get_json()] == ["Hall"]


    # =====================================================================
# Story 3: filter venues by supported room layout (HTTP level)
# =====================================================================
def _names_of(response):
    assert response.status_code == 200, response.get_json()
    return [v["name"] for v in response.get_json()]


def test_s3_ac1_api_returns_only_venues_supporting_the_selected_layout(
    app, client, coordinator, auth_header
):
    _create_venue(app, "Theatre hall", supported_layouts=["Theatre"])
    _create_venue(app, "Classroom only", supported_layouts=["Classroom"])

    response = _request(client, auth_header, {**VALID_PARAMS, "layout": "Theatre"})

    assert _names_of(response) == ["Theatre hall"]


@pytest.mark.parametrize(
    ("layout", "expected"),
    [
        (" tHeAtRe ", ["Theatre hall"]),
        ("Unlisted layout", []),
    ],
)
def test_s3_ac1_api_trims_layout_and_returns_no_matches_for_unknown_layout(
    app, client, coordinator, auth_header, layout, expected
):
    _create_venue(app, "Theatre hall", supported_layouts=["Theatre"])

    response = _request(client, auth_header, {**VALID_PARAMS, "layout": layout})

    assert _names_of(response) == expected


def test_s3_ac1_api_layout_options_come_from_the_catalogue(
    app, client, coordinator, auth_header
):
    _create_venue(app, "A", supported_layouts=["Theatre", "Classroom"])
    _create_venue(app, "Inactive", is_active=False, supported_layouts=["Secret"])

    response = client.get(
        "/api/venues/search/options",
        headers=auth_header("coordinator@test.com", "password"),
    )

    assert response.status_code == 200
    assert response.get_json()["layouts"] == ["Classroom", "Theatre"]


def test_s3_ac2_api_each_result_lists_all_supported_layouts(
    app, client, coordinator, auth_header
):
    _create_venue(app, "Flexible", supported_layouts=["Theatre", "Classroom", "U-shape"])

    for selected in ("Theatre", "Classroom", "U-shape"):
        response = _request(client, auth_header, {**VALID_PARAMS, "layout": selected})
        (venue,) = response.get_json()
        assert venue["name"] == "Flexible"
        assert venue["supportedLayouts"] == ["Classroom", "Theatre", "U-shape"]


def test_s3_ac3_api_layout_combines_with_all_other_filters(
    app, client, coordinator, auth_header
):
    full = dict(
        capacity=60,
        location="East Campus",
        facilities=["Projector"],
        accessibility_features=["Hearing loop"],
        supported_layouts=["Theatre"],
    )
    _create_venue(app, "Matches everything", **full)
    _create_venue(app, "Wrong layout", **{**full, "supported_layouts": ["Classroom"]})
    _create_venue(app, "Wrong location", **{**full, "location": "West Campus"})
    _create_venue(app, "Missing facility", **{**full, "facilities": []})
    _create_venue(app, "Over max capacity", **{**full, "capacity": 500})

    response = _request(
        client,
        auth_header,
        {
            **VALID_PARAMS,
            "layout": "Theatre",
            "location": "East Campus",
            "max_capacity": "100",
            "facilities": ["Projector"],
            "accessibility": ["Hearing loop"],
        },
    )

    assert _names_of(response) == ["Matches everything"]


def test_s3_ac3_api_layout_does_not_return_venues_with_an_approved_booking(
    app, client, coordinator, auth_header
):
    booked_id = _create_venue(app, "Booked", supported_layouts=["Theatre"])
    _create_venue(app, "Free", supported_layouts=["Theatre"])
    _create_booking(
        app, booked_id, coordinator, BOOKING_APPROVED,
        datetime(2026, 10, 8, 10), datetime(2026, 10, 8, 12),
    )

    response = _request(client, auth_header, {**VALID_PARAMS, "layout": "Theatre"})

    assert _names_of(response) == ["Free"]


def test_s3_ac3_api_max_capacity_below_attendance_still_returns_an_error_with_layout(
    app, client, coordinator, auth_header
):
    _create_venue(app, "Theatre hall", supported_layouts=["Theatre"])

    response = _request(
        client, auth_header, {**VALID_PARAMS, "layout": "Theatre", "max_capacity": "10"}
    )

    assert response.status_code == 400
    assert "max_capacity" in response.get_json()["errors"]


@pytest.mark.parametrize("blank", ["", "   "])
def test_s3_ac4_api_blank_or_missing_layout_applies_no_restriction(
    app, client, coordinator, auth_header, blank
):
    _create_venue(app, "Theatre hall", supported_layouts=["Theatre"])
    _create_venue(app, "No layouts recorded")

    without = _names_of(_request(client, auth_header, VALID_PARAMS))
    with_blank = _names_of(_request(client, auth_header, {**VALID_PARAMS, "layout": blank}))

    assert without == with_blank == ["No layouts recorded", "Theatre hall"]


def test_s3_ac4_api_venue_staff_edit_is_reflected_in_the_next_search_and_options(
    app, client, coordinator, make_user, auth_header
):
    venue_id = _create_venue(
        app,
        "Hall",
        location="Old Campus",
        facilities=["Old projector"],
        accessibility_features=["Old access feature"],
        supported_layouts=["theatre", "classroom"],
    )
    with app.app_context():
        make_user("staff@test.com", ["venue_staff"])
    staff = auth_header("staff@test.com")

    assert _names_of(_request(client, auth_header, {**VALID_PARAMS, "layout": "Classroom"})) == ["Hall"]

    edit = client.put(
        f"/api/venues/{venue_id}",
        json={
            "location": "New Campus",
            "facilities": ["New projector"],
            "accessibilityFeatures": ["Step-free access"],
            "supportedLayouts": ["Banquet"],
        },
        headers=staff,
    )
    assert edit.status_code == 200, edit.get_json()
    assert edit.get_json()["venue"]["supportedLayouts"] == ["banquet"]

    assert _names_of(_request(client, auth_header, {**VALID_PARAMS, "layout": "Classroom"})) == []
    assert _names_of(_request(client, auth_header, {**VALID_PARAMS, "layout": "Banquet"})) == ["Hall"]
    updated_search = _request(
        client,
        auth_header,
        {
            **VALID_PARAMS,
            "layout": "Banquet",
            "location": "New Campus",
            "facilities": ["New projector"],
            "accessibility": ["Step-free access"],
        },
    )
    assert _names_of(updated_search) == ["Hall"]

    options_response = client.get(
        "/api/venues/search/options",
        headers=auth_header("coordinator@test.com", "password"),
    )
    assert options_response.status_code == 200
    assert options_response.get_json() == {
        "locations": ["New Campus"],
        "facilities": ["New projector"],
        "accessibilityFeatures": ["Step-free access"],
        "layouts": ["banquet"],
    }


def test_s3_ac4_api_venue_staff_can_create_a_venue_whose_layouts_are_searchable(
    app, client, coordinator, make_user, auth_header
):
    with app.app_context():
        make_user("staff@test.com", ["venue_staff"])

    created = client.post(
        "/api/venues",
        json={"name": "Brand new", "location": "North Campus", "capacity": 80,
              "supportedLayouts": ["Boardroom"]},
        headers=auth_header("staff@test.com"),
    )
    assert created.status_code == 201, created.get_json()

    response = _request(client, auth_header, {**VALID_PARAMS, "layout": "Boardroom"})
    assert _names_of(response) == ["Brand new"]