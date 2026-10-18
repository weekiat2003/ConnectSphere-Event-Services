"""Tests for the user story:

  As a Venue Staff member, I want to create a new venue record with location,
  capacity, facilities, accessibility, supported layouts, and operating hours,
  so that it can be considered for event bookings.

Each test is tagged with the acceptance criterion it covers (AC1..AC6) so it can
be traced back to the story. Endpoint: POST /api/venues, GET /api/venues.
"""
import pytest

from app.models.venue import Venue
from app.venues import services  # noqa: F401  (ensures package imports cleanly)
from app.venues.services import catalogue

URL = "/api/venues"


# The project's tests/conftest.py already provides: app, client, make_user, auth_header.
@pytest.fixture()
def staff_headers(make_user, auth_header):
    make_user("staff@test.com", ["venue_staff"])
    return auth_header("staff@test.com")


@pytest.fixture()
def coordinator_headers(make_user, auth_header):
    make_user("coord@test.com", ["event_coordinator"])
    return auth_header("coord@test.com")


@pytest.fixture()
def staff_id(make_user):
    return make_user("staff2@test.com", ["venue_staff"])


def valid_payload(**overrides):
    payload = {
        "name": "Grand Hall",
        "location": "1 Main Street",
        "capacity": 200,
        "facilities": ["projector", "wifi"],
        "accessibilityFeatures": ["wheelchair ramp"],
        "supportedLayouts": ["theatre", "banquet"],
        "operatingHours": "08:00-22:00",
        "setupMinutes": 30,
        "turnaroundMinutes": 15,
    }
    payload.update(overrides)
    return payload


def venue_count():
    return Venue.query.count()


def create(client, headers, **overrides):
    return client.post(URL, json=valid_payload(**overrides), headers=headers)


# ---------------------------------------------------------------------------
# Happy path (story main flow)
# ---------------------------------------------------------------------------
class TestCreateVenueHappyPath:
    def test_staff_can_create_venue_with_all_fields(self, client, staff_headers):
        resp = create(client, staff_headers)

        assert resp.status_code == 201
        body = resp.get_json()
        assert body["id"] is not None
        assert body["name"] == "Grand Hall"
        assert body["location"] == "1 Main Street"
        assert body["capacity"] == 200
        assert body["operatingHours"] == "08:00-22:00"

    def test_all_fields_are_persisted(self, client, staff_headers):
        venue_id = create(client, staff_headers).get_json()["id"]

        venue = Venue.query.get(venue_id)
        # table-backed lists come back sorted by name
        assert sorted(venue.facilities) == ["projector", "wifi"]
        assert sorted(venue.accessibility_features) == ["wheelchair ramp"]
        assert sorted(venue.supported_layouts) == ["banquet", "theatre"]
        assert venue.setup_minutes == 30
        assert venue.turnaround_minutes == 15

    def test_minimum_valid_capacity_of_one(self, client, staff_headers):  # boundary
        assert create(client, staff_headers, capacity=1).status_code == 201


# ---------------------------------------------------------------------------
# AC1: blank venue name -> validation error, venue not created
# ---------------------------------------------------------------------------
class TestAC1BlankName:
    @pytest.mark.parametrize("name", ["", None, "   ", "\t\n"])
    def test_blank_name_rejected(self, client, staff_headers, name):
        resp = create(client, staff_headers, name=name)

        assert resp.status_code == 400
        assert "name" in resp.get_json()["error"].lower()
        assert venue_count() == 0

    def test_missing_name_key_rejected(self, client, staff_headers):
        payload = valid_payload()
        del payload["name"]
        resp = client.post(URL, json=payload, headers=staff_headers)

        assert resp.status_code == 400
        assert venue_count() == 0

    def test_service_raises_value_error(self, app, staff_id):
        with pytest.raises(ValueError, match="name"):
            catalogue.create_venue(staff_id, valid_payload(name=""))
        assert venue_count() == 0


