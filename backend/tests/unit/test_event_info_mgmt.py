from datetime import datetime

import pytest
from app.extensions import db
from app.models.event import Event, EventEquipmentRequirement, EventSafetyAssessment, EventStatusHistory
from app.models.notification import Notification
from app.models.venue import Venue, VenueBooking, BOOKING_APPROVED, BOOKING_HELD
from app.events.services.update import (
    update_event_fields, EventLockedError, EventNotEditableStatusError,
    OfflineReviewNotConfirmedError, EventValidationError,
)
from app.venues.services.preparation import (
    update_venue_preparation,
    PreparationUpdateError,
)


def _make_event_change_booking(event_id, status=BOOKING_APPROVED):
    venue = Venue(name="Hall A", capacity=100, created_by=1)
    db.session.add(venue)
    db.session.commit()
    booking = VenueBooking(
        event_id=event_id, venue_id=venue.id, requested_by=1, status=status,
        start_datetime=datetime(2026, 12, 1, 9), end_datetime=datetime(2026, 12, 1, 17),
    )
    db.session.add(booking)
    db.session.commit()
    return booking


class TestUpdateEventFields:
    def test_coordinator_edits_ordinary_field(self, app, coordinator, make_event):
        with app.app_context():
            from app.models.user import User
            event_id = make_event(organiser_id=1, status="planning", coordinator_id=coordinator)
            event = Event.query.get(event_id)
            user = User.query.get(coordinator)

            update_event_fields(event, user, {"name": "Updated Name"})

            assert Event.query.get(event_id).name == "Updated Name"
            assert len(event.field_edit_logs) == 1
            assert event.field_edit_logs[0].was_rejected is False
            assert event.field_edit_logs[0].changed_by == coordinator
            assert event.field_edit_logs[0].created_at is not None

    @pytest.mark.parametrize("status", ["under_review", "approved", "planning"])
    def test_editable_statuses_allow_edits(self, app, coordinator, make_event, status):
        with app.app_context():
            from app.models.user import User
            event_id = make_event(organiser_id=1, status=status, coordinator_id=coordinator)
            event = Event.query.get(event_id)
            user = User.query.get(coordinator)

            update_event_fields(event, user, {"description": "New description"})

            assert Event.query.get(event_id).description == "New description"
            assert Event.query.get(event_id).status == status  # an ordinary edit keeps the status

    def test_edit_during_safety_check_is_saved_and_reverts_to_planning(self, app, coordinator, make_event):
        with app.app_context():
            from app.models.user import User
            event_id = make_event(organiser_id=1, status="safety_check", coordinator_id=coordinator)
            event = Event.query.get(event_id)
            user = User.query.get(coordinator)

            update_event_fields(event, user, {"description": "New description"})

            refreshed = Event.query.get(event_id)
            assert refreshed.description == "New description"
            assert refreshed.status == "planning"
            history = EventStatusHistory.query.filter_by(event_id=event_id, new_status="planning").one()
            assert history.old_status == "safety_check"
            assert history.reason == "Edited during safety check"

    def test_significant_field_requires_offline_review_confirmation(self, app, coordinator, make_event):
        with app.app_context():
            from app.models.user import User
            event_id = make_event(organiser_id=1, status="planning", coordinator_id=coordinator)
            event = Event.query.get(event_id)
            user = User.query.get(coordinator)

            with pytest.raises(OfflineReviewNotConfirmedError):
                update_event_fields(event, user, {"expected_attendance": 80})

            # Record is unchanged -- rejection happened before any write.
            assert Event.query.get(event_id).expected_attendance != 80

    def test_significant_field_with_confirmation_saves_and_flags_arrangements(self, app, coordinator, make_event):
        with app.app_context():
            from app.models.user import User
            event_id = make_event(organiser_id=1, status="planning", coordinator_id=coordinator,
                                   expected_attendance=50, capacity_needed=60)
            booking = _make_event_change_booking(event_id)
            event = Event.query.get(event_id)
            user = User.query.get(coordinator)

            update_event_fields(event, user, {"expected_attendance": 55}, offline_review_confirmed=True)

            assert Event.query.get(event_id).expected_attendance == 55
            refreshed = VenueBooking.query.get(booking.id)
            assert refreshed.needs_reconsideration is True
            assert refreshed.status == BOOKING_APPROVED  # not auto-cancelled

    def test_significant_change_flags_tentative_holds_without_cancelling(self, app, coordinator, make_event):
        with app.app_context():
            from app.models.user import User
            event_id = make_event(organiser_id=1, status="planning", coordinator_id=coordinator)
            booking = _make_event_change_booking(event_id, status=BOOKING_HELD)
            event = Event.query.get(event_id)

            update_event_fields(
                event, User.query.get(coordinator), {"expected_attendance": 55},
                offline_review_confirmed=True,
            )

            refreshed = VenueBooking.query.get(booking.id)
            assert refreshed.needs_reconsideration is True
            assert refreshed.status == BOOKING_HELD

    def test_equipment_requirements_can_be_updated_and_audited(self, app, coordinator, make_event):
        with app.app_context():
            from app.models.event import EventEquipmentRequirement
            from app.models.user import User
            event_id = make_event(organiser_id=1, status="planning", coordinator_id=coordinator)
            requirement = EventEquipmentRequirement(
                event_id=event_id, equipment_type="Projector", quantity=1
            )
            db.session.add(requirement)
            db.session.commit()

            update_event_fields(
                Event.query.get(event_id), User.query.get(coordinator),
                {"equipment_requirements": [
                    {"id": requirement.id, "type": "Projector", "quantity": 2}
                ]},
                offline_review_confirmed=True,
            )

            refreshed = EventEquipmentRequirement.query.get(requirement.id)
            assert refreshed.quantity == 2
            assert refreshed.needs_recheck is True
            log = Event.query.get(event_id).field_edit_logs[-1]
            assert log.was_significant is True
            assert log.old_values["equipment_requirements"][0]["quantity"] == 1
            assert log.new_values["equipment_requirements"][0]["quantity"] == 2

    def test_empty_equipment_requirements_clears_existing_items(self, app, coordinator, make_event):
        with app.app_context():
            from app.models.user import User
            event_id = make_event(organiser_id=1, status="planning", coordinator_id=coordinator)
            req = EventEquipmentRequirement(event_id=event_id, equipment_type="Projector", quantity=1)
            db.session.add(req)
            db.session.commit()
            req_id = req.id

            update_event_fields(
                Event.query.get(event_id), User.query.get(coordinator),
                {"equipment_requirements": []},
                offline_review_confirmed=True,
            )

            assert EventEquipmentRequirement.query.filter_by(event_id=event_id).count() == 0
            assert EventEquipmentRequirement.query.get(req_id) is None

    def test_non_list_equipment_requirements_rejected(self, app, coordinator, make_event):
        with app.app_context():
            from app.models.user import User
            event_id = make_event(organiser_id=1, status="planning", coordinator_id=coordinator, name="Original")
            event = Event.query.get(event_id)
            user = User.query.get(coordinator)

            with pytest.raises(EventValidationError) as exc_info:
                update_event_fields(event, user, {"equipment_requirements": "not-a-list"}, offline_review_confirmed=True)

            assert "equipment_requirements" in exc_info.value.field_errors
            assert Event.query.get(event_id).name == "Original"

    def test_unrelated_significant_change_does_not_flag_equipment(self, app, coordinator, make_event):
        with app.app_context():
            from app.models.user import User
            from app.models.event import EventEquipmentRequirement
            event_id = make_event(organiser_id=1, status="planning", coordinator_id=coordinator,
                                   expected_attendance=50, capacity_needed=60)
            req = EventEquipmentRequirement(event_id=event_id, equipment_type="Projector", quantity=2)
            db.session.add(req)
            db.session.commit()
            event = Event.query.get(event_id)
            user = User.query.get(coordinator)

            update_event_fields(event, user, {"capacity_needed": 65}, offline_review_confirmed=True)

            assert EventEquipmentRequirement.query.get(req.id).needs_recheck is False

    def test_non_assigned_coordinator_rejected(self, app, coordinator, make_user, make_event):
        with app.app_context():
            from app.models.user import User
            other_id = make_user("other@test.com", ["event_coordinator"])
            event_id = make_event(organiser_id=1, status="planning", coordinator_id=coordinator)
            event = Event.query.get(event_id)
            other = User.query.get(other_id)

            with pytest.raises(PermissionError):
                update_event_fields(event, other, {"name": "Hijacked"})

            assert Event.query.get(event_id).name != "Hijacked"

    def test_confirmed_event_is_locked_and_audited(self, app, coordinator, make_event):
        with app.app_context():
            from app.models.user import User
            event_id = make_event(organiser_id=1, status="confirmed", coordinator_id=coordinator)
            event = Event.query.get(event_id)
            user = User.query.get(coordinator)

            with pytest.raises(EventLockedError):
                update_event_fields(event, user, {"name": "Too Late"})

            assert Event.query.get(event_id).name != "Too Late"
            assert len(event.field_edit_logs) == 1
            assert event.field_edit_logs[0].was_rejected is True

    def test_lock_check_precedes_ownership_check(self, app, coordinator, make_user, make_event):
        """US-4 AC1 says "any user" -- confirmed lock fires even for a
        Coordinator who isn't even assigned to this event."""
        with app.app_context():
            from app.models.user import User
            other_id = make_user("other2@test.com", ["event_coordinator"])
            event_id = make_event(organiser_id=1, status="confirmed", coordinator_id=coordinator)
            event = Event.query.get(event_id)
            other = User.query.get(other_id)

            with pytest.raises(EventLockedError):
                update_event_fields(event, other, {"name": "Nope"})

    @pytest.mark.parametrize("status", ["draft", "submitted", "completed", "cancelled", "rejected"])
    def test_non_editable_status_rejected(self, app, coordinator, make_event, status):
        with app.app_context():
            from app.models.user import User
            event_id = make_event(organiser_id=1, status=status, coordinator_id=coordinator)
            event = Event.query.get(event_id)
            user = User.query.get(coordinator)

            with pytest.raises(EventNotEditableStatusError):
                update_event_fields(event, user, {"name": "Nope"})

    def test_invalid_value_blocks_save_and_leaves_record_unchanged(self, app, coordinator, make_event):
        with app.app_context():
            from app.models.user import User
            event_id = make_event(organiser_id=1, status="planning", coordinator_id=coordinator, name="Original")
            event = Event.query.get(event_id)
            user = User.query.get(coordinator)

            with pytest.raises(EventValidationError) as exc_info:
                update_event_fields(event, user, {"name": "   "})

            assert "name" in exc_info.value.field_errors
            assert Event.query.get(event_id).name == "Original"

    @pytest.mark.parametrize(
        ("field", "value", "error_field"),
        [
            ("name", " ", "name"),
            ("purpose", "", "purpose"),
            ("description", None, "description"),
            ("proposed_date", None, "proposed_date"),
            ("proposed_time", "", "proposed_time"),
            ("proposed_date", "not-a-date", "proposed_date"),
            ("proposed_time", "not-a-time", "proposed_time"),
            ("expected_attendance", 0, "expected_attendance"),
            ("expected_attendance", "many", "expected_attendance"),
            ("capacity_needed", None, "capacity_needed"),
            ("required_layout", " ", "required_layout"),
            ("accessibility_needs", "", "accessibility_needs"),
            ("required_facilities", "chairs", "required_facilities"),
            ("registration_required", "yes", "registration_required"),
            ("intended_capacity", 0, "intended_capacity"),
        ],
    )
    def test_mandatory_fields_are_validated_without_saving(
        self, app, coordinator, make_event, field, value, error_field
    ):
        with app.app_context():
            from app.models.user import User
            event_id = make_event(
                organiser_id=1, status="planning", coordinator_id=coordinator, name="Original"
            )
            event = Event.query.get(event_id)

            with pytest.raises(EventValidationError) as exc_info:
                update_event_fields(
                    event, User.query.get(coordinator), {field: value},
                    offline_review_confirmed=True,
                )

            assert error_field in exc_info.value.field_errors
            assert Event.query.get(event_id).name == "Original"

    def test_capacity_below_attendance_rejected(self, app, coordinator, make_event):
        with app.app_context():
            from app.models.user import User
            event_id = make_event(organiser_id=1, status="planning", coordinator_id=coordinator,
                                   expected_attendance=50, capacity_needed=60)
            event = Event.query.get(event_id)
            user = User.query.get(coordinator)

            with pytest.raises(EventValidationError) as exc_info:
                update_event_fields(event, user, {"capacity_needed": 30}, offline_review_confirmed=True)

            assert "capacity_needed" in exc_info.value.field_errors

    def test_unknown_field_rejected(self, app, coordinator, make_event):
        with app.app_context():
            from app.models.user import User
            event_id = make_event(organiser_id=1, status="planning", coordinator_id=coordinator)
            event = Event.query.get(event_id)
            user = User.query.get(coordinator)

            with pytest.raises(EventValidationError) as exc_info:
                update_event_fields(event, user, {"status": "confirmed"})

            assert "status" in exc_info.value.field_errors

