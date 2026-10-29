"""Attendee notifications (Notification System, "Notify attendees on registration changes").

One test class per acceptance criterion:

  AC1  Opted-in Attendee is told when registration opens or closes, with the event
       name and the new status.
  AC2  A registered / waitlisted Attendee gets ONE notification per status change,
       showing the old status, the new status and the event name.
  AC3  When a place is released, ONLY the first Attendee in waiting-list order is
       notified; nobody else on the list.
  AC4  Only Attendees affected by the event are notified.

Tests drive the real registration service and then look at who was notified and what
the notification says, the same way the Notification System tests do.
"""
from datetime import time, timedelta

import pytest

from app.common.time import utcnow
from app.events.services import status
from app.extensions import db
from app.models.event import Event
from app.models.notification import TYPE_REGISTRATION_CHANGE, Notification
from app.registrations import service as registrations
from app.registrations.service import Conflict


# --------------------------------------------------------------------- helpers
def inbox(user_id, type_=None):
    query = Notification.query.filter_by(recipient_id=user_id)
    if type_:
        query = query.filter_by(type=type_)
    return query.order_by(Notification.id).all()


def count_all():
    return Notification.query.count()


def make_public_event(organiser_id, coordinator_id, capacity=1, name="Gala Night", status_="confirmed"):
    event = Event(
        organiser_id=organiser_id,
        coordinator_id=coordinator_id,
        status=status_,
        name=name,
        purpose="Fundraising",
        description="Annual fundraising gala",
        category="Social",
        proposed_date=(utcnow() + timedelta(days=30)).date(),
        proposed_time=time(19, 0),
        expected_attendance=120,
        capacity_needed=150,
        required_layout="banquet",
        accessibility_needs="Step-free access",
        registration_required=True,
        intended_capacity=capacity,
    )
    db.session.add(event)
    db.session.commit()
    return event


@pytest.fixture()
def attendees(make_user):
    return [make_user(f"att{i}@test.com", ["attendee"], name=f"Attendee {i}") for i in range(1, 6)]


@pytest.fixture()
def others(make_user):
    """People who must never receive an attendee notification."""
    return {
        "venue": make_user("other-venue@test.com", ["venue_staff"], name="Vic Venue"),
        "tech": make_user("other-tech@test.com", ["technical_support_staff"], name="Tia Tech"),
    }


def open_event(organiser, coordinator, capacity=1, **kw):
    event = make_public_event(organiser, coordinator, capacity=capacity, **kw)
    registrations.open_registration(event.id, organiser)
    return event


def status_pair(notification):
    return notification.data["oldStatus"], notification.data["newStatus"]