# ---------------------------------------------------------------------------
# AC2: capacity zero / negative -> validation error
# ---------------------------------------------------------------------------
class TestAC2Capacity:
    @pytest.mark.parametrize("capacity", [0, -1, -500])
    def test_zero_or_negative_capacity_rejected(self, client, staff_headers, capacity):
        resp = create(client, staff_headers, capacity=capacity)

        assert resp.status_code == 400
        assert "capacity" in resp.get_json()["error"].lower()
        assert venue_count() == 0

    @pytest.mark.parametrize("capacity", [None, ""])
    def test_blank_capacity_rejected(self, client, staff_headers, capacity):
        resp = create(client, staff_headers, capacity=capacity)

        assert resp.status_code == 400
        assert venue_count() == 0

    def test_missing_capacity_key_rejected(self, client, staff_headers):
        payload = valid_payload()
        del payload["capacity"]
        resp = client.post(URL, json=payload, headers=staff_headers)

        assert resp.status_code == 400
        assert venue_count() == 0

    @pytest.mark.parametrize("capacity", ["abc", "12.5", 12.5, [], {}])
    def test_non_integer_capacity_rejected_not_500(self, client, staff_headers, capacity):
        resp = create(client, staff_headers, capacity=capacity)

        assert resp.status_code == 400  # must be a validation error, not a crash
        assert venue_count() == 0


# ---------------------------------------------------------------------------
# AC3: negative setup / turnaround time -> validation error
# ---------------------------------------------------------------------------
class TestAC3SetupAndTurnaround:
    def test_negative_setup_rejected(self, client, staff_headers):
        resp = create(client, staff_headers, setupMinutes=-1)

        assert resp.status_code == 400
        assert "setup" in resp.get_json()["error"].lower()
        assert venue_count() == 0

    def test_negative_turnaround_rejected(self, client, staff_headers):
        resp = create(client, staff_headers, turnaroundMinutes=-1)

        assert resp.status_code == 400
        assert "turnaround" in resp.get_json()["error"].lower()
        assert venue_count() == 0

    def test_both_negative_rejected(self, client, staff_headers):
        resp = create(client, staff_headers, setupMinutes=-5, turnaroundMinutes=-5)

        assert resp.status_code == 400
        assert venue_count() == 0

    def test_zero_setup_and_turnaround_allowed(self, client, staff_headers):  # boundary
        resp = create(client, staff_headers, setupMinutes=0, turnaroundMinutes=0)

        assert resp.status_code == 201

    def test_omitted_times_default_to_zero(self, client, staff_headers):
        payload = valid_payload()
        del payload["setupMinutes"], payload["turnaroundMinutes"]
        resp = client.post(URL, json=payload, headers=staff_headers)

        assert resp.status_code == 201
        venue = Venue.query.get(resp.get_json()["id"])
        assert venue.setup_minutes == 0 and venue.turnaround_minutes == 0

    @pytest.mark.parametrize("field", ["setupMinutes", "turnaroundMinutes"])
    def test_non_numeric_time_rejected_not_500(self, client, staff_headers, field):
        resp = create(client, staff_headers, **{field: "abc"})

        assert resp.status_code == 400
        assert venue_count() == 0


# ---------------------------------------------------------------------------
# AC4: only name and capacity are mandatory
# ---------------------------------------------------------------------------
class TestAC4OptionalFields:
    def test_only_name_and_capacity(self, client, staff_headers):
        resp = client.post(URL, json={"name": "Bare Venue", "capacity": 10}, headers=staff_headers)

        assert resp.status_code == 201
        venue = Venue.query.get(resp.get_json()["id"])
        assert list(venue.facilities) == []
        assert list(venue.accessibility_features) == []
        assert list(venue.supported_layouts) == []
        assert venue.operating_hours is None

    @pytest.mark.parametrize(
        "omitted", ["facilities", "accessibilityFeatures", "operatingHours", "supportedLayouts"]
    )
    def test_each_optional_field_can_be_omitted(self, client, staff_headers, omitted):
        payload = valid_payload()
        del payload[omitted]
        resp = client.post(URL, json=payload, headers=staff_headers)

        assert resp.status_code == 201

    def test_empty_values_accepted(self, client, staff_headers):
        resp = create(
            client, staff_headers,
            facilities=[], accessibilityFeatures=[], supportedLayouts=[], operatingHours=None,
        )

        assert resp.status_code == 201


