from datetime import datetime

from app.events.services import update as update_service
from app.models.user import User
from app.extensions import db
from app.models.event import Event, EventEquipmentRequirement
from app.models.venue import Venue, VenueBooking, BOOKING_APPROVED


def _make_booking(event_id, staff_id, status=BOOKING_APPROVED):
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


class TestVenuePreparationRoute:
    def test_managing_staff_updates_preparation_returns_200(
        self, client, app, coordinator, make_user, make_event, auth_header
    ):
        with app.app_context():
            staff_id = make_user("vstaff@test.com", ["venue_staff"])
            event_id = make_event(organiser_id=coordinator, status="planning", coordinator_id=coordinator)
            booking = _make_booking(event_id, staff_id)
            booking_id = booking.id
            event_id_for_view = event_id
        headers = auth_header("vstaff@test.com")

        res = client.put(
            f"/api/venues/bookings/{booking_id}/preparation",
            json={"setup_status": "in_progress"},
            headers=headers,
        )

        assert res.status_code == 200
        assert res.get_json()["setupStatus"] == "in_progress"
        assert res.get_json()["updatedAt"] is not None

    # Fetch the event again to verify the updated booking is serialized.
        event_response = client.get(
            f"/api/events/{event_id_for_view}",
            headers=auth_header("coordinator@test.com"),
        )
        assert event_response.status_code == 200

        bookings = event_response.get_json()["venueBookings"]
        booking_data = next(
            b for b in bookings if b["id"] == booking_id
        )

        assert booking_data["setupStatus"] == "in_progress"

    def test_non_managing_staff_returns_403(self, client, app, make_user, make_event, auth_header):
        with app.app_context():
            owner_id = make_user("owner2@test.com", ["venue_staff"])
            make_user("other2@test.com", ["venue_staff"])
            event_id = make_event(organiser_id=1, status="planning")
            booking = _make_booking(event_id, owner_id)
            booking_id = booking.id
            original_setup_status = booking.setup_status

        headers = auth_header("other2@test.com")

        res = client.put(
            f"/api/venues/bookings/{booking_id}/preparation",
            json={"setup_status": "done"},
            headers=headers,
        )

        assert res.status_code == 403

        # Database check to confirm the booking's preparation status did not change.
        with app.app_context():
            booking = db.session.get(VenueBooking, booking_id)
            assert booking.setup_status == original_setup_status

    def test_non_venue_staff_role_rejected_by_decorator(self, client, app, coordinator, make_event, auth_header):
        with app.app_context():
            event_id = make_event(organiser_id=1, status="planning")
            booking = _make_booking(event_id, coordinator)
            booking_id = booking.id
            original_setup_status = booking.setup_status

        headers = auth_header("coordinator@test.com")

        res = client.put(
            f"/api/venues/bookings/{booking_id}/preparation",
            json={"setup_status": "done"},
            headers=headers,
        )

        assert res.status_code == 403
        
        with app.app_context():
            booking = db.session.get(VenueBooking, booking_id)
            assert booking.setup_status == original_setup_status

    def test_inactive_booking_returns_400(self, client, app, make_user, make_event, auth_header):
        with app.app_context():
            staff_id = make_user("vstaff3@test.com", ["venue_staff"])
            event_id = make_event(organiser_id=1, status="planning")
            booking = _make_booking(event_id, staff_id, status="pending")
            booking_id = booking.id
            original_setup_status = booking.setup_status

        headers = auth_header("vstaff3@test.com")

        res = client.put(
            f"/api/venues/bookings/{booking_id}/preparation",
            json={"setup_status": "done"},
            headers=headers,
        )

        assert res.status_code == 400
        
        with app.app_context():
            booking = db.session.get(VenueBooking, booking_id)
            assert booking.status == "pending"
            assert booking.setup_status == original_setup_status


    def test_nonexistent_booking_returns_404(self, client, make_user, auth_header):
        make_user("vstaff4@test.com", ["venue_staff"])
        headers = auth_header("vstaff4@test.com")

        res = client.put(
            "/api/venues/bookings/999999/preparation",
            json={"setup_status": "done"},
            headers=headers,
        )

        assert res.status_code == 404


