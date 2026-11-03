from datetime import datetime

import pytest

from app.events import routes as event_routes
from app.events.services import update as update_service
from app.models.user import User
from app.extensions import db
from app.models.equipment import EquipmentItem, EquipmentReservation
from app.models.event import Event, EventEquipmentRequirement, EventFieldEditLog
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

    def test_date_only_edit_preserves_equipment_and_reservation_data(
        self, client, app, coordinator, make_event, auth_header
    ):
        with app.app_context():
            event_id = make_event(
                organiser_id=1,
                status="planning",
                coordinator_id=coordinator,
                proposed_date=datetime(2026, 12, 1).date(),
                proposed_time=datetime(2026, 12, 1, 9).time(),
            )
            item = EquipmentItem(name="Projector", total_quantity=5)
            requirement = EventEquipmentRequirement(
                event_id=event_id,
                equipment_type="Projector",
                quantity=2,
                technical_notes="Ceiling mount",
                status="confirmed",
            )
            db.session.add_all([item, requirement])
            db.session.commit()
            reservation = EquipmentReservation(
                event_id=event_id,
                equipment_requirement_id=requirement.id,
                equipment_item_id=item.id,
                quantity=2,
                start_datetime=datetime(2026, 12, 1, 10),
                end_datetime=datetime(2026, 12, 1, 12),
                status="reserved",
            )
            db.session.add(reservation)
            db.session.commit()
            requirement_id = requirement.id
            item_id = item.id
            reservation_id = reservation.id

        response = client.put(
            f"/api/events/{event_id}/update",
            json={
                "fields": {"proposed_date": "2026-12-02"},
                "offlineReviewConfirmed": True,
            },
            headers=auth_header("coordinator@test.com"),
        )

        assert response.status_code == 200
        with app.app_context():
            requirement = db.session.get(EventEquipmentRequirement, requirement_id)
            reservation = db.session.get(EquipmentReservation, reservation_id)
            edit_log = EventFieldEditLog.query.filter_by(event_id=event_id).one()
            assert (
                requirement.equipment_type,
                requirement.quantity,
                requirement.technical_notes,
                requirement.status,
            ) == ("Projector", 2, "Ceiling mount", "confirmed")
            # Date edits retain the existing recheck behavior without changing the requirement itself.
            assert requirement.needs_recheck is True
            assert (
                reservation.equipment_requirement_id,
                reservation.equipment_item_id,
                reservation.quantity,
                reservation.status,
                reservation.start_datetime,
                reservation.end_datetime,
            ) == (
                requirement_id,
                item_id,
                2,
                "reserved",
                datetime(2026, 12, 1, 10),
                datetime(2026, 12, 1, 12),
            )
            assert edit_log.fields_changed == ["proposed_date"]
            assert "equipment_requirements" not in edit_log.old_values
            assert "equipment_requirements" not in edit_log.new_values

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
        assert res.get_json()["status"] == "planning"

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



