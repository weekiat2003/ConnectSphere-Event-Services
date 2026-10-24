"""Unit tests for Attendee Registration (app/registrations/service.py).

One test class per user story. They call the service directly against the
in-memory test database, like the other service-level tests in this folder.
"""
from datetime import time, timedelta

import pytest
from sqlalchemy.exc import IntegrityError

from app.common.time import utcnow
from app.extensions import db
from app.models.event import Event
from app.models.registration import Registration
from app.models.venue import Venue, VenueBooking
from app.registrations import service
from app.registrations.service import Conflict, EventFull, Forbidden, NotFound


@pytest.fixture()
def people(make_user):
    """An organiser, the event's coordinator, an unrelated organiser and five attendees."""
    ids = {
        "organiser": make_user("reg-org@test.com", ["event_organiser"], name="Olive Organiser"),
        "coordinator": make_user("reg-coord@test.com", ["event_coordinator"], name="Carl Coordinator"),
        "other_organiser": make_user("reg-org2@test.com", ["event_organiser"], name="Other Organiser"),
    }
    for i in range(1, 6):
        ids[f"a{i}"] = make_user(f"reg-a{i}@test.com", ["attendee"], name=f"Attendee {i}")
    return ids


def make_event(people, status="confirmed", capacity=2, required=True, days=30, **extra):
    event = Event(
        name=extra.pop("name", "Open Day"),
        description="A public talk",
        organiser_id=people["organiser"],
        coordinator_id=people["coordinator"],
        status=status,
        registration_required=required,
        intended_capacity=capacity,
        proposed_date=(utcnow() + timedelta(days=days)).date(),
        proposed_time=time(10, 0),
        expected_attendance=extra.pop("expected_attendance", 50),
        **extra,
    )
    db.session.add(event)
    db.session.commit()
    return event


def open_event(people, **kw):
    event = make_event(people, **kw)
    service.open_registration(event.id, people["organiser"])
    return event


def active_count(event_id):
    return Registration.query.filter(
        Registration.event_id == event_id, Registration.status != "withdrawn"
    ).count()