# Equipment deletion
    def test_equipment_requirement_removed_when_omitted_from_payload(self, app, coordinator, make_event):
        with app.app_context():
            from app.models.user import User
            event_id = make_event(organiser_id=1, status="planning", coordinator_id=coordinator)
            keep = EventEquipmentRequirement(event_id=event_id, equipment_type="Projector", quantity=1)
            remove = EventEquipmentRequirement(event_id=event_id, equipment_type="Speaker", quantity=2)
            db.session.add_all([keep, remove])
            db.session.commit()
            keep_id, remove_id = keep.id, remove.id

            update_event_fields(
                Event.query.get(event_id), User.query.get(coordinator),
                {"equipment_requirements": [{"id": keep_id, "type": "Projector", "quantity": 1}]},
                offline_review_confirmed=True,
            )

            remaining = EventEquipmentRequirement.query.filter_by(event_id=event_id).all()
            assert [r.id for r in remaining] == [keep_id]
            assert EventEquipmentRequirement.query.get(remove_id) is None


# Atomicity of mixed ordinary + significant edits
    def test_mixed_ordinary_and_significant_edit_blocked_atomically(self, app, coordinator, make_event):
        with app.app_context():
            from app.models.user import User
            event_id = make_event(organiser_id=1, status="planning", coordinator_id=coordinator, name="Original")
            event = Event.query.get(event_id)
            user = User.query.get(coordinator)

            with pytest.raises(OfflineReviewNotConfirmedError):
                update_event_fields(event, user, {"name": "Updated Name", "expected_attendance": 80})

            refreshed = Event.query.get(event_id)
            assert refreshed.name == "Original"
            assert refreshed.expected_attendance != 80

