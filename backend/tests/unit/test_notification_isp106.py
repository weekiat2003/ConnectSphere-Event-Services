from datetime import datetime
from app.events.services import status

import pytest

from app.equipment.services import reservation as reservation_service
from app.events.services import review
from app.events.services import update as updateservice
from app.extensions import db
from app.models.equipment import EquipmentItem, EquipmentReservation
from app.models.event import Event, EventEquipmentRequirement
from app.models.notification import (
    TYPE_EQUIPMENT_RESERVATION_UPDATE,
    TYPE_NEW_EQUIPMENT_REQUEST,
    Notification,
)
from app.models.user import User
from app.notifications.services import triggers


@pytest.fixture
def tech(make_user):
    return make_user("tech@test.com", ["technical_support_staff"], name="Tia Tech")


def inbox(user_id):
    return (Notification.query
            .filter_by(recipient_id=user_id, type=TYPE_NEW_EQUIPMENT_REQUEST)
            .order_by(Notification.id).all())


def make_with_lines(make_event, organiser, coordinator, status, lines=(("Projector", 2),)):
    event = db.session.get(Event, make_event(organiser, status=status, coordinator_id=coordinator))
    for type_, quantity in lines:
        event.equipment_requirements.append(
            EventEquipmentRequirement(equipment_type=type_, quantity=quantity))
    db.session.commit()
    return event


def save(event, coordinator, requirements):
    updateservice.update_event_fields(
        event, db.session.get(User, coordinator),
        {"equipment_requirements": requirements}, offline_review_confirmed=True)


def test_an_unchanged_equipment_save_sends_nothing(app, organiser, coordinator, make_event, tech):
    event = make_with_lines(make_event, organiser, coordinator, "planning")
    line = event.equipment_requirements[0]
    save(event, coordinator, [{"id": line.id, "type": "Projector", "quantity": 2}])
    assert inbox(tech) == []


def test_editing_another_field_sends_nothing(app, organiser, coordinator, make_event, tech):
    event = make_with_lines(make_event, organiser, coordinator, "planning")
    updateservice.update_event_fields(event, db.session.get(User, coordinator), {"name": "Renamed gala"})
    assert inbox(tech) == []


def test_adding_a_line_sends_one_update_asking_for_a_recheck(app, organiser, coordinator, make_event, tech):
    event = make_with_lines(make_event, organiser, coordinator, "planning")
    line = event.equipment_requirements[0]
    save(event, coordinator, [{"id": line.id, "type": "Projector", "quantity": 2},
                              {"type": "Speaker", "quantity": 3},
                              {"type": "Microphone", "quantity": 1}])
    notices = inbox(tech)
    assert len(notices) == 1
    assert notices[0].data["kind"] == "updated"
    assert "3 × Speaker" in notices[0].message and "1 × Microphone" in notices[0].message
    assert "re-check suitability" in notices[0].message
    assert "updated" in notices[0].message and "submitted" not in notices[0].message


def test_removing_a_line_notifies(app, organiser, coordinator, make_event, tech):
    event = make_with_lines(make_event, organiser, coordinator, "planning",
                            lines=(("Projector", 2), ("Speaker", 3)))
    keep = event.equipment_requirements[0]
    save(event, coordinator, [{"id": keep.id, "type": "Projector", "quantity": 2}])
    notices = inbox(tech)
    assert len(notices) == 1 and "Speaker" not in notices[0].message


def test_no_notification_while_the_event_is_under_review(app, organiser, coordinator, make_event, tech):
    event = make_with_lines(make_event, organiser, coordinator, "under_review")
    save(event, coordinator, [{"type": "Speaker", "quantity": 3}])
    assert inbox(tech) == []


def test_only_technical_support_is_notified_once_each(app, organiser, coordinator, make_event, make_user, tech):
    both = make_user("both@test.com", ["technical_support_staff", "event_coordinator"], name="Bo Both")
    event = make_with_lines(make_event, organiser, coordinator, "under_review")
    review.approve_event(event, coordinator)

    assert event.status == "approved"

    # Under the new workflow, approval alone does not start planning. The tests that expect a planning-stage notification should explicitly transition the event to planning after approval.

    status.change_status(event, "planning", coordinator)

    assert len(inbox(tech)) == 1
    assert len(inbox(both)) == 1
    assert inbox(organiser) == []
    assert inbox(coordinator) == []

def test_a_failing_notification_does_not_block_approval(
    app, organiser, coordinator, make_event, monkeypatch
):
    event = make_with_lines(
        make_event,
        organiser,
        coordinator,
        "under_review",
    )

    # Approval should only move the event to approved.
    review.approve_event(event, coordinator)
    assert event.status == "approved"

    # Simulate a notification service failure.
    def boom(*args, **kwargs):
        raise RuntimeError("notification service down")

    monkeypatch.setattr(triggers, "notify_role", boom)

    # Notifications should not block the transition to planning.
    app.config["TESTING"] = False

    status.change_status(event, "planning", coordinator)

    db.session.expire_all()
    saved_event = db.session.get(Event, event.id)

    assert saved_event.status == "planning"

