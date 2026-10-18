from datetime import datetime

import pytest
from app.extensions import db
from app.models.event import EventEquipmentRequirement
from app.models.event import Event
from app.models.venue import Venue, VenueBooking, BOOKING_APPROVED, BOOKING_HELD
from app.events.services.update import (
    update_event_fields, EventLockedError, EventNotEditableStatusError,
    OfflineReviewNotConfirmedError, EventValidationError,
)
from app.venues.services.preparation import (
    update_venue_preparation,
    PreparationUpdateError,
)
from app.equipment.services.preparation import (
    update_equipment_preparation,
    EquipmentPreparationError,
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

    def test_equipment_requirement_flagged_on_significant_change(self, app, coordinator, make_event):
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

            assert EventEquipmentRequirement.query.get(req.id).needs_recheck is True

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

    @pytest.mark.parametrize("status", ["draft", "submitted", "safety_check", "completed", "cancelled", "rejected"])
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
            ("equipment_requirements", [], "equipment_requirements"),
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


# test equipment preparation service

def _make_requirement(event_id, status="requested"):
    req = EventEquipmentRequirement(event_id=event_id, equipment_type="Projector", quantity=2, status=status)
    db.session.add(req)
    db.session.commit()
    return req


class TestEquipmentPreparation:
    def test_tss_updates_preparation(self, app, make_user, make_event):
        with app.app_context():
            from app.models.user import User
            tss_id = make_user("tss@test.com", ["technical_support_staff"])
            event_id = make_event(organiser_id=1, status="planning")
            req = _make_requirement(event_id)
            tss = User.query.get(tss_id)

            update_equipment_preparation(req, tss, {"testing_status": "done", "installation_status": "in_progress"})

            refreshed = EventEquipmentRequirement.query.get(req.id)
            assert refreshed.testing_status == "done"
            assert refreshed.installation_status == "in_progress"
            assert refreshed.updated_at is not None

    def test_non_tss_rejected(self, app, coordinator, make_event):
        with app.app_context():
            from app.models.user import User
            event_id = make_event(organiser_id=1, status="planning")
            req = _make_requirement(event_id)
            coord = User.query.get(coordinator)

            with pytest.raises(PermissionError):
                update_equipment_preparation(req, coord, {"testing_status": "done"})

    def test_cannot_touch_quantity_or_type(self, app, make_user, make_event):
        """AC2: TSS can't change venue details, core event fields, or
        quantity/type of equipment requested by the Coordinator."""
        with app.app_context():
            from app.models.user import User
            tss_id = make_user("tss2@test.com", ["technical_support_staff"])
            event_id = make_event(organiser_id=1, status="planning")
            req = _make_requirement(event_id)
            tss = User.query.get(tss_id)

            with pytest.raises(EquipmentPreparationError):
                update_equipment_preparation(req, tss, {"quantity": 10})

            assert EventEquipmentRequirement.query.get(req.id).quantity == 2

    def test_confirmed_equipment_reserved_still_updatable(self, app, make_user, make_event):
        """AC3: updating preparation doesn't revert event status or touch
        core info -- it's gated by the requirement's own status."""
        with app.app_context():
            from app.models.user import User
            from app.models.event import Event
            tss_id = make_user("tss3@test.com", ["technical_support_staff"])
            event_id = make_event(organiser_id=1, status="confirmed")
            req = _make_requirement(event_id, status="confirmed")
            tss = User.query.get(tss_id)

            update_equipment_preparation(req, tss, {"installation_status": "done"})

            assert EventEquipmentRequirement.query.get(req.id).installation_status == "done"
            assert Event.query.get(event_id).status == "confirmed"  # unchanged

    def test_unavailable_requirement_rejected(self, app, make_user, make_event):
        with app.app_context():
            from app.models.user import User
            tss_id = make_user("tss4@test.com", ["technical_support_staff"])
            event_id = make_event(organiser_id=1, status="planning")
            req = _make_requirement(event_id, status="unavailable")
            tss = User.query.get(tss_id)

            with pytest.raises(EquipmentPreparationError):
                update_equipment_preparation(req, tss, {"testing_status": "done"})

