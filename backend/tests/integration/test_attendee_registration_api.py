"""HTTP tests for Attendee Registration (/api/registrations/...): roles, status codes
and the rules that must hold even when the screen would not offer the action."""
from datetime import time, timedelta

import pytest

from app.common.time import utcnow
from app.extensions import db
from app.models.event import Event
from app.models.registration import Registration

URL = "/api/registrations"


@pytest.fixture()
def cast(make_user, auth_header):
    users = {
        "organiser": make_user("api-org@test.com", ["event_organiser"], name="Olive Organiser"),
        "coordinator": make_user("api-coord@test.com", ["event_coordinator"], name="Carl Coordinator"),
        "other_organiser": make_user("api-org2@test.com", ["event_organiser"]),
        "a1": make_user("api-a1@test.com", ["attendee"], name="Attendee One"),
        "a2": make_user("api-a2@test.com", ["attendee"], name="Attendee Two"),
        "a3": make_user("api-a3@test.com", ["attendee"], name="Attendee Three"),
    }
    headers = {
        "organiser": auth_header("api-org@test.com"),
        "coordinator": auth_header("api-coord@test.com"),
        "other_organiser": auth_header("api-org2@test.com"),
        "a1": auth_header("api-a1@test.com"),
        "a2": auth_header("api-a2@test.com"),
        "a3": auth_header("api-a3@test.com"),
    }
    return {"id": users, "h": headers}


def make_event(cast, status="confirmed", capacity=2, required=True, name="Open Day"):
    event = Event(
        name=name,
        description="A public talk",
        organiser_id=cast["id"]["organiser"],
        coordinator_id=cast["id"]["coordinator"],
        status=status,
        registration_required=required,
        intended_capacity=capacity,
        proposed_date=(utcnow() + timedelta(days=30)).date(),
        proposed_time=time(10, 0),
    )
    db.session.add(event)
    db.session.commit()
    return event


def open_event(client, cast, **kw):
    event = make_event(cast, **kw)
    resp = client.post(f"{URL}/events/{event.id}/open", headers=cast["h"]["organiser"])
    assert resp.status_code == 200, resp.get_json()
    return event


class TestViewing:
    def test_attendee_sees_public_details_only(self, client, cast):
        event = open_event(client, cast)

        resp = client.get(f"{URL}/events/{event.id}", headers=cast["h"]["a1"])

        assert resp.status_code == 200
        body = resp.get_json()
        assert body["name"] == "Open Day" and body["placesRemaining"] == 2
        assert "coordinatorId" not in body and "organiserId" not in body

    @pytest.mark.parametrize("status", ["draft", "under_review", "approved", "planning", "rejected"])
    def test_unconfirmed_event_looks_exactly_like_a_missing_one(self, client, cast, status):
        event = make_event(cast, status=status)

        hidden = client.get(f"{URL}/events/{event.id}", headers=cast["h"]["a1"])
        missing = client.get(f"{URL}/events/99999", headers=cast["h"]["a1"])

        assert hidden.status_code == missing.status_code == 404
        assert hidden.get_json() == missing.get_json()

    def test_browse_lists_only_confirmed_events_that_take_registrations(self, client, cast):
        shown = open_event(client, cast, name="Shown")
        make_event(cast, required=False, name="No sign-up")
        make_event(cast, status="planning", name="Planning")

        listed = client.get(f"{URL}/events", headers=cast["h"]["a1"]).get_json()

        assert [e["id"] for e in listed] == [shown.id]

    def test_cancelled_event_shows_its_final_status_without_a_register_option(self, client, cast):
        event = make_event(cast, status="cancelled")

        body = client.get(f"{URL}/events/{event.id}", headers=cast["h"]["a1"]).get_json()

        assert body["status"] == "cancelled" and body["canRegister"] is False

    def test_only_attendees_may_browse_and_anonymous_users_are_unauthorised(self, client, cast):
        event = open_event(client, cast)

        assert client.get(f"{URL}/events", headers=cast["h"]["organiser"]).status_code == 403
        assert client.get(f"{URL}/events/{event.id}", headers=cast["h"]["coordinator"]).status_code == 403
        assert client.get(f"{URL}/events").status_code == 401