class TestEquipmentPreparationRoute:
    def test_technical_support_can_update_confirmed_event_equipment(self, client, app, make_user, make_event, auth_header):
        with app.app_context():
            make_user("tss-prep@test.com", ["technical_support_staff"])
            event_id = make_event(organiser_id=1, status="confirmed")
            requirement = EventEquipmentRequirement(
                event_id=event_id, equipment_type="Projector", quantity=1, status="confirmed"
            )
            db.session.add(requirement)
            db.session.commit()
            requirement_id = requirement.id

        response = client.put(
            f"/api/equipment/requirements/{requirement_id}/preparation",
            json={"testing_status": "done"},
            headers=auth_header("tss-prep@test.com"),
        )

        assert response.status_code == 200
        assert response.get_json()["testingStatus"] == "done"
        assert response.get_json()["updatedAt"] is not None

        event_response = client.get(
            f"/api/events/{event_id}",
            headers=auth_header("tss-prep@test.com"),
        )
        assert event_response.status_code == 200

        event_data = event_response.get_json()
        assert event_data["status"] == "confirmed"

        requirements = event_data["equipmentRequirements"]
        requirement_data = next(
            r for r in requirements if r["id"] == requirement_id
        )

        assert requirement_data["testingStatus"] == "done"

    def test_non_technical_staff_cannot_update_equipment_preparation(
        self, client, app, coordinator, make_event, auth_header
    ):
        with app.app_context():
            event_id = make_event(organiser_id=1, status="planning")
            requirement = EventEquipmentRequirement(
                event_id=event_id, equipment_type="Projector", 
                quantity=1
            )
            db.session.add(requirement)
            db.session.commit()
            requirement_id = requirement.id
            original_testing_status = requirement.testing_status


        response = client.put(
            f"/api/equipment/requirements/{requirement_id}/preparation",
            json={"testing_status": "done"},
            headers=auth_header("coordinator@test.com"),
        )

        assert response.status_code == 403
        
        with app.app_context():
            requirement = db.session.get(
                EventEquipmentRequirement, requirement_id
            )
            assert requirement.testing_status == original_testing_status