# Boundary: capacity exactly equals attendance
    def test_capacity_equal_to_attendance_is_valid_boundary(self, app, coordinator, make_event):
        with app.app_context():
            from app.models.user import User
            event_id = make_event(organiser_id=1, status="planning", coordinator_id=coordinator,
                                   expected_attendance=50, capacity_needed=60)
            event = Event.query.get(event_id)
            user = User.query.get(coordinator)

            update_event_fields(event, user, {"capacity_needed": 50}, offline_review_confirmed=True)

            assert Event.query.get(event_id).capacity_needed == 50

# Audit log correctly marks ordinary-only edits as not significant:
    def test_ordinary_only_edit_logged_as_not_significant(self, app, coordinator, make_event):
        with app.app_context():
            from app.models.user import User
            event_id = make_event(organiser_id=1, status="planning", coordinator_id=coordinator)
            event = Event.query.get(event_id)
            user = User.query.get(coordinator)

            update_event_fields(event, user, {"purpose": "Updated purpose"})

            log = Event.query.get(event_id).field_edit_logs[-1]
            assert log.was_significant is False


    def test_required_facilities_can_be_empty_list(self, app, coordinator, make_event):
        with app.app_context():
            from app.models.user import User
            event_id = make_event(organiser_id=1, status="planning", coordinator_id=coordinator)
            event = Event.query.get(event_id)
            user = User.query.get(coordinator)

            update_event_fields(event, user, {"required_facilities": []}, offline_review_confirmed=True)

            refreshed = Event.query.get(event_id)
            assert refreshed.required_facilities == []           