# =====================================================================
# AC1  Opted-in Attendee: registration opens or closes
# =====================================================================
class TestAC1RegistrationOpensOrCloses:
    def test_opted_in_attendee_is_notified_when_registration_opens(self, app, organiser, coordinator, attendees):
        event = make_public_event(organiser, coordinator)
        registrations.set_following(event.id, attendees[0], True)

        registrations.open_registration(event.id, organiser)

        [n] = inbox(attendees[0])
        assert n.type == TYPE_REGISTRATION_CHANGE
        assert n.title == "Registration open"
        assert "Gala Night" in n.message and "open" in n.message  # event name + new status
        assert n.data["registrationOpen"] is True

    def test_opted_in_attendee_is_notified_when_registration_closes(self, app, organiser, coordinator, attendees):
        event = open_event(organiser, coordinator)
        registrations.set_following(event.id, attendees[0], True)

        registrations.close_registration(event.id, organiser)

        [n] = inbox(attendees[0])
        assert n.title == "Registration closed"
        assert "Gala Night" in n.message and "closed" in n.message
        assert n.data["registrationOpen"] is False

    def test_notification_is_unread_and_links_to_the_event(self, app, organiser, coordinator, attendees):
        event = make_public_event(organiser, coordinator)
        registrations.set_following(event.id, attendees[0], True)

        registrations.open_registration(event.id, organiser)

        [n] = inbox(attendees[0])
        assert n.is_read is False
        assert n.event_id == event.id and n.link == f"/attendee/events/{event.id}"

    # def test_attendee_who_did_not_opt_in_hears_nothing(self, app, organiser, coordinator, attendees):
    #     event = make_public_event(organiser, coordinator)

    #     registrations.open_registration(event.id, organiser)
    #     registrations.close_registration(event.id, organiser)

    #     assert count_all() == 0

    def test_attendee_who_opted_out_before_opening_hears_nothing(self, app, organiser, coordinator, attendees):
        event = make_public_event(organiser, coordinator)
        registrations.set_following(event.id, attendees[0], True)
        registrations.set_following(event.id, attendees[0], False)

        registrations.open_registration(event.id, organiser)

        assert inbox(attendees[0]) == []

    def test_every_follower_gets_exactly_one_notification(self, app, organiser, coordinator, attendees):
        event = make_public_event(organiser, coordinator)
        for attendee in attendees[:3]:
            registrations.set_following(event.id, attendee, True)

        registrations.open_registration(event.id, organiser)

        assert [len(inbox(a)) for a in attendees[:3]] == [1, 1, 1]
        assert inbox(attendees[3]) == [] and inbox(attendees[4]) == []

    def test_following_twice_does_not_double_the_notification(self, app, organiser, coordinator, attendees):
        event = make_public_event(organiser, coordinator)
        registrations.set_following(event.id, attendees[0], True)
        registrations.set_following(event.id, attendees[0], True)

        registrations.open_registration(event.id, organiser)

        assert len(inbox(attendees[0])) == 1

    def test_open_close_reopen_gives_one_notification_per_change_in_order(self, app, organiser, coordinator, attendees):
        event = make_public_event(organiser, coordinator)
        registrations.set_following(event.id, attendees[0], True)

        registrations.open_registration(event.id, organiser)
        registrations.close_registration(event.id, organiser)
        registrations.open_registration(event.id, organiser)

        assert [n.title for n in inbox(attendees[0])] == [
            "Registration open", "Registration closed", "Registration open",
        ]

    def test_only_the_event_that_changed_notifies_its_followers(self, app, organiser, coordinator, attendees):
        event = make_public_event(organiser, coordinator, name="Gala Night")
        other = make_public_event(organiser, coordinator, name="Quiz Night")
        registrations.set_following(event.id, attendees[0], True)
        registrations.set_following(other.id, attendees[0], True)

        registrations.open_registration(other.id, organiser)

        [n] = inbox(attendees[0])
        assert "Quiz Night" in n.message and "Gala Night" not in n.message

    def test_following_after_the_event_opened_gives_no_late_notification(self, app, organiser, coordinator, attendees):
        event = open_event(organiser, coordinator)

        registrations.set_following(event.id, attendees[0], True)

        assert inbox(attendees[0]) == []

    def test_opening_an_already_open_event_notifies_nobody_again(self, app, organiser, coordinator, attendees):
        event = make_public_event(organiser, coordinator)
        registrations.set_following(event.id, attendees[0], True)
        registrations.open_registration(event.id, organiser)

        with pytest.raises(Conflict, match="already open"):
            registrations.open_registration(event.id, organiser)

        assert len(inbox(attendees[0])) == 1

    def test_a_failed_open_notifies_nobody(self, app, organiser, coordinator, attendees):
        event = make_public_event(organiser, coordinator)
        registrations.set_following(event.id, attendees[0], True)
        event.status = "cancelled"  # registration can no longer be opened
        db.session.commit()

        with pytest.raises(Conflict):
            registrations.open_registration(event.id, organiser)

        assert count_all() == 0