# =====================================================================
# 1. Attendee views confirmed event information
# =====================================================================
class TestAttendeeViewsEvent:
    PUBLIC_KEYS = {
        "id", "name", "description", "date", "time", "venues", "status", "statusLabel",
        "registrationOpen", "capacity", "placesRemaining", "isFull", "canRegister",
        "canJoinWaitlist", "myRegistration", "followingUpdates",
    }

    def test_only_public_details_are_shown(self, app, people):
        event = open_event(people)

        info = service.get_event(event.id, people["a1"])

        assert set(info) == self.PUBLIC_KEYS
        assert info["name"] == "Open Day" and info["time"] == "10:00"
        for hidden in ("coordinatorId", "coordinator", "reviews", "equipment", "statusHistory", "organiserId"):
            assert hidden not in info

    def test_venue_names_come_from_approved_bookings_only(self, app, people):
        event = open_event(people)
        hall, annex = Venue(name="Main Hall", location="N", capacity=100), Venue(name="Annex", location="S", capacity=50)
        db.session.add_all([hall, annex])
        db.session.flush()
        start = utcnow() + timedelta(days=30)
        db.session.add_all([
            VenueBooking(event_id=event.id, venue_id=hall.id, requested_by=1, status="approved", start_datetime=start, end_datetime=start + timedelta(hours=2)),
            VenueBooking(event_id=event.id, venue_id=annex.id, requested_by=1, status="pending", start_datetime=start, end_datetime=start + timedelta(hours=2)),
        ])
        db.session.commit()

        assert service.get_event(event.id, people["a1"])["venues"] == ["Main Hall"]

    @pytest.mark.parametrize("status", ["draft", "submitted", "under_review", "approved", "planning", "safety_check", "rejected"])
    def test_unconfirmed_events_are_not_found(self, app, people, status):
        event = make_event(people, status=status)

        with pytest.raises(NotFound) as hidden:
            service.get_event(event.id, people["a1"])
        with pytest.raises(NotFound) as missing:
            service.get_event(99999, people["a1"])

        assert str(hidden.value) == str(missing.value)  # does not reveal that the event exists

    def test_confirmed_event_without_registration_is_not_listed_or_viewable(self, app, people):
        event = make_event(people, required=False)

        assert service.list_events(people["a1"]) == []
        with pytest.raises(NotFound):
            service.get_event(event.id, people["a1"])

    def test_list_shows_only_confirmed_events_that_take_registrations(self, app, people):
        shown = open_event(people, name="Shown")
        make_event(people, name="Draft", status="draft")
        make_event(people, name="No sign-up", required=False)
        make_event(people, name="Done", status="completed")

        assert [e["id"] for e in service.list_events(people["a1"])] == [shown.id]

    def test_limited_capacity_shows_remaining_places_then_full(self, app, people):
        event = open_event(people, capacity=2)
        assert service.get_event(event.id, people["a3"])["placesRemaining"] == 2

        service.register(event.id, people["a1"])
        assert service.get_event(event.id, people["a3"])["placesRemaining"] == 1

        service.register(event.id, people["a2"])
        info = service.get_event(event.id, people["a3"])
        assert info["placesRemaining"] == 0 and info["isFull"] is True
        assert info["canRegister"] is False and info["canJoinWaitlist"] is True

    def test_unlimited_capacity_never_reports_full(self, app, people):
        event = open_event(people, capacity=None)

        info = service.get_event(event.id, people["a1"])

        assert info["capacity"] is None and info["placesRemaining"] is None and info["isFull"] is False

    def test_registration_not_open_still_shows_the_event(self, app, people):
        event = make_event(people)

        info = service.get_event(event.id, people["a1"])

        assert info["name"] == "Open Day"
        assert info["registrationOpen"] is False and info["canRegister"] is False

    def test_closed_registration_is_indicated_too(self, app, people):
        event = open_event(people)
        service.close_registration(event.id, people["organiser"])

        info = service.get_event(event.id, people["a1"])

        assert info["registrationOpen"] is False and info["canRegister"] is False

    @pytest.mark.parametrize("status", ["cancelled", "completed"])
    def test_finished_events_show_final_status_and_no_register_option(self, app, people, status):
        event = make_event(people, status=status)

        info = service.get_event(event.id, people["a1"])

        assert info["status"] == status and info["statusLabel"] == status.capitalize()
        assert info["canRegister"] is False and info["canJoinWaitlist"] is False

    def test_unknown_event_id_is_a_clear_not_found(self, app, people):
        with pytest.raises(NotFound, match="not found"):
            service.get_event(424242, people["a1"])


