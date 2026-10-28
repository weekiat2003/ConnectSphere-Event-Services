import pytest

from app.events.services import review
from app.events.services import update as updateservice
from app.extensions import db
from app.models.event import Event, EventEquipmentRequirement
from app.models.notification import TYPE_NEW_EQUIPMENT_REQUEST, Notification
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
    assert len(inbox(tech)) == 1 and len(inbox(both)) == 1
    assert inbox(organiser) == [] and inbox(coordinator) == []


def test_a_failing_notification_does_not_block_approval(app, organiser, coordinator, make_event, tech, monkeypatch):
    event = make_with_lines(make_event, organiser, coordinator, "under_review")
    app.config["TESTING"] = False

    def boom(*args, **kwargs):
        raise RuntimeError("notification service down")

    monkeypatch.setattr(triggers, "notify_role", boom)
    review.approve_event(event, coordinator)
    db.session.expire_all()
    assert db.session.get(Event, event.id).status == "planning"