# =====================================================================
# AC2  Status changes: one notification with old status, new status, event name
# =====================================================================
class TestAC2StatusChanges:
    def test_waitlisted_to_registered(self, app, organiser, coordinator, attendees):
        event = open_event(organiser, coordinator, capacity=1)
        holder = registrations.register(event.id, attendees[0])
        registrations.join_waitlist(event.id, attendees[1])

        registrations.withdraw(holder.id, attendees[0])

        [n] = inbox(attendees[1])
        assert status_pair(n) == ("waitlisted", "registered")
        assert 'from Waiting list to Registered' in n.message and "Gala Night" in n.message

    def test_registered_to_withdrawn(self, app, organiser, coordinator, attendees):
        event = open_event(organiser, coordinator, capacity=3)
        mine = registrations.register(event.id, attendees[0])

        registrations.withdraw(mine.id, attendees[0])

        [n] = inbox(attendees[0])
        assert status_pair(n) == ("registered", "withdrawn")
        assert "from Registered to Withdrawn" in n.message and "Gala Night" in n.message

    def test_waitlisted_to_withdrawn(self, app, organiser, coordinator, attendees):
        event = open_event(organiser, coordinator, capacity=1)
        registrations.register(event.id, attendees[0])
        waiting = registrations.join_waitlist(event.id, attendees[1])

        registrations.withdraw(waiting.id, attendees[1])

        [n] = inbox(attendees[1])
        assert status_pair(n) == ("waitlisted", "withdrawn")
        assert "from Waiting list to Withdrawn" in n.message

    def test_registered_to_cancelled_when_the_event_is_cancelled(self, app, organiser, coordinator, attendees):
        event = open_event(organiser, coordinator, capacity=3)
        registrations.register(event.id, attendees[0])

        status.cancel_event(event.id, coordinator, "The venue flooded overnight.")

        [n] = inbox(attendees[0])
        assert status_pair(n) == ("registered", "cancelled")
        assert "from Registered to Cancelled" in n.message and "Gala Night" in n.message
        assert "The venue flooded overnight." in n.message

    def test_waitlisted_to_cancelled_when_the_event_is_cancelled(self, app, organiser, coordinator, attendees):
        event = open_event(organiser, coordinator, capacity=1)
        registrations.register(event.id, attendees[0])
        registrations.join_waitlist(event.id, attendees[1])

        status.cancel_event(event.id, coordinator, "No longer going ahead.")

        assert status_pair(inbox(attendees[1])[0]) == ("waitlisted", "cancelled")

    def test_waiting_list_position_change_shows_old_and_new_position(self, app, organiser, coordinator, attendees):
        event = open_event(organiser, coordinator, capacity=1)
        registrations.register(event.id, attendees[0])
        leaving = registrations.join_waitlist(event.id, attendees[1])
        registrations.join_waitlist(event.id, attendees[2])
        registrations.join_waitlist(event.id, attendees[3])

        registrations.withdraw(leaving.id, attendees[1])

        [n2] = inbox(attendees[2])
        [n3] = inbox(attendees[3])
        assert (n2.data["oldPosition"], n2.data["newPosition"]) == (2, 1)
        assert (n3.data["oldPosition"], n3.data["newPosition"]) == (3, 2)
        assert "moved from 2 to 1" in n2.message and "Gala Night" in n2.message

    def test_attendees_ahead_of_a_leaver_get_no_position_notification(self, app, organiser, coordinator, attendees):
        event = open_event(organiser, coordinator, capacity=1)
        registrations.register(event.id, attendees[0])
        registrations.join_waitlist(event.id, attendees[1])
        leaving = registrations.join_waitlist(event.id, attendees[2])

        registrations.withdraw(leaving.id, attendees[2])

        assert inbox(attendees[1]) == []  # was ahead of the leaver: position unchanged

    def test_one_notification_per_change_with_no_duplicates(self, app, organiser, coordinator, attendees):
        event = open_event(organiser, coordinator, capacity=1)
        holder = registrations.register(event.id, attendees[0])
        registrations.join_waitlist(event.id, attendees[1])

        registrations.withdraw(holder.id, attendees[0])

        assert len(inbox(attendees[0])) == 1 and len(inbox(attendees[1])) == 1
        # reading the event again must not repeat the promotion notice
        registrations.get_event(event.id, attendees[1])
        registrations.my_registrations(attendees[1])
        assert len(inbox(attendees[1])) == 1

    def test_raising_the_capacity_promotes_and_notifies_once(self, app, organiser, coordinator, attendees):
        event = open_event(organiser, coordinator, capacity=1)
        registrations.register(event.id, attendees[0])
        registrations.join_waitlist(event.id, attendees[1])

        event.intended_capacity = 2
        db.session.commit()
        registrations.get_event(event.id, attendees[2])  # any read brings the list up to date
        registrations.get_event(event.id, attendees[2])

        [n] = inbox(attendees[1])
        assert status_pair(n) == ("waitlisted", "registered")

    def test_status_notices_do_not_depend_on_following_the_event(self, app, organiser, coordinator, attendees):
        event = open_event(organiser, coordinator, capacity=1)
        holder = registrations.register(event.id, attendees[0])
        registrations.join_waitlist(event.id, attendees[1])  # never opted in to "Notify me"

        registrations.withdraw(holder.id, attendees[0])

        assert len(inbox(attendees[1])) == 1

    def test_a_refused_withdrawal_sends_nothing(self, app, organiser, coordinator, attendees):
        event = open_event(organiser, coordinator, capacity=3)
        mine = registrations.register(event.id, attendees[0])
        registrations.withdraw(mine.id, attendees[0])
        before = count_all()

        with pytest.raises(Conflict, match="already withdrawn"):
            registrations.withdraw(mine.id, attendees[0])

        assert count_all() == before