# =====================================================================
# 2. Attendee registers for an event
# =====================================================================
class TestRegister:
    def test_creates_one_registered_record_and_reduces_places(self, app, people):
        event = open_event(people, capacity=3)

        registration = service.register(event.id, people["a1"])

        assert registration.status == "registered" and registration.attendee_id == people["a1"]
        assert Registration.query.count() == 1
        assert service.get_event(event.id, people["a2"])["placesRemaining"] == 2

    @pytest.mark.parametrize("existing", ["registered", "waitlisted"])
    def test_cannot_register_twice(self, app, people, existing):
        event = open_event(people, capacity=1)
        if existing == "registered":
            service.register(event.id, people["a1"])
        else:
            service.register(event.id, people["a2"])
            service.join_waitlist(event.id, people["a1"])

        with pytest.raises(Conflict, match="already have an active registration") as err:
            service.register(event.id, people["a1"])

        assert err.value.code == "already_registered"
        assert Registration.query.filter_by(attendee_id=people["a1"]).count() == 1

    def test_blocked_when_registration_has_not_opened(self, app, people):
        event = make_event(people)

        with pytest.raises(Conflict, match="not open") as err:
            service.register(event.id, people["a1"])

        assert err.value.code == "registration_closed" and Registration.query.count() == 0

    def test_blocked_when_registration_is_closed(self, app, people):
        event = open_event(people)
        service.close_registration(event.id, people["organiser"])

        with pytest.raises(Conflict, match="not open"):
            service.register(event.id, people["a1"])

    @pytest.mark.parametrize("status", ["draft", "approved", "planning", "rejected"])
    def test_unconfirmed_event_is_rejected_even_through_the_api(self, app, people, status):
        event = make_event(people, status=status)

        with pytest.raises(NotFound):
            service.register(event.id, people["a1"])

        assert Registration.query.count() == 0

    @pytest.mark.parametrize("status", ["cancelled", "completed"])
    def test_finished_event_is_rejected(self, app, people, status):
        event = make_event(people, status=status)

        with pytest.raises(Conflict) as err:
            service.register(event.id, people["a1"])

        assert err.value.code == "event_finished" and Registration.query.count() == 0

    def test_last_place_goes_to_the_first_request_and_the_second_is_offered_the_waiting_list(self, app, people):
        event = open_event(people, capacity=1)

        first = service.register(event.id, people["a1"])
        with pytest.raises(EventFull, match="waiting list"):
            service.register(event.id, people["a2"])
        second = service.join_waitlist(event.id, people["a2"])

        assert first.status == "registered" and second.status == "waitlisted"
        assert Registration.query.filter_by(status="registered").count() == 1  # capacity never exceeded

    def test_registering_again_after_withdrawing_keeps_the_old_record(self, app, people):
        event = open_event(people)
        old = service.register(event.id, people["a1"])
        service.withdraw(old.id, people["a1"])

        new = service.register(event.id, people["a1"])

        assert new.id != old.id and new.status == "registered"
        statuses = [r.status for r in Registration.query.filter_by(attendee_id=people["a1"]).order_by(Registration.id)]
        assert statuses == ["withdrawn", "registered"]

    def test_the_intended_capacity_is_the_limit(self, app, people):
        event = open_event(people, capacity=3, expected_attendance=500)  # expected attendance is irrelevant

        for key in ("a1", "a2", "a3"):
            service.register(event.id, people[key])
        with pytest.raises(EventFull):
            service.register(event.id, people["a4"])

    def test_database_stops_two_active_records_for_one_attendee(self, app, people):
        event = open_event(people, capacity=5)
        db.session.add(Registration(event_id=event.id, attendee_id=people["a1"], status="registered"))
        db.session.commit()
        db.session.add(Registration(event_id=event.id, attendee_id=people["a1"], status="waitlisted"))

        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()

    def test_database_allows_many_withdrawn_records_for_history(self, app, people):
        event = open_event(people, capacity=5)
        for _ in range(3):
            db.session.add(Registration(event_id=event.id, attendee_id=people["a1"], status="withdrawn"))
        db.session.commit()

        assert Registration.query.filter_by(attendee_id=people["a1"], status="withdrawn").count() == 3


# =====================================================================
# 3. Attendee views their registration status
# =====================================================================
class TestMyRegistrations:
    def test_shows_each_event_and_status_but_only_my_own(self, app, people):
        e1, e2 = open_event(people, name="One", capacity=5), open_event(people, name="Two", capacity=5)
        service.register(e1.id, people["a1"])
        service.register(e2.id, people["a1"])
        service.register(e1.id, people["a2"])

        mine = service.my_registrations(people["a1"])

        assert {m["event"]["name"] for m in mine} == {"One", "Two"}
        assert all(m["attendeeId"] == people["a1"] and m["status"] == "registered" for m in mine)

    def test_waitlisted_entry_shows_queue_position(self, app, people):
        event = open_event(people, capacity=1)
        service.register(event.id, people["a1"])
        service.join_waitlist(event.id, people["a2"])
        service.join_waitlist(event.id, people["a3"])

        assert service.my_registrations(people["a2"])[0]["queuePosition"] == 1
        assert service.my_registrations(people["a3"])[0]["queuePosition"] == 2
        assert service.my_registrations(people["a1"])[0]["queuePosition"] is None

    def test_empty_state_when_never_registered(self, app, people):
        assert service.my_registrations(people["a1"]) == []

    def test_reload_shows_the_latest_status(self, app, people):
        event = open_event(people, capacity=1)
        first = service.register(event.id, people["a1"])
        service.join_waitlist(event.id, people["a2"])
        assert service.my_registrations(people["a2"])[0]["status"] == "waitlisted"

        service.withdraw(first.id, people["a1"])

        assert service.my_registrations(people["a2"])[0]["status"] == "registered"

    def test_withdrawn_records_still_appear_and_are_distinguishable(self, app, people):
        event = open_event(people)
        registration = service.register(event.id, people["a1"])
        service.withdraw(registration.id, people["a1"])

        mine = service.my_registrations(people["a1"])

        assert len(mine) == 1 and mine[0]["status"] == "withdrawn"

    def test_cancelled_event_state_is_visible_next_to_my_registration(self, app, people):
        event = open_event(people)
        service.register(event.id, people["a1"])
        event.status = "cancelled"
        db.session.commit()

        mine = service.my_registrations(people["a1"])[0]

        assert mine["status"] == "registered" and mine["event"]["status"] == "cancelled"

    def test_another_attendees_registration_cannot_be_opened_or_changed(self, app, people):
        event = open_event(people)
        theirs = service.register(event.id, people["a1"])

        with pytest.raises(Forbidden):
            service.withdraw(theirs.id, people["a2"])


