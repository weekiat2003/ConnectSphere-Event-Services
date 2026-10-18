from datetime import datetime

from app.extensions import db
from app.models.event import EventEquipmentRequirement
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

        event_response = client.get(
            f"/api/events/{event_id_for_view}",
            headers=auth_header("coordinator@test.com"),
        )
        assert event_response.status_code == 200
        assert event_response.get_json()["venueBookings"][0]["setupStatus"] == "in_progress"

    def test_non_managing_staff_returns_403(self, client, app, make_user, make_event, auth_header):
        with app.app_context():
            owner_id = make_user("owner2@test.com", ["venue_staff"])
            make_user("other2@test.com", ["venue_staff"])
            event_id = make_event(organiser_id=1, status="planning")
            booking = _make_booking(event_id, owner_id)
            booking_id = booking.id
        headers = auth_header("other2@test.com")

        res = client.put(
            f"/api/venues/bookings/{booking_id}/preparation",
            json={"setup_status": "done"},
            headers=headers,
        )

        assert res.status_code == 403

    def test_non_venue_staff_role_rejected_by_decorator(self, client, app, coordinator, make_event, auth_header):
        with app.app_context():
            event_id = make_event(organiser_id=1, status="planning")
            booking = _make_booking(event_id, coordinator)
            booking_id = booking.id
        headers = auth_header("coordinator@test.com")

        res = client.put(
            f"/api/venues/bookings/{booking_id}/preparation",
            json={"setup_status": "done"},
            headers=headers,
        )

        assert res.status_code == 403

    def test_inactive_booking_returns_400(self, client, app, make_user, make_event, auth_header):
        with app.app_context():
            staff_id = make_user("vstaff3@test.com", ["venue_staff"])
            event_id = make_event(organiser_id=1, status="planning")
            booking = _make_booking(event_id, staff_id, status="pending")
            booking_id = booking.id
        headers = auth_header("vstaff3@test.com")

        res = client.put(
            f"/api/venues/bookings/{booking_id}/preparation",
            json={"setup_status": "done"},
            headers=headers,
        )

        assert res.status_code == 400

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
        assert event_response.get_json()["status"] == "confirmed"
        assert event_response.get_json()["equipmentRequirements"][0]["testingStatus"] == "done"

    def test_non_technical_staff_cannot_update_equipment_preparation(
        self, client, app, coordinator, make_event, auth_header
    ):
        with app.app_context():
            event_id = make_event(organiser_id=1, status="planning")
            requirement = EventEquipmentRequirement(
                event_id=event_id, equipment_type="Projector", quantity=1
            )
            db.session.add(requirement)
            db.session.commit()
            requirement_id = requirement.id

        response = client.put(
            f"/api/equipment/requirements/{requirement_id}/preparation",
            json={"testing_status": "done"},
            headers=auth_header("coordinator@test.com"),
        )

        assert response.status_code == 403