def reservation_notice_inbox(user_id):
    return Notification.query.filter_by(
        recipient_id=user_id, type=TYPE_EQUIPMENT_RESERVATION_UPDATE
    ).order_by(Notification.id).all()


def make_reservable_event(make_event, organiser, coordinator=None, quantity=2):
    event_id = make_event(
        organiser, status="approved", coordinator_id=coordinator
    )
    event = db.session.get(Event, event_id)
    requirement = EventEquipmentRequirement(
        event_id=event.id, equipment_type="Projector", quantity=quantity
    )
    item = EquipmentItem(name="Projector", total_quantity=10)
    db.session.add_all([requirement, item])
    db.session.commit()
    return event, requirement, item


def make_reservation(event, requirement, item, created_by):
    return reservation_service.reserve(
        event,
        requirement,
        item,
        datetime(2026, 12, 1, 10),
        datetime(2026, 12, 1, 11),
        created_by,
    )


def test_equipment_reservation_notifies_only_assigned_coordinator(
    app, organiser, coordinator, make_event, make_user, tech
):
    other_coordinator = make_user("other-coordinator@test.com", ["event_coordinator"])
    event, requirement, item = make_reservable_event(make_event, organiser, coordinator)

    reservation = make_reservation(event, requirement, item, tech)

    notices = reservation_notice_inbox(coordinator)
    assert len(notices) == 1
    assert notices[0].title == "Equipment reserved"
    assert notices[0].message == (
        '2 × Projector for "Test Event", '
        "2026-12-01T10:00:00 to 2026-12-01T11:00:00"
    )
    assert notices[0].data == {
        "event_id": event.id,
        "requirement_id": requirement.id,
        "reservation_id": reservation.id,
        "kind": "reserved",
    }
    assert reservation_notice_inbox(other_coordinator) == []
    assert reservation_notice_inbox(tech) == []


def test_refused_equipment_reservation_sends_no_notification(
    app, organiser, coordinator, make_event, tech
):
    event, requirement, item = make_reservable_event(make_event, organiser, coordinator)
    item.status = "retired"
    db.session.commit()

    with pytest.raises(reservation_service.ReservationError):
        make_reservation(event, requirement, item, tech)

    assert reservation_notice_inbox(coordinator) == []


def test_insufficient_stock_notifies_coordinator_and_later_reservation_clears_flag(
    app, organiser, coordinator, make_event, tech
):
    event, requirement, item = make_reservable_event(
        make_event, organiser, coordinator, quantity=50
    )
    requirement.needs_recheck = True
    db.session.commit()

    with pytest.raises(reservation_service.ReservationError, match="Not enough"):
        reservation_service.reserve(
            event,
            requirement,
            item,
            datetime(2026, 12, 1, 10),
            datetime(2026, 12, 1, 11),
            tech,
            quantity=50,
        )

    notices = reservation_notice_inbox(coordinator)
    assert len(notices) == 1
    assert notices[0].data == {
        "event_id": event.id,
        "requirement_id": requirement.id,
        "kind": "reservation_refused",
        "requested_quantity": 50,
        "available_quantity": 10,
    }
    db.session.expire_all()
    assert db.session.get(EventEquipmentRequirement, requirement.id).status == "requested"
    assert db.session.get(EventEquipmentRequirement, requirement.id).needs_recheck is True

    reservation = reservation_service.reserve(
        event,
        requirement,
        item,
        datetime(2026, 12, 1, 10),
        datetime(2026, 12, 1, 11),
        tech,
        quantity=10,
    )

    db.session.expire_all()
    updated = db.session.get(EventEquipmentRequirement, requirement.id)
    assert reservation.quantity == 10
    assert updated.status == "confirmed"
    assert updated.needs_recheck is False


def test_manual_equipment_release_notifies_assigned_coordinator(
    app, organiser, coordinator, make_event, tech
):
    event, requirement, item = make_reservable_event(make_event, organiser, coordinator)
    reservation = make_reservation(event, requirement, item, tech)
    db.session.expire_all()
    reservation = db.session.get(EquipmentReservation, reservation.id)
    db.session.query(Notification).delete()
    db.session.commit()

    reservation_service.release(reservation, actor_id=tech)

    notices = reservation_notice_inbox(coordinator)
    assert len(notices) == 1
    assert notices[0].title == "Equipment reservation released"
    assert notices[0].data["kind"] == "released"
    assert notices[0].data["reservation_id"] == reservation.id


def test_equipment_reservation_without_coordinator_sends_no_notification(
    app, organiser, make_event, tech
):
    event, requirement, item = make_reservable_event(make_event, organiser)

    make_reservation(event, requirement, item, tech)

    assert reservation_notice_inbox(tech) == []


def test_equipment_reservation_does_not_notify_actor_coordinator(
    app, organiser, coordinator, make_event
):
    event, requirement, item = make_reservable_event(make_event, organiser, coordinator)

    reservation = make_reservation(event, requirement, item, coordinator)

    assert reservation_notice_inbox(coordinator) == []
    reservation_service.release(reservation, actor_id=coordinator)
    assert reservation_notice_inbox(coordinator) == []