# =====================================================================
# 4. Attendee withdraws their registration
# =====================================================================
class TestWithdraw:
    def test_registered_becomes_withdrawn_and_the_place_is_free_again(self, app, people):
        event = open_event(people, capacity=1)
        registration = service.register(event.id, people["a1"])

        withdrawn, promoted = service.withdraw(registration.id, people["a1"])

        assert withdrawn.status == "withdrawn" and promoted == []
        assert service.get_event(event.id, people["a2"])["placesRemaining"] == 1

    def test_withdrawing_from_the_waiting_list_moves_everyone_behind_up(self, app, people):
        event = open_event(people, capacity=1)
        service.register(event.id, people["a1"])
        w1 = service.join_waitlist(event.id, people["a2"])
        w2 = service.join_waitlist(event.id, people["a3"])
        w3 = service.join_waitlist(event.id, people["a4"])

        service.withdraw(w2.id, people["a3"])

        assert service.queue_position(db.session.get(Registration, w1.id)) == 1  # ahead: unchanged
        assert service.queue_position(db.session.get(Registration, w3.id)) == 2  # behind: moved up
        assert db.session.get(Registration, w2.id).status == "withdrawn"

    def test_withdrawing_twice_changes_nothing_and_explains(self, app, people):
        event = open_event(people)
        registration = service.register(event.id, people["a1"])
        service.withdraw(registration.id, people["a1"])

        with pytest.raises(Conflict, match="already withdrawn") as err:
            service.withdraw(registration.id, people["a1"])

        assert err.value.code == "already_withdrawn"

    def test_first_waitlisted_attendee_is_registered_automatically(self, app, people):
        event = open_event(people, capacity=1)
        holder = service.register(event.id, people["a1"])
        first = service.join_waitlist(event.id, people["a2"])
        second = service.join_waitlist(event.id, people["a3"])

        _, promoted = service.withdraw(holder.id, people["a1"])

        assert [p.id for p in promoted] == [first.id]
        assert db.session.get(Registration, first.id).status == "registered"
        assert db.session.get(Registration, second.id).status == "waitlisted"
        assert service.queue_position(db.session.get(Registration, second.id)) == 1

    @pytest.mark.parametrize("status", ["cancelled", "completed"])
    def test_not_allowed_once_the_event_is_cancelled_or_completed(self, app, people, status):
        event = open_event(people)
        registration = service.register(event.id, people["a1"])
        event.status = status
        db.session.commit()

        with pytest.raises(Conflict, match=status) as err:
            service.withdraw(registration.id, people["a1"])

        assert err.value.code == "event_finished"
        assert db.session.get(Registration, registration.id).status == "registered"

    def test_not_allowed_once_the_event_has_started(self, app, people):
        event = open_event(people)
        registration = service.register(event.id, people["a1"])
        event.proposed_date = (utcnow() - timedelta(days=1)).date()
        db.session.commit()

        with pytest.raises(Conflict, match="already started") as err:
            service.withdraw(registration.id, people["a1"])

        assert err.value.code == "event_started"

    def test_only_the_owner_can_withdraw(self, app, people):
        event = open_event(people)
        registration = service.register(event.id, people["a1"])

        with pytest.raises(Forbidden):
            service.withdraw(registration.id, people["a2"])

        assert db.session.get(Registration, registration.id).status == "registered"

    def test_unknown_registration_is_not_found(self, app, people):
        with pytest.raises(NotFound):
            service.withdraw(99999, people["a1"])

    def test_remaining_places_go_up_for_everyone_else(self, app, people):
        event = open_event(people, capacity=2)
        a = service.register(event.id, people["a1"])
        service.register(event.id, people["a2"])
        assert service.get_event(event.id, people["a3"])["placesRemaining"] == 0

        service.withdraw(a.id, people["a1"])

        assert service.get_event(event.id, people["a3"])["placesRemaining"] == 1