class TestRegisterOverHttp:
    def test_register_creates_one_registration(self, client, cast):
        event = open_event(client, cast)

        resp = client.post(f"{URL}/events/{event.id}/register", headers=cast["h"]["a1"])

        assert resp.status_code == 201 and resp.get_json()["status"] == "registered"
        assert Registration.query.count() == 1

    def test_duplicate_is_refused_with_a_clear_message(self, client, cast):
        event = open_event(client, cast)
        client.post(f"{URL}/events/{event.id}/register", headers=cast["h"]["a1"])

        resp = client.post(f"{URL}/events/{event.id}/register", headers=cast["h"]["a1"])

        assert resp.status_code == 409 and resp.get_json()["code"] == "already_registered"
        assert Registration.query.count() == 1

    def test_closed_registration_blocks_with_a_reason(self, client, cast):
        event = make_event(cast)

        resp = client.post(f"{URL}/events/{event.id}/register", headers=cast["h"]["a1"])

        assert resp.status_code == 409 and "not open" in resp.get_json()["error"]
        assert Registration.query.count() == 0

    @pytest.mark.parametrize("status,expected", [("draft", 404), ("planning", 404), ("rejected", 404), ("cancelled", 409), ("completed", 409)])
    def test_direct_api_calls_for_ineligible_events_are_rejected(self, client, cast, status, expected):
        event = make_event(cast, status=status)

        resp = client.post(f"{URL}/events/{event.id}/register", headers=cast["h"]["a1"])

        assert resp.status_code == expected and Registration.query.count() == 0

    def test_full_event_offers_the_waiting_list(self, client, cast):
        event = open_event(client, cast, capacity=1)
        client.post(f"{URL}/events/{event.id}/register", headers=cast["h"]["a1"])

        resp = client.post(f"{URL}/events/{event.id}/register", headers=cast["h"]["a2"])

        assert resp.status_code == 409
        assert resp.get_json()["code"] == "event_full" and resp.get_json()["waitlistAvailable"] is True

    @pytest.mark.parametrize("who", ["organiser", "coordinator"])
    def test_only_attendees_can_register(self, client, cast, who):
        event = open_event(client, cast)

        assert client.post(f"{URL}/events/{event.id}/register", headers=cast["h"][who]).status_code == 403
        assert client.post(f"{URL}/events/{event.id}/register").status_code == 401
        assert Registration.query.count() == 0


class TestWaitlistAndWithdrawOverHttp:
    def test_join_waitlist_then_get_promoted_when_a_place_frees_up(self, client, cast):
        event = open_event(client, cast, capacity=1)
        first = client.post(f"{URL}/events/{event.id}/register", headers=cast["h"]["a1"]).get_json()
        joined = client.post(f"{URL}/events/{event.id}/waitlist", headers=cast["h"]["a2"])
        assert joined.status_code == 201 and joined.get_json()["queuePosition"] == 1

        out = client.post(f"{URL}/{first['id']}/withdraw", headers=cast["h"]["a1"])

        assert out.status_code == 200 and out.get_json()["status"] == "withdrawn"
        assert out.get_json()["promotedRegistrationIds"] == [joined.get_json()["id"]]
        mine = client.get(f"{URL}/mine", headers=cast["h"]["a2"]).get_json()
        assert mine[0]["status"] == "registered"

    def test_waitlist_is_not_offered_while_places_remain(self, client, cast):
        event = open_event(client, cast, capacity=2)

        resp = client.post(f"{URL}/events/{event.id}/waitlist", headers=cast["h"]["a1"])

        assert resp.status_code == 409 and resp.get_json()["code"] == "places_available"

    def test_waitlist_positions_are_distinct_and_in_order(self, client, cast):
        event = open_event(client, cast, capacity=1)
        client.post(f"{URL}/events/{event.id}/register", headers=cast["h"]["a1"])

        p2 = client.post(f"{URL}/events/{event.id}/waitlist", headers=cast["h"]["a2"]).get_json()["queuePosition"]
        p3 = client.post(f"{URL}/events/{event.id}/waitlist", headers=cast["h"]["a3"]).get_json()["queuePosition"]

        assert (p2, p3) == (1, 2)

    def test_only_the_owner_can_withdraw(self, client, cast):
        event = open_event(client, cast)
        mine = client.post(f"{URL}/events/{event.id}/register", headers=cast["h"]["a1"]).get_json()

        resp = client.post(f"{URL}/{mine['id']}/withdraw", headers=cast["h"]["a2"])

        assert resp.status_code == 403
        assert db.session.get(Registration, mine["id"]).status == "registered"

    def test_withdrawing_twice_is_a_clear_message_not_an_error_page(self, client, cast):
        event = open_event(client, cast)
        mine = client.post(f"{URL}/events/{event.id}/register", headers=cast["h"]["a1"]).get_json()
        client.post(f"{URL}/{mine['id']}/withdraw", headers=cast["h"]["a1"])

        resp = client.post(f"{URL}/{mine['id']}/withdraw", headers=cast["h"]["a1"])

        assert resp.status_code == 409 and "already withdrawn" in resp.get_json()["error"]

    def test_unknown_registration_is_404(self, client, cast):
        assert client.post(f"{URL}/99999/withdraw", headers=cast["h"]["a1"]).status_code == 404

    def test_my_registrations_only_lists_my_own_and_starts_empty(self, client, cast):
        assert client.get(f"{URL}/mine", headers=cast["h"]["a1"]).get_json() == []
        event = open_event(client, cast, capacity=5)
        client.post(f"{URL}/events/{event.id}/register", headers=cast["h"]["a1"])
        client.post(f"{URL}/events/{event.id}/register", headers=cast["h"]["a2"])

        mine = client.get(f"{URL}/mine", headers=cast["h"]["a1"]).get_json()

        assert len(mine) == 1 and mine[0]["attendeeId"] == cast["id"]["a1"]
        assert client.get(f"{URL}/mine", headers=cast["h"]["organiser"]).status_code == 403