# =====================================================================
# AC3  A place is released: only the first Attendee on the waiting list is told
# =====================================================================
class TestAC3OnlyTheFirstWaitingAttendeeIsNotified:
    def test_first_in_waiting_list_order_is_notified_and_nobody_else(self, app, organiser, coordinator, attendees):
        event = open_event(organiser, coordinator, capacity=1)
        holder = registrations.register(event.id, attendees[0])
        registrations.join_waitlist(event.id, attendees[1])
        registrations.join_waitlist(event.id, attendees[2])
        registrations.join_waitlist(event.id, attendees[3])

        registrations.withdraw(holder.id, attendees[0])

        [promoted] = inbox(attendees[1])
        assert promoted.title == "A place is available for you"
        assert status_pair(promoted) == ("waitlisted", "registered")
        assert inbox(attendees[2]) == [] and inbox(attendees[3]) == []

    def test_order_is_the_order_they_joined_not_the_order_of_their_user_ids(self, app, organiser, coordinator, attendees):
        event = open_event(organiser, coordinator, capacity=1)
        holder = registrations.register(event.id, attendees[0])
        registrations.join_waitlist(event.id, attendees[3])  # joined first, highest user id
        registrations.join_waitlist(event.id, attendees[1])

        registrations.withdraw(holder.id, attendees[0])

        assert len(inbox(attendees[3])) == 1
        assert inbox(attendees[1]) == []

    def test_the_waiting_list_does_not_hear_about_everyone_moving_up(self, app, organiser, coordinator, attendees):
        event = open_event(organiser, coordinator, capacity=1)
        holder = registrations.register(event.id, attendees[0])
        registrations.join_waitlist(event.id, attendees[1])
        registrations.join_waitlist(event.id, attendees[2])

        registrations.withdraw(holder.id, attendees[0])

        # attendee 2 moved from position 2 to 1, but "no one else is notified at that point"
        assert all(n.data.get("kind") != "position_changed" for n in inbox(attendees[2]))
        assert inbox(attendees[2]) == []

    def test_two_places_free_notifies_exactly_the_first_two_in_order(self, app, organiser, coordinator, attendees):
        event = open_event(organiser, coordinator, capacity=1)
        registrations.register(event.id, attendees[0])
        for attendee in attendees[1:4]:
            registrations.join_waitlist(event.id, attendee)

        event.intended_capacity = 3  # two more places
        db.session.commit()
        registrations.get_event(event.id, attendees[4])

        assert len(inbox(attendees[1])) == 1 and len(inbox(attendees[2])) == 1
        assert inbox(attendees[3]) == []
        assert inbox(attendees[1])[0].id < inbox(attendees[2])[0].id  # told in queue order

    def test_withdrawing_with_nobody_waiting_only_confirms_to_the_leaver(self, app, organiser, coordinator, attendees):
        event = open_event(organiser, coordinator, capacity=3)
        mine = registrations.register(event.id, attendees[0])
        registrations.register(event.id, attendees[1])

        registrations.withdraw(mine.id, attendees[0])

        assert len(inbox(attendees[0])) == 1
        assert inbox(attendees[1]) == []  # another registered attendee is not told

    def test_a_waitlisted_attendee_leaving_does_not_announce_a_free_place(self, app, organiser, coordinator, attendees):
        event = open_event(organiser, coordinator, capacity=1)
        registrations.register(event.id, attendees[0])
        leaving = registrations.join_waitlist(event.id, attendees[1])
        registrations.join_waitlist(event.id, attendees[2])

        registrations.withdraw(leaving.id, attendees[1])

        assert all(n.title != "A place is available for you" for a in attendees for n in inbox(a))
        assert inbox(attendees[0]) == []

    def test_the_attendee_holding_the_place_is_not_told_about_the_promotion(self, app, organiser, coordinator, attendees):
        event = open_event(organiser, coordinator, capacity=2)
        registrations.register(event.id, attendees[0])
        holder = registrations.register(event.id, attendees[1])
        registrations.join_waitlist(event.id, attendees[2])

        registrations.withdraw(holder.id, attendees[1])

        assert inbox(attendees[0]) == []  # still registered, nothing changed for them