# =====================================================================
# 5. Attendee joins a waiting list at capacity
# =====================================================================
class TestWaitingList:
    def test_at_capacity_registering_is_refused_and_the_waiting_list_is_offered(self, app, people):
        event = open_event(people, capacity=1)
        service.register(event.id, people["a1"])

        with pytest.raises(EventFull) as err:
            service.register(event.id, people["a2"])

        assert err.value.code == "event_full"
        assert Registration.query.filter_by(attendee_id=people["a2"]).count() == 0

    def test_positions_follow_the_order_requests_arrived(self, app, people):
        event = open_event(people, capacity=1)
        service.register(event.id, people["a1"])

        w = [service.join_waitlist(event.id, people[k]) for k in ("a2", "a3", "a4")]

        assert [service.queue_position(r) for r in w] == [1, 2, 3]
        assert all(r.status == "waitlisted" for r in w)

    def test_no_two_waitlisted_attendees_share_a_position(self, app, people):
        event = open_event(people, capacity=1)
        service.register(event.id, people["a1"])
        for key in ("a2", "a3", "a4", "a5"):
            service.join_waitlist(event.id, people[key])

        positions = [
            service.queue_position(r)
            for r in Registration.query.filter_by(event_id=event.id, status="waitlisted")
        ]

        assert sorted(positions) == [1, 2, 3, 4]

    @pytest.mark.parametrize("existing", ["registered", "waitlisted"])
    def test_cannot_join_when_already_registered_or_waitlisted(self, app, people, existing):
        event = open_event(people, capacity=1)
        if existing == "registered":
            service.register(event.id, people["a1"])
        else:
            service.register(event.id, people["a2"])
            service.join_waitlist(event.id, people["a1"])

        with pytest.raises(Conflict) as err:
            service.join_waitlist(event.id, people["a1"])

        assert err.value.code == "already_registered"

    def test_not_offered_when_places_remain(self, app, people):
        event = open_event(people, capacity=2)
        service.register(event.id, people["a1"])

        with pytest.raises(Conflict, match="register directly") as err:
            service.join_waitlist(event.id, people["a2"])

        assert err.value.code == "places_available" and Registration.query.filter_by(status="waitlisted").count() == 0

    def test_blocked_when_the_organiser_closed_registration(self, app, people):
        event = open_event(people, capacity=1)
        service.register(event.id, people["a1"])
        service.close_registration(event.id, people["organiser"])

        with pytest.raises(Conflict, match="not open"):
            service.join_waitlist(event.id, people["a2"])

    def test_raising_the_capacity_registers_waitlisted_attendees_in_queue_order(self, app, people):
        event = open_event(people, capacity=1)
        service.register(event.id, people["a1"])
        w1 = service.join_waitlist(event.id, people["a2"])
        w2 = service.join_waitlist(event.id, people["a3"])
        w3 = service.join_waitlist(event.id, people["a4"])

        event.intended_capacity = 3  # the Organiser raises the capacity
        db.session.commit()
        service.get_event(event.id, people["a5"])  # any read brings the list up to date

        assert db.session.get(Registration, w1.id).status == "registered"
        assert db.session.get(Registration, w2.id).status == "registered"
        assert db.session.get(Registration, w3.id).status == "waitlisted"
        assert service.queue_position(db.session.get(Registration, w3.id)) == 1

    def test_removing_the_capacity_limit_registers_everyone_waiting(self, app, people):
        event = open_event(people, capacity=1)
        service.register(event.id, people["a1"])
        waiting = [service.join_waitlist(event.id, people[k]) for k in ("a2", "a3")]

        event.intended_capacity = None
        db.session.commit()
        service.list_events(people["a5"])

        assert all(db.session.get(Registration, r.id).status == "registered" for r in waiting)