# test venue preparation service


def _make_preparation_booking(event_id, staff_id, status=BOOKING_APPROVED):
    venue = Venue(name="Hall A", capacity=100, created_by=staff_id)
    db.session.add(venue)
    db.session.commit()
    booking = VenueBooking(
        event_id=event_id, venue_id=venue.id, requested_by=1, status=status,
        start_datetime=datetime(2026, 12, 1, 9), end_datetime=datetime(2026, 12, 1, 17),
    )
    db.session.add(booking)
    db.session.commit()
    return booking


class TestVenuePreparation:
    def test_non_object_changes_rejected(self, app, make_user, make_event):
        with app.app_context():
            from app.models.user import User

            staff_id = make_user("staff-non-object@test.com", ["venue_staff"])
            event_id = make_event(organiser_id=1, status="planning")
            booking = _make_preparation_booking(event_id, staff_id)
            staff = User.query.get(staff_id)

            with pytest.raises(PreparationUpdateError, match="must be an object"):
                update_venue_preparation(booking, staff, [])

    def test_empty_changes_rejected(self, app, make_user, make_event):
        with app.app_context():
            from app.models.user import User

            staff_id = make_user("staff-empty@test.com", ["venue_staff"])
            event_id = make_event(organiser_id=1, status="planning")
            booking = _make_preparation_booking(event_id, staff_id)
            staff = User.query.get(staff_id)

            with pytest.raises(PreparationUpdateError, match="At least one"):
                update_venue_preparation(booking, staff, {})

    def test_non_text_venue_notes_rejected_without_mutation(self, app, make_user, make_event):
        with app.app_context():
            from app.models.user import User

            staff_id = make_user("staff-invalid-notes@test.com", ["venue_staff"])
            event_id = make_event(organiser_id=1, status="planning")
            booking = _make_preparation_booking(event_id, staff_id)
            staff = User.query.get(staff_id)

            with pytest.raises(PreparationUpdateError, match="Venue notes must be text"):
                update_venue_preparation(booking, staff, {"venue_notes": 123})

            assert VenueBooking.query.get(booking.id).venue_notes is None

    def test_managing_venue_staff_updates_preparation(self, app, make_user, make_event):
        with app.app_context():
            from app.models.user import User
            staff_id = make_user("staff@test.com", ["venue_staff"])
            event_id = make_event(organiser_id=1, status="planning")
            booking = _make_preparation_booking(event_id, staff_id)
            staff = User.query.get(staff_id)

            update_venue_preparation(booking, staff, {"setup_status": "in_progress", "venue_notes": "Chairs delivered"})

            refreshed = VenueBooking.query.get(booking.id)
            assert refreshed.setup_status == "in_progress"
            assert refreshed.venue_notes == "Chairs delivered"
            assert refreshed.updated_at is not None

    def test_non_managing_venue_staff_rejected(self, app, make_user, make_event):
        """AC2: no booking at a venue I manage -> denied."""
        with app.app_context():
            from app.models.user import User
            owner_id = make_user("owner@test.com", ["venue_staff"])
            other_id = make_user("other@test.com", ["venue_staff"])
            event_id = make_event(organiser_id=1, status="planning")
            booking = _make_preparation_booking(event_id, owner_id)
            other = User.query.get(other_id)

            with pytest.raises(PermissionError):
                update_venue_preparation(booking, other, {"setup_status": "done"})

    def test_non_venue_staff_role_rejected(self, app, coordinator, make_event):
        with app.app_context():
            from app.models.user import User
            event_id = make_event(organiser_id=1, status="planning")
            booking = _make_preparation_booking(event_id, coordinator)  # coordinator "owns" venue for this test only
            coord = User.query.get(coordinator)

            with pytest.raises(PermissionError):
                update_venue_preparation(booking, coord, {"setup_status": "done"})

    def test_confirmed_event_booking_still_updatable(self, app, make_user, make_event):
        """AC3: preparation progress is gated by booking status, not event status."""
        with app.app_context():
            from app.models.user import User
            staff_id = make_user("staff2@test.com", ["venue_staff"])
            event_id = make_event(organiser_id=1, status="confirmed")
            booking = _make_preparation_booking(event_id, staff_id)
            staff = User.query.get(staff_id)

            update_venue_preparation(booking, staff, {"setup_status": "done"})

            assert VenueBooking.query.get(booking.id).setup_status == "done"

    def test_non_active_booking_rejected(self, app, make_user, make_event):
        with app.app_context():
            from app.models.user import User
            staff_id = make_user("staff3@test.com", ["venue_staff"])
            event_id = make_event(organiser_id=1, status="planning")
            booking = _make_preparation_booking(event_id, staff_id, status="pending")
            staff = User.query.get(staff_id)

            with pytest.raises(PreparationUpdateError):
                update_venue_preparation(booking, staff, {"setup_status": "done"})

    def test_unknown_field_rejected(self, app, make_user, make_event):
        with app.app_context():
            from app.models.user import User
            staff_id = make_user("staff4@test.com", ["venue_staff"])
            event_id = make_event(organiser_id=1, status="planning")
            booking = _make_preparation_booking(event_id, staff_id)
            staff = User.query.get(staff_id)

            with pytest.raises(PreparationUpdateError):
                update_venue_preparation(booking, staff, {"status": "approved"})

    def test_invalid_setup_status_rejected_without_mutation(self, app, make_user, make_event):
        with app.app_context():
            from app.models.user import User
            staff_id = make_user("staff-invalid-status@test.com", ["venue_staff"])
            event_id = make_event(organiser_id=1, status="planning")
            booking = _make_preparation_booking(event_id, staff_id)
            staff = User.query.get(staff_id)

            with pytest.raises(PreparationUpdateError):
                update_venue_preparation(booking, staff, {"setup_status": "complete"})

            assert VenueBooking.query.get(booking.id).setup_status == "pending"