# =====================================================================
# AC4  Only Attendees affected by the event are notified
# =====================================================================
class TestAC4OnlyAffectedAttendees:
    def test_cancelling_one_event_does_not_notify_attendees_of_another(self, app, organiser, coordinator, attendees):
        event = open_event(organiser, coordinator, capacity=5, name="Gala Night")
        other = open_event(organiser, coordinator, capacity=5, name="Quiz Night")
        registrations.register(event.id, attendees[0])
        registrations.register(other.id, attendees[1])

        status.cancel_event(event.id, coordinator, "Cancelled for testing.")

        assert len(inbox(attendees[0])) == 1
        assert inbox(attendees[1]) == []

    def test_an_attendee_in_two_events_only_hears_about_the_affected_one(self, app, organiser, coordinator, attendees):
        event = open_event(organiser, coordinator, capacity=5, name="Gala Night")
        other = open_event(organiser, coordinator, capacity=5, name="Quiz Night")
        registrations.register(event.id, attendees[0])
        registrations.register(other.id, attendees[0])

        status.cancel_event(other.id, coordinator, "Cancelled for testing.")

        [n] = inbox(attendees[0])
        assert n.event_id == other.id and "Quiz Night" in n.message

    def test_cancellation_reaches_registered_and_waitlisted_but_not_withdrawn(self, app, organiser, coordinator, attendees):
        event = open_event(organiser, coordinator, capacity=1)
        registrations.register(event.id, attendees[0])
        registrations.join_waitlist(event.id, attendees[1])
        gone = registrations.join_waitlist(event.id, attendees[2])
        registrations.withdraw(gone.id, attendees[2])
        before = len(inbox(attendees[2]))  # their own withdrawal confirmation

        status.cancel_event(event.id, coordinator, "Cancelled for testing.")

        assert len(inbox(attendees[0])) == 1 and len(inbox(attendees[1])) == 1
        assert len(inbox(attendees[2])) == before  # already withdrawn: not affected any more
        assert inbox(attendees[3]) == [] and inbox(attendees[4]) == []

    def test_open_and_close_reach_followers_only_not_every_attendee(self, app, organiser, coordinator, attendees):
        event = make_public_event(organiser, coordinator)
        registrations.set_following(event.id, attendees[0], True)

        registrations.open_registration(event.id, organiser)
        registrations.close_registration(event.id, organiser)

        assert len(inbox(attendees[0])) == 2
        assert all(inbox(a) == [] for a in attendees[1:])

    def test_a_registered_attendee_who_is_not_following_is_not_told_about_close(self, app, organiser, coordinator, attendees):
        event = open_event(organiser, coordinator, capacity=3)
        registrations.register(event.id, attendees[0])

        registrations.close_registration(event.id, organiser)

        assert inbox(attendees[0]) == []

    def test_staff_never_receive_attendee_notifications(self, app, organiser, coordinator, attendees, others):
        event = open_event(organiser, coordinator, capacity=1)
        registrations.set_following(event.id, attendees[0], True)
        holder = registrations.register(event.id, attendees[0])
        registrations.join_waitlist(event.id, attendees[1])
        registrations.withdraw(holder.id, attendees[0])
        registrations.close_registration(event.id, organiser)
        status.cancel_event(event.id, coordinator, "Cancelled for testing.")

        registration_notices = lambda uid: inbox(uid, TYPE_REGISTRATION_CHANGE)  # noqa: E731
        assert registration_notices(organiser) == [] and registration_notices(coordinator) == []
        assert all(registration_notices(uid) == [] for uid in others.values())

    def test_each_notification_belongs_to_exactly_one_recipient(self, app, organiser, coordinator, attendees):
        event = open_event(organiser, coordinator, capacity=1)
        holder = registrations.register(event.id, attendees[0])
        registrations.join_waitlist(event.id, attendees[1])
        registrations.withdraw(holder.id, attendees[0])

        by_recipient = {a: inbox(a) for a in attendees[:2]}

        ids = [n.id for notices in by_recipient.values() for n in notices]
        assert len(ids) == len(set(ids)) == 2