# =====================================================================
# 6. Organiser opens or closes registration
# =====================================================================
class TestOpenCloseRegistration:
    def test_open_lets_attendees_register(self, app, people):
        event = make_event(people)
        assert service.get_event(event.id, people["a1"])["registrationOpen"] is False

        service.open_registration(event.id, people["organiser"])

        assert service.get_event(event.id, people["a1"])["registrationOpen"] is True
        assert service.register(event.id, people["a1"]).status == "registered"

    @pytest.mark.parametrize("status", ["draft", "submitted", "approved", "planning"])
    def test_cannot_open_before_the_event_is_confirmed(self, app, people, status):
        event = make_event(people, status=status)

        with pytest.raises(Conflict, match="once the event is confirmed") as err:
            service.open_registration(event.id, people["organiser"])

        assert err.value.code == "event_not_confirmed"

    def test_cannot_open_when_the_event_takes_no_registrations(self, app, people):
        event = make_event(people, required=False)

        with pytest.raises(Conflict, match="does not take registrations"):
            service.open_registration(event.id, people["organiser"])

    @pytest.mark.parametrize("status", ["cancelled", "completed"])
    def test_cannot_open_a_finished_event(self, app, people, status):
        event = make_event(people, status=status)

        with pytest.raises(Conflict, match=status):
            service.open_registration(event.id, people["organiser"])

    def test_closing_blocks_new_registrations_but_keeps_existing_places(self, app, people):
        event = open_event(people, capacity=5)
        mine = service.register(event.id, people["a1"])

        service.close_registration(event.id, people["organiser"])

        with pytest.raises(Conflict):
            service.register(event.id, people["a2"])
        assert db.session.get(Registration, mine.id).status == "registered"

    def test_reopening_keeps_registrations_and_waiting_list_order(self, app, people):
        event = open_event(people, capacity=1)
        service.register(event.id, people["a1"])
        w1 = service.join_waitlist(event.id, people["a2"])
        w2 = service.join_waitlist(event.id, people["a3"])
        before = [(r.id, r.status) for r in Registration.query.order_by(Registration.id)]

        service.close_registration(event.id, people["organiser"])
        service.open_registration(event.id, people["organiser"])

        assert [(r.id, r.status) for r in Registration.query.order_by(Registration.id)] == before
        assert [service.queue_position(db.session.get(Registration, r.id)) for r in (w1, w2)] == [1, 2]

    def test_opening_or_closing_twice_changes_nothing_and_explains(self, app, people):
        event = make_event(people)
        service.open_registration(event.id, people["organiser"])
        with pytest.raises(Conflict, match="already open"):
            service.open_registration(event.id, people["organiser"])

        service.close_registration(event.id, people["organiser"])
        with pytest.raises(Conflict, match="already closed"):
            service.close_registration(event.id, people["organiser"])

    def test_closing_a_never_opened_event_is_a_clear_message(self, app, people):
        event = make_event(people)

        with pytest.raises(Conflict, match="already closed"):
            service.close_registration(event.id, people["organiser"])

    @pytest.mark.parametrize("who", ["other_organiser", "coordinator", "a1"])
    def test_only_the_events_organiser_can_open_or_close(self, app, people, who):
        event = make_event(people)

        with pytest.raises(Forbidden):
            service.open_registration(event.id, people[who])
        service.open_registration(event.id, people["organiser"])
        with pytest.raises(Forbidden):
            service.close_registration(event.id, people[who])

    def test_unknown_event_is_not_found(self, app, people):
        with pytest.raises(NotFound):
            service.open_registration(99999, people["organiser"])

    def test_managed_events_lists_mine_including_unconfirmed_ones(self, app, people):
        confirmed = open_event(people, name="Confirmed")
        draft = make_event(people, name="Draft", status="draft")
        make_event(people, name="Not mine", status="confirmed")  # same people; make another organiser's
        other = Event(name="Other", organiser_id=people["other_organiser"], status="confirmed", registration_required=True, proposed_date=utcnow().date())
        db.session.add(other)
        db.session.commit()

        mine = {e["name"]: e for e in service.list_managed_events(people["organiser"])}

        assert "Other" not in mine
        assert mine["Confirmed"]["registrationOpen"] is True and mine["Draft"]["registrationOpen"] is False
        assert mine["Confirmed"]["id"] == confirmed.id and mine["Draft"]["id"] == draft.id