class TestOrganiserOverHttp:
    def test_open_and_close_toggle_what_attendees_see(self, client, cast):
        event = make_event(cast)
        assert client.get(f"{URL}/events/{event.id}", headers=cast["h"]["a1"]).get_json()["registrationOpen"] is False

        assert client.post(f"{URL}/events/{event.id}/open", headers=cast["h"]["organiser"]).get_json()["registrationOpen"] is True
        assert client.get(f"{URL}/events/{event.id}", headers=cast["h"]["a1"]).get_json()["registrationOpen"] is True

        assert client.post(f"{URL}/events/{event.id}/close", headers=cast["h"]["organiser"]).get_json()["registrationOpen"] is False
        assert client.get(f"{URL}/events/{event.id}", headers=cast["h"]["a1"]).get_json()["registrationOpen"] is False

    def test_cannot_open_before_confirmation(self, client, cast):
        event = make_event(cast, status="planning")

        resp = client.post(f"{URL}/events/{event.id}/open", headers=cast["h"]["organiser"])

        assert resp.status_code == 409 and "confirmed" in resp.get_json()["error"]

    def test_twice_is_a_message_not_a_crash(self, client, cast):
        event = open_event(client, cast)

        resp = client.post(f"{URL}/events/{event.id}/open", headers=cast["h"]["organiser"])

        assert resp.status_code == 409 and "already open" in resp.get_json()["error"]

    def test_someone_elses_event_and_other_roles_are_denied(self, client, cast):
        event = make_event(cast)

        assert client.post(f"{URL}/events/{event.id}/open", headers=cast["h"]["other_organiser"]).status_code == 403
        assert client.post(f"{URL}/events/{event.id}/open", headers=cast["h"]["coordinator"]).status_code == 403
        assert client.post(f"{URL}/events/{event.id}/open", headers=cast["h"]["a1"]).status_code == 403
        assert client.post(f"{URL}/events/99999/open", headers=cast["h"]["organiser"]).status_code == 404

    def test_managed_events_list_is_for_organisers_and_coordinators(self, client, cast):
        event = make_event(cast)

        listed = client.get(f"{URL}/manage/events", headers=cast["h"]["organiser"]).get_json()

        assert [e["id"] for e in listed] == [event.id]
        assert client.get(f"{URL}/manage/events", headers=cast["h"]["coordinator"]).status_code == 200
        assert client.get(f"{URL}/manage/events", headers=cast["h"]["a1"]).status_code == 403


class TestAttendeeListOverHttp:
    def _two_registered(self, client, cast):
        event = open_event(client, cast, capacity=5)
        client.post(f"{URL}/events/{event.id}/register", headers=cast["h"]["a1"])
        client.post(f"{URL}/events/{event.id}/register", headers=cast["h"]["a2"])
        return event

    @pytest.mark.parametrize("who", ["organiser", "coordinator"])
    def test_organiser_and_coordinator_can_view(self, client, cast, who):
        event = self._two_registered(client, cast)

        resp = client.get(f"{URL}/events/{event.id}/attendees", headers=cast["h"][who])

        assert resp.status_code == 200
        body = resp.get_json()
        assert {r["attendeeName"] for r in body["registrations"]} == {"Attendee One", "Attendee Two"}
        assert body["summary"]["registered"] == 2 and body["summary"]["placesRemaining"] == 3

    def test_no_credentials_or_contact_details_are_returned(self, client, cast):
        event = self._two_registered(client, cast)

        text = client.get(f"{URL}/events/{event.id}/attendees", headers=cast["h"]["organiser"]).get_data(as_text=True)

        assert "@test.com" not in text and "password" not in text.lower()

    def test_paging_parameters_are_honoured(self, client, cast):
        event = self._two_registered(client, cast)

        body = client.get(f"{URL}/events/{event.id}/attendees?page=2&pageSize=1", headers=cast["h"]["organiser"]).get_json()

        assert body["page"] == 2 and body["pages"] == 2 and len(body["registrations"]) == 1

    def test_other_organisers_and_attendees_are_denied(self, client, cast):
        event = self._two_registered(client, cast)

        assert client.get(f"{URL}/events/{event.id}/attendees", headers=cast["h"]["other_organiser"]).status_code == 403
        assert client.get(f"{URL}/events/{event.id}/attendees", headers=cast["h"]["a1"]).status_code == 403
        assert client.get(f"{URL}/events/{event.id}/attendees").status_code == 401

    def test_unknown_event_is_404(self, client, cast):
        assert client.get(f"{URL}/events/99999/attendees", headers=cast["h"]["organiser"]).status_code == 404