def test_adding_new_equipment_requirement_does_not_overwrite_existing(app, coordinator, make_event):
    with app.app_context():
        from app.models.user import User
        event_id = make_event(organiser_id=1, status="planning", coordinator_id=coordinator)
        existing = EventEquipmentRequirement(event_id=event_id, equipment_type="Projector", quantity=1)
        db.session.add(existing)
        db.session.commit()

        update_event_fields(
            Event.query.get(event_id), User.query.get(coordinator),
            {"equipment_requirements": [
                {"id": existing.id, "type": "Projector", "quantity": 1},
                {"type": "Speaker", "quantity": 2},
            ]},
            offline_review_confirmed=True,
        )

        items = {i.equipment_type: i.quantity for i in EventEquipmentRequirement.query.filter_by(event_id=event_id)}
        assert items == {"Projector": 1, "Speaker": 2}
class TestSafetyCheckEdits:
    def test_significant_edit_during_safety_check_reverts_once_with_the_significant_reason(
        self, app, coordinator, make_event
    ):
        with app.app_context():
            from app.models.user import User
            event_id = make_event(organiser_id=1, status="safety_check", coordinator_id=coordinator,
                                  expected_attendance=50, capacity_needed=60)
            event = Event.query.get(event_id)

            update_event_fields(
                event, User.query.get(coordinator), {"expected_attendance": 55},
                offline_review_confirmed=True,
            )

            assert Event.query.get(event_id).status == "planning"
            rows = EventStatusHistory.query.filter_by(event_id=event_id, new_status="planning").all()
            assert len(rows) == 1
            assert rows[0].reason.startswith("Significant change to")

    def test_accessibility_needs_edit_is_significant(self, app, coordinator, make_event):
        with app.app_context():
            from app.models.user import User
            event_id = make_event(organiser_id=1, status="planning", coordinator_id=coordinator)
            event = Event.query.get(event_id)

            with pytest.raises(OfflineReviewNotConfirmedError):
                update_event_fields(event, User.query.get(coordinator), {"accessibility_needs": "Hearing loop"})

            update_event_fields(
                event, User.query.get(coordinator), {"accessibility_needs": "Hearing loop"},
                offline_review_confirmed=True,
            )
            assert event.field_edit_logs[-1].was_significant is True

    def test_failed_edit_during_safety_check_changes_nothing(self, app, coordinator, make_event):
        with app.app_context():
            from app.models.user import User
            event_id = make_event(organiser_id=1, status="safety_check", coordinator_id=coordinator, name="Original")
            event = Event.query.get(event_id)

            with pytest.raises(EventValidationError):
                update_event_fields(event, User.query.get(coordinator), {"name": "   "})

            refreshed = Event.query.get(event_id)
            assert refreshed.status == "safety_check"
            assert refreshed.name == "Original"
            assert EventStatusHistory.query.filter_by(event_id=event_id).count() == 0

    def test_empty_edit_during_safety_check_does_not_revert(self, app, coordinator, make_event):
        with app.app_context():
            from app.models.user import User
            event_id = make_event(organiser_id=1, status="safety_check", coordinator_id=coordinator)
            event = Event.query.get(event_id)

            update_event_fields(event, User.query.get(coordinator), {})

            assert Event.query.get(event_id).status == "safety_check"

    def test_revert_from_safety_check_discards_the_in_progress_assessment(
        self, app, coordinator, make_user, make_event
    ):
        with app.app_context():
            from app.models.user import User
            officer_id = make_user("assess-revert@test.com", ["safety_officer"])
            event_id = make_event(organiser_id=1, status="safety_check", coordinator_id=coordinator)
            db.session.add(EventSafetyAssessment(
                event_id=event_id, safety_officer_id=officer_id,
                factors={"emergency_access": {"outcome": "concern", "notes": None}},
            ))
            db.session.commit()

            update_event_fields(Event.query.get(event_id), User.query.get(coordinator), {"purpose": "New purpose"})

            assert EventSafetyAssessment.query.filter_by(event_id=event_id).count() == 0

    def test_organiser_is_told_when_a_safety_check_edit_returns_the_event_to_planning(
        self, app, organiser, coordinator, make_event
    ):
        with app.app_context():
            from app.models.user import User
            event_id = make_event(organiser, status="safety_check", coordinator_id=coordinator)

            update_event_fields(Event.query.get(event_id), User.query.get(coordinator), {"purpose": "New purpose"})

            notes = [n for n in Notification.query.filter_by(recipient_id=organiser, event_id=event_id)
                     if n.data.get("kind") == "returned_to_planning"]
            assert len(notes) == 1
            assert "Edited during safety check" in notes[0].message