# =====================================================================
# 7. View registered attendees for an event
# =====================================================================
class TestAttendeeList:
    def _fill(self, people):
        event = open_event(people, capacity=2)
        a = service.register(event.id, people["a1"])
        service.register(event.id, people["a2"])
        service.join_waitlist(event.id, people["a3"])
        service.join_waitlist(event.id, people["a4"])
        service.withdraw(a.id, people["a1"])  # a3 is promoted; a1 withdrawn
        return event

    @pytest.mark.parametrize("who", ["organiser", "coordinator"])
    def test_organiser_and_coordinator_see_names_statuses_and_positions(self, app, people, who):
        event = self._fill(people)

        data = service.list_attendees(event.id, people[who])

        by_name = {r["attendeeName"]: r for r in data["registrations"]}
        assert by_name["Attendee 1"]["status"] == "withdrawn"
        assert by_name["Attendee 2"]["status"] == "registered"
        assert by_name["Attendee 3"]["status"] == "registered"  # promoted
        assert by_name["Attendee 4"]["status"] == "waitlisted" and by_name["Attendee 4"]["queuePosition"] == 1

    def test_summary_counts_match_the_list(self, app, people):
        event = self._fill(people)

        data = service.list_attendees(event.id, people["organiser"])

        statuses = [r["status"] for r in data["registrations"]]
        assert data["summary"] == {
            "registered": statuses.count("registered"),
            "waitlisted": statuses.count("waitlisted"),
            "withdrawn": statuses.count("withdrawn"),
            "capacity": 2,
            "placesRemaining": 0,
        }

    def test_empty_event_returns_an_empty_list(self, app, people):
        event = open_event(people)

        data = service.list_attendees(event.id, people["organiser"])

        assert data["registrations"] == [] and data["total"] == 0 and data["summary"]["registered"] == 0

    def test_withdrawn_entries_are_visible_but_marked(self, app, people):
        event = open_event(people)
        r = service.register(event.id, people["a1"])
        service.withdraw(r.id, people["a1"])

        data = service.list_attendees(event.id, people["organiser"])

        assert [x["status"] for x in data["registrations"]] == ["withdrawn"]
        assert data["summary"]["registered"] == 0 and data["summary"]["withdrawn"] == 1

    @pytest.mark.parametrize("who", ["other_organiser", "a1"])
    def test_everyone_else_is_denied(self, app, people, who):
        event = open_event(people)

        with pytest.raises(Forbidden):
            service.list_attendees(event.id, people[who])

    def test_unknown_event_is_not_found(self, app, people):
        with pytest.raises(NotFound):
            service.list_attendees(99999, people["organiser"])

    def test_reload_reflects_new_registrations_and_withdrawals(self, app, people):
        event = open_event(people, capacity=5)
        assert service.list_attendees(event.id, people["organiser"])["total"] == 0

        r = service.register(event.id, people["a1"])
        assert service.list_attendees(event.id, people["organiser"])["summary"]["registered"] == 1

        service.withdraw(r.id, people["a1"])
        assert service.list_attendees(event.id, people["organiser"])["summary"]["registered"] == 0

    def test_every_registration_is_reachable_through_paging(self, app, people, make_user):
        event = open_event(people, capacity=None)
        for i in range(25):
            attendee = make_user(f"bulk{i}@test.com", ["attendee"], name=f"Bulk {i:02d}")
            service.register(event.id, attendee)

        seen, page = [], 1
        while True:
            data = service.list_attendees(event.id, people["organiser"], page=page, page_size=10)
            seen += [r["id"] for r in data["registrations"]]
            if page >= data["pages"]:
                break
            page += 1

        assert data["total"] == 25 and data["pages"] == 3
        assert len(seen) == 25 and len(set(seen)) == 25  # none cut off, none repeated

    def test_page_size_is_capped_and_bad_paging_values_are_safe(self, app, people):
        event = open_event(people)

        data = service.list_attendees(event.id, people["organiser"], page=-4, page_size=100000)

        assert data["page"] == 1 and data["pageSize"] == service.MAX_PAGE_SIZE

    def test_only_planning_details_are_exposed(self, app, people):
        event = self._fill(people)

        row = service.list_attendees(event.id, people["organiser"])["registrations"][0]

        assert set(row) == {"id", "attendeeName", "status", "queuePosition", "registeredAt"}