class TestEventUpdateRoute:
    def test_coordinator_updates_ordinary_field_returns_200(self, client, app, coordinator, make_event, auth_header):
        with app.app_context():
            event_id = make_event(organiser_id=1, status="planning", coordinator_id=coordinator)

        res = client.put(
            f"/api/events/{event_id}/update",
            json={"fields": {"purpose": "Updated purpose"}, "offlineReviewConfirmed": False},
            headers=auth_header("coordinator@test.com"),
        )

        assert res.status_code == 200
        assert res.get_json()["purpose"] == "Updated purpose"

    def test_significant_field_without_confirmation_returns_400(self, client, app, coordinator, make_event, auth_header):
        with app.app_context():
            event_id = make_event(organiser_id=1, status="planning", coordinator_id=coordinator)

        res = client.put(
            f"/api/events/{event_id}/update",
            json={"fields": {"expected_attendance": 80}, "offlineReviewConfirmed": False},
            headers=auth_header("coordinator@test.com"),
        )

        assert res.status_code == 400  # adjust if your error handler maps OfflineReviewNotConfirmedError differently
        with app.app_context():
            assert Event.query.get(event_id).expected_attendance != 80

    def test_significant_field_with_confirmation_updates_and_flags_booking(
        self, client, app, coordinator, make_event, auth_header
    ):
        with app.app_context():
            event_id = make_event(organiser_id=1, status="planning", coordinator_id=coordinator,
                                   expected_attendance=50, capacity_needed=60)
            booking = _make_booking(event_id, 1)
            booking_id = booking.id

        res = client.put(
            f"/api/events/{event_id}/update",
            json={"fields": {"expected_attendance": 55}, "offlineReviewConfirmed": True},
            headers=auth_header("coordinator@test.com"),
        )

        assert res.status_code == 200
        assert res.get_json()["expectedAttendance"] == 55
        with app.app_context():
            assert VenueBooking.query.get(booking_id).needs_reconsideration is True

    def test_non_assigned_coordinator_returns_403(self, client, app, coordinator, make_user, make_event, auth_header):
        with app.app_context():
            make_user("other-coord@test.com", ["event_coordinator"])
            event_id = make_event(organiser_id=1, status="planning", coordinator_id=coordinator)

        res = client.put(
            f"/api/events/{event_id}/update",
            json={"fields": {"purpose": "Hijacked"}, "offlineReviewConfirmed": False},
            headers=auth_header("other-coord@test.com"),
        )

        assert res.status_code == 403

    def test_organiser_cannot_call_update_route_directly(self, client, app, make_user, make_event, auth_header):
        with app.app_context():
            organiser_id = make_user("org-direct@test.com", ["event_organiser"])
            event_id = make_event(organiser_id=organiser_id, status="planning")
            original_purpose = Event.query.get(event_id).purpose


        res = client.put(
            f"/api/events/{event_id}/update",
            json={"fields": {"purpose": "Hijacked"}, "offlineReviewConfirmed": False},
            headers=auth_header("org-direct@test.com"),
        )

        assert res.status_code == 403
        
        with app.app_context():
            event = db.session.get(Event, event_id)
            assert event.purpose == original_purpose


    def test_confirmed_event_returns_locked_status(self, client, app, coordinator, make_event, auth_header):
        with app.app_context():
            event_id = make_event(organiser_id=1, status="confirmed", coordinator_id=coordinator)

        res = client.put(
            f"/api/events/{event_id}/update",
            json={"fields": {"purpose": "Too late"}, "offlineReviewConfirmed": False},
            headers=auth_header("coordinator@test.com"),
        )

        assert res.status_code == 423  # adjust to whatever your EventLockedError handler actually returns

    def test_non_editable_status_rejected(self, client, app, coordinator, make_event, auth_header):
        with app.app_context():
            event_id = make_event(organiser_id=1, status="draft", coordinator_id=coordinator)

        res = client.put(
            f"/api/events/{event_id}/update",
            json={"fields": {"purpose": "Nope"}, "offlineReviewConfirmed": False},
            headers=auth_header("coordinator@test.com"),
        )

        assert res.status_code in (400, 409)  # adjust to match your EventNotEditableStatusError handler



    def test_safety_check_status_is_editable(self, client, app, coordinator, make_event, auth_header):
        """Per Clarification Session 3: coordinator can edit before the final confirmed status, so safety check is editable."""
        with app.app_context():
            event_id = make_event(organiser_id=1, status="safety_check", coordinator_id=coordinator)

        res = client.put(
            f"/api/events/{event_id}/update",
            json={"fields": {"purpose": "Updated during safety check"}, "offlineReviewConfirmed": False},
            headers=auth_header("coordinator@test.com"),
        )

        assert res.status_code == 200

    def test_validation_error_returns_400_with_field_errors(self, client, app, coordinator, make_event, auth_header):
        with app.app_context():
            event_id = make_event(organiser_id=1, status="planning", coordinator_id=coordinator, name="Original")

        res = client.put(
            f"/api/events/{event_id}/update",
            json={"fields": {"name": "   "}, "offlineReviewConfirmed": False},
            headers=auth_header("coordinator@test.com"),
        )

        assert res.status_code == 400
        assert "name" in res.get_json().get("fieldErrors", res.get_json().get("errors", {}))
        with app.app_context():
            assert Event.query.get(event_id).name == "Original"

    def test_required_facilities_empty_list_accepted(self, client, app, coordinator, make_event, auth_header):
        with app.app_context():
            event_id = make_event(organiser_id=1, status="planning", coordinator_id=coordinator)

        res = client.put(
            f"/api/events/{event_id}/update",
            json={"fields": {"required_facilities": []}, "offlineReviewConfirmed": True},
            headers=auth_header("coordinator@test.com"),
        )

        assert res.status_code == 200
        assert res.get_json()["venueRequirements"]["requiredFacilities"] == []

    def test_removing_equipment_requirement_via_api(self, client, app, coordinator, make_event, auth_header):
        with app.app_context():
            event_id = make_event(organiser_id=1, status="planning", coordinator_id=coordinator)
            keep = EventEquipmentRequirement(event_id=event_id, equipment_type="Projector", quantity=1)
            remove = EventEquipmentRequirement(event_id=event_id, equipment_type="Speaker", quantity=2)
            db.session.add_all([keep, remove])
            db.session.commit()
            keep_id = keep.id

        res = client.put(
            f"/api/events/{event_id}/update",
            json={
                "fields": {"equipment_requirements": [{"id": keep_id, "type": "Projector", "quantity": 1}]},
                "offlineReviewConfirmed": True,
            },
            headers=auth_header("coordinator@test.com"),
        )

        assert res.status_code == 200
        items = res.get_json()["equipmentRequirements"]
        assert len(items) == 1
        assert items[0]["id"] == keep_id

    def test_edit_history_appears_on_subsequent_get(self, client, app, coordinator, make_event, auth_header):
        with app.app_context():
            event_id = make_event(organiser_id=1, status="planning", coordinator_id=coordinator)

        update_res=client.put(
            f"/api/events/{event_id}/update",
            json={"fields": {"purpose": "Updated purpose"}, "offlineReviewConfirmed": False},
            headers=auth_header("coordinator@test.com"),
        )

        res = client.get(f"/api/events/{event_id}", headers=auth_header("coordinator@test.com"))
        logs = res.get_json().get("fieldEditLogs")
        assert logs is not None, "fieldEditLogs missing from GET /events/<id> — see item 4, implement the serializer first"
        assert len(logs) == 1
        assert logs[0]["wasSignificant"] is False
        assert logs[0]["newValues"]["purpose"] == "Updated purpose"
        assert update_res.status_code == 200


class TestEventFieldEditLogsVisibility:
    def test_organiser_sees_field_edit_logs(self, client, app, organiser, coordinator, make_event, auth_header):
        with app.app_context():
            event_id = make_event(organiser_id=organiser, status="planning", coordinator_id=coordinator)
            event = Event.query.get(event_id)
            update_service.update_event_fields(event, User.query.get(coordinator), {"purpose": "Updated"})

        res = client.get(f"/api/events/{event_id}", headers=auth_header("organiser@test.com"))

        assert res.status_code == 200
        logs = res.get_json()["fieldEditLogs"]
        assert len(logs) == 1
        assert logs[0]["newValues"]["purpose"] == "Updated"
        assert logs[0]["changedByName"] is not None