class TestEventDraftRoutes:
    def test_organiser_can_list_own_drafts(
        self, client, app, organiser, make_event, auth_header
    ):
        with app.app_context():
            draft_id = make_event(
                organiser_id=organiser,
                status="draft",
                name="My Saved Draft",
            )

        response = client.get(
            "/api/events/drafts",
            headers=auth_header("organiser@test.com"),
        )

        assert response.status_code == 200

        drafts = response.get_json()
        assert isinstance(drafts, list)
        assert len(drafts) == 1
        assert drafts[0]["id"] == draft_id
        assert drafts[0]["name"] == "My Saved Draft"

    def test_organiser_with_no_drafts_receives_empty_list(
        self, client, app, organiser, auth_header
    ):
        response = client.get(
            "/api/events/drafts",
            headers=auth_header("organiser@test.com"),
        )

        assert response.status_code == 200
        assert response.get_json() == []

    def test_organiser_cannot_see_another_organisers_drafts(
        self, client, app, organiser, make_user, make_event, auth_header
    ):
        with app.app_context():
            other_organiser_id = make_user(
                "other-organiser@test.com",
                ["event_organiser"],
            )

            make_event(
                organiser_id=other_organiser_id,
                status="draft",
                name="Someone Else's Draft",
            )

        response = client.get(
            "/api/events/drafts",
            headers=auth_header("organiser@test.com"),
        )

        assert response.status_code == 200
        assert response.get_json() == []


    def test_organiser_can_update_own_draft(
        self, client, app, organiser, make_event, auth_header
    ):
        with app.app_context():
            draft_id = make_event(
                organiser_id=organiser,
                status="draft",
                name="Original Draft",
            )

        response = client.put(
            f"/api/events/drafts/{draft_id}",
            json={"name": "Updated Draft"},
            headers=auth_header("organiser@test.com"),
        )

        assert response.status_code == 200
        assert response.get_json()["name"] == "Updated Draft"

    def test_update_nonexistent_draft_returns_404(
        self, client, organiser, auth_header
    ):
        response = client.put(
            "/api/events/drafts/999999",
            json={"name": "Updated Draft"},
            headers=auth_header("organiser@test.com"),
        )

        assert response.status_code == 404
        assert response.get_json()["error"] == "Draft not found"

    def test_organiser_cannot_update_another_organisers_draft(
        self, client, app, organiser, make_user, make_event, auth_header
    ):
        with app.app_context():
            other_organiser_id = make_user(
                "other-organiser@test.com",
                ["event_organiser"],
            )
            draft_id = make_event(
                organiser_id=other_organiser_id,
                status="draft",
                name="Another Organiser's Draft",
            )

        response = client.put(
            f"/api/events/drafts/{draft_id}",
            json={"name": "Hijacked Draft"},
            headers=auth_header("organiser@test.com"),
        )

        assert response.status_code == 404
        assert response.get_json()["error"] == "Draft not found"

        with app.app_context():
            draft = db.session.get(Event, draft_id)
            assert draft.name == "Another Organiser's Draft"

    def test_update_non_draft_event_returns_400(
        self, client, app, organiser, make_event, auth_header
    ):
        with app.app_context():
            event_id = make_event(
                organiser_id=organiser,
                status="planning",
                name="Event Already in Planning",
            )

        response = client.put(
            f"/api/events/drafts/{event_id}",
            json={"name": "Updated Event"},
            headers=auth_header("organiser@test.com"),
        )

        assert response.status_code == 400
        assert response.get_json()["error"] == (
            "Only a draft request can be edited this way"
        )

    def test_organiser_can_delete_own_draft(
        self, client, app, organiser, make_event, auth_header
    ):
        with app.app_context():
            draft_id = make_event(
                organiser_id=organiser,
                status="draft",
                name="Draft to Delete",
            )

        response = client.delete(
            f"/api/events/drafts/{draft_id}",
            headers=auth_header("organiser@test.com"),
        )

        assert response.status_code == 204

        with app.app_context():
            assert db.session.get(Event, draft_id) is None

    def test_delete_nonexistent_draft_returns_404(
        self, client, organiser, auth_header
    ):
        response = client.delete(
            "/api/events/drafts/999999",
            headers=auth_header("organiser@test.com"),
        )

        assert response.status_code == 404
        assert response.get_json()["error"] == "Draft not found"

    def test_organiser_cannot_delete_another_organisers_draft(
        self, client, app, organiser, make_user, make_event, auth_header
    ):
        with app.app_context():
            other_organiser_id = make_user(
                "other-organiser@test.com",
                ["event_organiser"],
            )
            draft_id = make_event(
                organiser_id=other_organiser_id,
                status="draft",
                name="Another Organiser's Draft",
            )

        response = client.delete(
            f"/api/events/drafts/{draft_id}",
            headers=auth_header("organiser@test.com"),
        )

        assert response.status_code == 404
        assert response.get_json()["error"] == "Draft not found"

        with app.app_context():
            draft = db.session.get(Event, draft_id)
            assert draft is not None
            assert draft.name == "Another Organiser's Draft"

    def test_delete_non_draft_event_returns_400(
        self, client, app, organiser, make_event, auth_header
    ):
        with app.app_context():
            event_id = make_event(
                organiser_id=organiser,
                status="planning",
                name="Event Already in Planning",
            )

        response = client.delete(
            f"/api/events/drafts/{event_id}",
            headers=auth_header("organiser@test.com"),
        )

        assert response.status_code == 400
        assert response.get_json()["error"] == (
            "Only a draft request can be deleted"
        )

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

    def test_edit_during_safety_check_returns_the_event_in_planning(self, client, app, coordinator, make_event, auth_header):
        with app.app_context():
            event_id = make_event(organiser_id=1, status="safety_check", coordinator_id=coordinator)

        res = client.put(
            f"/api/events/{event_id}/update",
            json={"fields": {"purpose": "Edited"}, "offlineReviewConfirmed": False},
            headers=auth_header("coordinator@test.com"),
        )

        assert res.status_code == 200
        assert res.get_json()["status"] == "planning"