# ---------------------------------------------------------------------------
# AC5: duplicates (same name + location) are allowed as separate records
# ---------------------------------------------------------------------------
class TestAC5Duplicates:
    def test_same_name_and_location_creates_separate_records(self, client, staff_headers):
        first = create(client, staff_headers)
        second = create(client, staff_headers)

        assert first.status_code == 201
        assert second.status_code == 201
        assert first.get_json()["id"] != second.get_json()["id"]
        assert venue_count() == 2

    def test_same_name_different_location_allowed(self, client, staff_headers):
        assert create(client, staff_headers).status_code == 201
        assert create(client, staff_headers, location="2 Other Road").status_code == 201

    def test_both_duplicates_listed_in_catalogue(self, client, staff_headers):
        create(client, staff_headers)
        create(client, staff_headers)

        listed = client.get(URL, headers=staff_headers).get_json()
        assert len(listed) == 2

    def test_duplicates_are_independent(self, client, staff_headers):
        id1 = create(client, staff_headers).get_json()["id"]
        id2 = create(client, staff_headers).get_json()["id"]

        client.put(f"{URL}/{id1}", json={"name": "Renamed"}, headers=staff_headers)

        assert Venue.query.get(id2).name == "Grand Hall"


# ---------------------------------------------------------------------------
# AC6: new venue is active by default and visible to staff and coordinators
# ---------------------------------------------------------------------------
class TestAC6ActiveAndVisible:
    def test_active_by_default(self, client, staff_headers):
        resp = create(client, staff_headers)

        assert resp.get_json()["isActive"] is True
        assert Venue.query.get(resp.get_json()["id"]).is_active is True

    def test_active_even_if_client_sends_inactive(self, client, staff_headers):
        resp = create(client, staff_headers, isActive=False, is_active=False)

        assert resp.status_code == 201
        assert resp.get_json()["isActive"] is True

    def test_visible_to_venue_staff(self, client, staff_headers):
        venue_id = create(client, staff_headers).get_json()["id"]

        listed = client.get(URL, headers=staff_headers)
        assert listed.status_code == 200
        assert venue_id in [v["id"] for v in listed.get_json()]

    def test_visible_to_event_coordinator(self, client, staff_headers, coordinator_headers):
        venue_id = create(client, staff_headers).get_json()["id"]

        listed = client.get(URL, headers=coordinator_headers)
        assert listed.status_code == 200
        assert venue_id in [v["id"] for v in listed.get_json()]

    def test_coordinator_can_fetch_new_venue_by_id(self, client, staff_headers, coordinator_headers):
        venue_id = create(client, staff_headers).get_json()["id"]

        resp = client.get(f"{URL}/{venue_id}", headers=coordinator_headers)
        assert resp.status_code == 200
        assert resp.get_json()["name"] == "Grand Hall"


# ---------------------------------------------------------------------------
# Authorisation (project requirement: role-based access)
# ---------------------------------------------------------------------------
class TestAuthorisation:
    def test_event_coordinator_cannot_create(self, client, coordinator_headers):
        resp = create(client, coordinator_headers)

        assert resp.status_code == 403
        assert venue_count() == 0

    def test_unauthenticated_cannot_create(self, client):
        resp = client.post(URL, json=valid_payload())

        assert resp.status_code == 401
        assert venue_count() == 0

    def test_unauthenticated_cannot_list(self, client):
        assert client.get(URL).status_code == 401


# ---------------------------------------------------------------------------
# Robustness
# ---------------------------------------------------------------------------
class TestRobustness:
    def test_empty_body_rejected(self, client, staff_headers):
        resp = client.post(URL, json={}, headers=staff_headers)

        assert resp.status_code == 400
        assert venue_count() == 0

    def test_special_characters_stored_verbatim(self, client, staff_headers):
        name = "Café & Hall #1 <b>x</b> 会場 🎉"
        resp = create(client, staff_headers, name=name)

        assert resp.status_code == 201
        assert resp.get_json()["name"] == name  # JSON API: returned as data, not rendered

    def test_sql_injection_string_is_plain_text(self, client, staff_headers):
        resp = create(client, staff_headers, name="'; DROP TABLE venues;--")

        assert resp.status_code == 201
        assert venue_count() == 1
