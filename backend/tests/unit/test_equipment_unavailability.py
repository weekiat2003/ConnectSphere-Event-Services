"""
Unit tests for ISP-61: Mark equipment unavailable due to damage or maintenance.
Target: app/equipment/services/catalogue.py (and availability.py for the reason text).
Integration tests (HTTP status codes and roles) live in tests/integration.
"""
import time
from datetime import datetime, timedelta

import pytest

from app.equipment.services import availability, catalogue
from app.extensions import db
from app.models.equipment import EquipmentReservation
from app.models.event import Event

D = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=30)


def _item(name="Projector", total=10):
    return catalogue.create_item({"name": name, "totalQuantity": total})


def _reservation(item, organiser_id, qty=3, status="reserved"):
    event = Event(organiser_id=organiser_id, status="approved",
                  name="Event A", purpose="Testing", description="Used in tests")
    db.session.add(event)
    db.session.commit()
    reservation = EquipmentReservation(
        event_id=event.id,
        equipment_item_id=item.id,
        quantity=qty,
        start_datetime=D.replace(hour=9),
        end_datetime=D.replace(hour=12),
        status=status,
    )
    db.session.add(reservation)
    db.session.commit()
    return reservation


def test_mark_unavailable_sets_status_to_reason(app):
    """ISP-61 AC1 (TC-61-01)"""
    with app.app_context():
        item = _item()
        catalogue.mark_unavailable(item, "damaged")
        assert item.status == "damaged"
        assert item.status != availability.ACTIVE


@pytest.mark.parametrize("reason", ["damaged", "maintenance"])
def test_unavailable_item_is_not_available_for_any_period(app, reason):
    """ISP-61 AC2 (TC-61-02)"""
    with app.app_context():
        item = _item()
        catalogue.mark_unavailable(item, reason)
        for day in (D, D + timedelta(days=30)):
            result = availability.check_availability(
                item, 1, day.replace(hour=9), day.replace(hour=12)
            )
            assert result["available"] is False
            assert reason in result["reason"]


@pytest.mark.parametrize("reason", [None, "", "broken"])
def test_mark_unavailable_rejects_missing_or_invalid_reason(app, reason):
    """ISP-61 AC3 (TC-61-03, service part)"""
    with app.app_context():
        item = _item()
        with pytest.raises(ValueError):
            catalogue.mark_unavailable(item, reason)
        assert item.status == "active"


def test_marking_twice_keeps_latest_reason(app):
    """ISP-61 AC4 (TC-61-04)"""
    with app.app_context():
        item = _item()
        catalogue.mark_unavailable(item, "maintenance")
        catalogue.mark_unavailable(item, "damaged")
        assert item.status == "damaged"


def test_marking_unavailable_lists_affected_reservations_without_cancelling(app, organiser):
    """ISP-61 AC5, stretch (TC-61-05)"""
    with app.app_context():
        item = _item()
        live = _reservation(item, organiser)
        _reservation(item, organiser, status="released")
        catalogue.mark_unavailable(item, "maintenance")

        affected = catalogue.affected_reservations(item)
        assert [r.id for r in affected] == [live.id]
        assert db.session.get(EquipmentReservation, live.id).status == "reserved"


def test_mark_active_restores_availability(app):
    """ISP-61 AC7 (TC-61-07)"""
    with app.app_context():
        item = _item()
        catalogue.mark_unavailable(item, "damaged")
        catalogue.mark_active(item)
        assert item.status == "active"
        result = availability.check_availability(item, 3, D.replace(hour=9), D.replace(hour=12))
        assert result["available"] is True


def test_mark_active_when_already_active_is_harmless(app):
    """ISP-61 AC8 (TC-61-08)"""
    with app.app_context():
        item = _item()
        catalogue.mark_active(item)
        assert item.status == "active"


def test_marking_does_not_change_total_or_reservations(app, organiser):
    """ISP-61 AC10 (TC-61-10)"""
    with app.app_context():
        item = _item()
        reservation = _reservation(item, organiser)
        catalogue.mark_unavailable(item, "maintenance")
        db.session.refresh(item)
        assert item.total_quantity == 10
        assert db.session.get(EquipmentReservation, reservation.id).status == "reserved"
        assert EquipmentReservation.query.count() == 1


def test_status_change_updates_timestamp(app):
    """ISP-61 AC11 (TC-61-11)"""
    with app.app_context():
        item = _item()
        before = item.updated_at
        time.sleep(0.01)
        catalogue.mark_unavailable(item, "damaged")
        db.session.refresh(item)
        assert item.updated_at > before