# ---------------------------------------------------------------------------
# The same notifications seen through the API (what the Attendee actually sees)
# ---------------------------------------------------------------------------
class TestAttendeeSeesOnlyTheirOwnNotifications:
    def test_the_attendee_lists_their_own_promotion_notice(self, app, client, auth_header, organiser, coordinator, attendees):
        event = open_event(organiser, coordinator, capacity=1)
        holder = registrations.register(event.id, attendees[0])
        registrations.join_waitlist(event.id, attendees[1])
        registrations.withdraw(holder.id, attendees[0])

        listed = client.get("/api/notifications", headers=auth_header("att2@test.com")).get_json()

        assert len(listed) == 1
        assert listed[0]["isRead"] is False and "Gala Night" in listed[0]["message"]
        assert client.get("/api/notifications/unread-count", headers=auth_header("att2@test.com")).get_json()["count"] == 1

    def test_another_attendee_cannot_see_or_mark_it_read(self, app, client, auth_header, organiser, coordinator, attendees):
        event = open_event(organiser, coordinator, capacity=1)
        holder = registrations.register(event.id, attendees[0])
        registrations.join_waitlist(event.id, attendees[1])
        registrations.withdraw(holder.id, attendees[0])
        promoted = inbox(attendees[1])[0]

        stranger = auth_header("att3@test.com")

        assert client.get("/api/notifications", headers=stranger).get_json() == []
        assert client.post(f"/api/notifications/{promoted.id}/read", headers=stranger).status_code in (403, 404)
        assert Notification.query.get(promoted.id).is_read is False

    def test_opening_it_marks_it_read_and_the_unread_count_drops(self, app, client, auth_header, organiser, coordinator, attendees):
        event = make_public_event(organiser, coordinator)
        registrations.set_following(event.id, attendees[0], True)
        registrations.open_registration(event.id, organiser)
        headers = auth_header("att1@test.com")
        [n] = client.get("/api/notifications", headers=headers).get_json()

        client.post(f"/api/notifications/{n['id']}/read", headers=headers)

        assert client.get("/api/notifications/unread-count", headers=headers).get_json()["count"] == 0
        assert len(client.get("/api/notifications", headers=headers).get_json()) == 1  # still viewable

    def test_anonymous_users_cannot_read_notifications(self, app, client):
        assert client.get("/api/notifications").status_code == 401