class TestEventRouteErrorPaths:
    def test_submit_and_general_event_routes_cover_validation_and_permission_paths(
        self, client, app, organiser, coordinator, make_user, make_event, auth_header, monkeypatch
    ):
        org_headers = auth_header("organiser@test.com")

        def invalid_submit(event, user_id):
            raise ValueError("submission is incomplete")

        monkeypatch.setattr(event_routes.review, "submit_event", invalid_submit)
        response = client.post(
            "/api/events",
            headers=org_headers,
            json={"name": "Invalid submission", "submit": True},
        )
        assert response.status_code == 400
        assert response.get_json()["event"]["status"] == "draft"

        with app.app_context():
            event_id = make_event(organiser, status="draft")
            other_organiser = make_user("route-other-org@test.com", ["event_organiser"])
            other_event_id = make_event(other_organiser, status="draft")
        assert client.post("/api/events/999999/submit", headers=org_headers).status_code == 404
        assert client.post(f"/api/events/{other_event_id}/submit", headers=org_headers).status_code == 404

        def denied_submit(event, user_id):
            raise PermissionError("not allowed to submit")

        monkeypatch.setattr(event_routes.review, "submit_event", denied_submit)
        response = client.post(f"/api/events/{event_id}/submit", headers=org_headers)
        assert response.status_code == 400

        attendee_id = make_user("route-attendee@test.com", ["attendee"])
        response = client.get("/api/events", headers=auth_header("route-attendee@test.com"))
        assert response.status_code == 403
        assert attendee_id is not None

        coordinator_headers = auth_header("coordinator@test.com")
        assert client.put(
            "/api/events/999999/update",
            headers=coordinator_headers,
            json={"fields": {"purpose": "Missing event"}},
        ).status_code == 404

    def test_review_clarification_approval_rejection_and_resubmission_routes(
        self, client, app, organiser, coordinator, make_event, auth_header, monkeypatch
    ):
        org_headers = auth_header("organiser@test.com")
        coordinator_headers = auth_header("coordinator@test.com")
        with app.app_context():
            event_id = make_event(
                organiser,
                status="under_review",
                coordinator_id=coordinator,
                name="Review route coverage",
            )

        assert client.get("/api/events/999999/review", headers=coordinator_headers).status_code == 404
        review_response = client.get(
            f"/api/events/{event_id}/review", headers=coordinator_headers
        )
        assert review_response.status_code == 200
        assert review_response.get_json()["availableActions"] == [
            "request_clarification",
            "approve",
            "reject",
        ]

        assert client.post(
            "/api/events/999999/clarification",
            headers=coordinator_headers,
            json={"comments": "Please clarify"},
        ).status_code == 404
        monkeypatch.setattr(
            event_routes.review,
            "request_clarification",
            lambda *args: (_ for _ in ()).throw(ValueError("invalid clarification")),
        )
        assert client.post(
            f"/api/events/{event_id}/clarification",
            headers=coordinator_headers,
            json={"comments": "Please clarify"},
        ).status_code == 400
        monkeypatch.setattr(
            event_routes.review, "request_clarification", lambda event, user_id, comments: event
        )
        assert client.post(
            f"/api/events/{event_id}/clarification",
            headers=coordinator_headers,
            json={"comments": "Please clarify"},
        ).status_code == 200

        assert client.post(
            "/api/events/999999/clarification/response",
            headers=org_headers,
            json={"reviewId": 1},
        ).status_code == 404
        assert client.post(
            f"/api/events/{event_id}/clarification/response",
            headers=org_headers,
            json={"comments": "Response without a review ID"},
        ).status_code == 400
        monkeypatch.setattr(
            event_routes.review,
            "respond_to_clarification",
            lambda *args: (_ for _ in ()).throw(PermissionError("not allowed")),
        )
        assert client.post(
            f"/api/events/{event_id}/clarification/response",
            headers=org_headers,
            json={"reviewId": 1, "comments": "Response"},
        ).status_code == 400
        monkeypatch.setattr(
            event_routes.review,
            "respond_to_clarification",
            lambda event, user_id, review_id, data: event,
        )
        monkeypatch.setattr(event_routes.review, "get_clarification_thread", lambda event: [])
        assert client.post(
            f"/api/events/{event_id}/clarification/response",
            headers=org_headers,
            json={"reviewId": 1, "comments": "Response"},
        ).status_code == 200

        assert client.delete(
            "/api/events/999999/clarification/1", headers=coordinator_headers
        ).status_code == 404
        monkeypatch.setattr(
            event_routes.review,
            "delete_clarification_request",
            lambda *args: (_ for _ in ()).throw(ValueError("cannot delete")),
        )
        assert client.delete(
            f"/api/events/{event_id}/clarification/1", headers=coordinator_headers
        ).status_code == 400
        monkeypatch.setattr(
            event_routes.review, "delete_clarification_request", lambda event, user_id, review_id: event
        )
        assert client.delete(
            f"/api/events/{event_id}/clarification/1", headers=coordinator_headers
        ).status_code == 200

        assert client.post(
            "/api/events/999999/approve",
            headers=coordinator_headers,
            json={"confirmed": True},
        ).status_code == 404
        assert client.post(
            f"/api/events/{event_id}/approve", headers=coordinator_headers, json={}
        ).status_code == 409
        monkeypatch.setattr(
            event_routes.review,
            "approve_event",
            lambda *args: (_ for _ in ()).throw(ValueError("cannot approve")),
        )
        assert client.post(
            f"/api/events/{event_id}/approve",
            headers=coordinator_headers,
            json={"confirmed": True},
        ).status_code == 400

        monkeypatch.setattr(
            event_routes.review,
            "approve_event",
            lambda *args: (_ for _ in ()).throw(RuntimeError("unexpected failure")),
        )
        with pytest.raises(RuntimeError, match="unexpected failure"):
            client.post(
                f"/api/events/{event_id}/approve",
                headers=coordinator_headers,
                json={"confirmed": True},
            )
        monkeypatch.setattr(event_routes.review, "approve_event", lambda event, user_id, comments: event)
        assert client.post(
            f"/api/events/{event_id}/approve",
            headers=coordinator_headers,
            json={"confirmed": True},
        ).status_code == 200

        assert client.post(
            "/api/events/999999/reject",
            headers=coordinator_headers,
            json={"confirmed": True},
        ).status_code == 404
        event = Event.query.get(event_id)
        event.status = "under_review"
        db.session.commit()
        assert client.post(
            f"/api/events/{event_id}/reject", headers=coordinator_headers, json={}
        ).status_code == 409
        monkeypatch.setattr(
            event_routes.review,
            "reject_event",
            lambda *args: (_ for _ in ()).throw(PermissionError("cannot reject")),
        )
        assert client.post(
            f"/api/events/{event_id}/reject",
            headers=coordinator_headers,
            json={"confirmed": True},
        ).status_code == 400
        monkeypatch.setattr(event_routes.review, "reject_event", lambda event, user_id, reason: event)
        assert client.post(
            f"/api/events/{event_id}/reject",
            headers=coordinator_headers,
            json={"confirmed": True},
        ).status_code == 200

        assert client.post("/api/events/999999/resubmit", headers=org_headers).status_code == 404
        monkeypatch.setattr(
            event_routes.review,
            "resubmit_rejected_event",
            lambda *args: (_ for _ in ()).throw(ValueError("not rejected")),
        )
        assert client.post(
            f"/api/events/{event_id}/resubmit", headers=org_headers, json={}
        ).status_code == 400
        monkeypatch.setattr(
            event_routes.review, "resubmit_rejected_event", lambda original, user_id, data: original
        )
        assert client.post(
            f"/api/events/{event_id}/resubmit", headers=org_headers, json={}
        ).status_code == 201

    def test_confirm_and_outcome_routes_cover_visibility_and_transition_errors(
        self, client, app, organiser, coordinator, make_user, make_event, auth_header, monkeypatch
    ):
        coordinator_headers = auth_header("coordinator@test.com")
        org_headers = auth_header("organiser@test.com")
        with app.app_context():
            event_id = make_event(
                organiser, status="safety_approved", coordinator_id=coordinator
            )
            other_user_id = make_user("outcome-other@test.com", ["event_organiser"])

        assert client.post("/api/events/999999/confirm", headers=coordinator_headers).status_code == 404
        assert client.post(
            f"/api/events/{event_id}/confirm", headers=auth_header("outcome-other@test.com")
        ).status_code == 403
        assert client.post(
            f"/api/events/{event_id}/confirm", headers=coordinator_headers
        ).status_code == 400

        monkeypatch.setattr(
            event_routes.status_service, "approved_safety_review_for_current_check", lambda event: object()
        )
        monkeypatch.setattr(
            event_routes.status_service,
            "confirm_after_safety_approval",
            lambda *args: (_ for _ in ()).throw(
                event_routes.status_service.InvalidTransitionError("invalid confirmation")
            ),
        )
        response = client.post(f"/api/events/{event_id}/confirm", headers=coordinator_headers)
        assert response.status_code == 400

        monkeypatch.setattr(
            event_routes.status_service, "confirm_after_safety_approval", lambda event, review, user_id: event
        )
        assert client.post(
            f"/api/events/{event_id}/confirm", headers=coordinator_headers
        ).status_code == 200

        assert client.get("/api/events/999999/outcome", headers=org_headers).status_code == 404
        assert client.get(
            f"/api/events/{event_id}/outcome",
            headers=auth_header("outcome-other@test.com"),
        ).status_code == 404
        response = client.get(f"/api/events/{event_id}/outcome", headers=org_headers)
        assert response.status_code == 200
        assert response.get_json()["status"] == "safety_approved"
        assert other_user_id is not None

    def test_assignment_status_cancel_and_safety_error_routes(
        self, client, app, organiser, coordinator, make_user, make_event, auth_header, monkeypatch
    ):
        lead_id = make_user("route-lead@test.com", ["event_coordinator_lead"])
        safety_id = make_user("route-safety@test.com", ["safety_officer"])
        lead_headers = auth_header("route-lead@test.com")
        coordinator_headers = auth_header("coordinator@test.com")
        safety_headers = auth_header("route-safety@test.com")
        with app.app_context():
            event_id = make_event(
                organiser, status="confirmed", coordinator_id=coordinator
            )

        assert client.post("/api/events/999999/auto-assign", headers=lead_headers).status_code == 404
        monkeypatch.setattr(
            event_routes.assignment,
            "try_assign_and_advance",
            lambda event: (_ for _ in ()).throw(ValueError("no coordinator")),
        )
        assert client.post(
            f"/api/events/{event_id}/auto-assign", headers=lead_headers
        ).status_code == 400
        monkeypatch.setattr(
            event_routes.assignment, "try_assign_and_advance", lambda event: event
        )
        assert client.post(
            f"/api/events/{event_id}/auto-assign", headers=lead_headers
        ).status_code == 200

        assert client.get(
            "/api/events/999999/assignment-history", headers=lead_headers
        ).status_code == 404
        assert client.post(
            "/api/events/999999/assign",
            headers=lead_headers,
            json={"coordinatorId": coordinator, "confirmed": True},
        ).status_code == 404
        assert client.post(
            "/api/events/999999/reassignment-request",
            headers=coordinator_headers,
            json={"reason": "Need help"},
        ).status_code == 404
        monkeypatch.setattr(
            event_routes.assignment,
            "request_reassignment",
            lambda *args: (_ for _ in ()).throw(PermissionError("not assigned")),
        )
        assert client.post(
            f"/api/events/{event_id}/reassignment-request",
            headers=coordinator_headers,
            json={"reason": "Need help"},
        ).status_code == 403
        monkeypatch.setattr(
            event_routes.assignment,
            "request_reassignment",
            lambda *args: (_ for _ in ()).throw(ValueError("invalid request")),
        )
        assert client.post(
            f"/api/events/{event_id}/reassignment-request",
            headers=coordinator_headers,
            json={"reason": "Need help"},
        ).status_code == 400

        assert client.get(
            "/api/events/999999/reassignment-request", headers=lead_headers
        ).status_code == 404
        monkeypatch.setattr(event_routes.assignment, "latest_reassignment_request", lambda event_id: None)
        response = client.get(
            f"/api/events/{event_id}/reassignment-request", headers=lead_headers
        )
        assert response.status_code == 200
        assert response.get_json() is None

        assert client.delete(
            "/api/events/999999/reassignment-request", headers=coordinator_headers
        ).status_code == 404
        monkeypatch.setattr(
            event_routes.assignment,
            "withdraw_reassignment_request",
            lambda *args: (_ for _ in ()).throw(PermissionError("not allowed")),
        )
        assert client.delete(
            f"/api/events/{event_id}/reassignment-request", headers=coordinator_headers
        ).status_code == 403
        monkeypatch.setattr(
            event_routes.assignment,
            "withdraw_reassignment_request",
            lambda *args: (_ for _ in ()).throw(ValueError("no request")),
        )
        assert client.delete(
            f"/api/events/{event_id}/reassignment-request", headers=coordinator_headers
        ).status_code == 400

        assert client.post(
            "/api/events/999999/reassignment-request/decline", headers=lead_headers
        ).status_code == 404
        monkeypatch.setattr(
            event_routes.assignment,
            "decline_reassignment_request",
            lambda *args: (_ for _ in ()).throw(ValueError("no request")),
        )
        assert client.post(
            f"/api/events/{event_id}/reassignment-request/decline",
            headers=lead_headers,
            json={},
        ).status_code == 400

        assert client.post("/api/events/999999/status", headers=coordinator_headers).status_code == 404
        other_coordinator = make_user("route-other-coord@test.com", ["event_coordinator"])
        assert client.post(
            f"/api/events/{event_id}/status",
            headers=auth_header("route-other-coord@test.com"),
            json={"status": "completed"},
        ).status_code == 403
        monkeypatch.setattr(
            event_routes.status_service,
            "change_status",
            lambda *args: (_ for _ in ()).throw(
                event_routes.status_service.InvalidTransitionError("invalid status")
            ),
        )
        assert client.post(
            f"/api/events/{event_id}/status",
            headers=coordinator_headers,
            json={"status": "completed"},
        ).status_code == 400

        monkeypatch.setattr(
            event_routes.status_service,
            "cancel_event",
            lambda *args, **kwargs: (_ for _ in ()).throw(LookupError()),
        )
        assert client.post(
            f"/api/events/{event_id}/cancel",
            headers=coordinator_headers,
            json={"reason": "Event removed", "confirmed": True},
        ).status_code == 404
        monkeypatch.setattr(
            event_routes.status_service,
            "cancel_event",
            lambda *args, **kwargs: (_ for _ in ()).throw(PermissionError("not assigned")),
        )
        assert client.post(
            f"/api/events/{event_id}/cancel",
            headers=coordinator_headers,
            json={"reason": "Event removed", "confirmed": True},
        ).status_code == 403
        monkeypatch.setattr(
            event_routes.status_service,
            "cancel_event",
            lambda *args, **kwargs: (_ for _ in ()).throw(
                event_routes.status_service.EventActionError({"reason": "invalid reason"})
            ),
        )
        assert client.post(
            f"/api/events/{event_id}/cancel",
            headers=coordinator_headers,
            json={"reason": "Event removed", "confirmed": True},
        ).status_code == 400

        assert client.get(
            "/api/events/999999/safety-assessment", headers=safety_headers
        ).status_code == 404
        assert client.put(
            "/api/events/999999/safety-assessment", headers=safety_headers, json={}
        ).status_code == 404
        assert client.post(
            "/api/events/999999/safety-review", headers=safety_headers, json={}
        ).status_code == 404
        with app.app_context():
            draft_id = make_event(organiser, status="draft")
        assert client.put(
            f"/api/events/{draft_id}/safety-assessment",
            headers=safety_headers,
            json={"factorAssessments": {}},
        ).status_code == 404
        monkeypatch.setattr(
            event_routes.safety,
            "save_assessment",
            lambda *args: (_ for _ in ()).throw(
                event_routes.safety.SafetyReviewConflictError("assessment conflict")
            ),
        )
        assert client.put(
            f"/api/events/{event_id}/safety-assessment",
            headers=safety_headers,
            json={"factorAssessments": {}},
        ).status_code == 409
        monkeypatch.setattr(
            event_routes.safety,
            "review_safety_check",
            lambda *args: (_ for _ in ()).throw(ValueError("invalid safety review")),
        )
        assert client.post(
            f"/api/events/{event_id}/safety-review",
            headers=safety_headers,
            json={"decision": "approved"},
        ).status_code == 400
        assert lead_id is not None
        assert safety_id is not None
        assert other_coordinator is not None
