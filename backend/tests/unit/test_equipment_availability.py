from datetime import datetime

import pytest

from app.equipment.services.availability import check_availability
from app.extensions import db
from app.models.equipment import EquipmentItem, EquipmentReservation

START = datetime(2026, 12, 1, 10, 0)
END = datetime(2026, 12, 1, 11, 0)


@pytest.fixture()
def projector(app):
    it = EquipmentItem(name="Projector", total_quantity=10)
    db.session.add(it)
    db.session.commit()
    return it


@pytest.fixture()
def reserve(organiser, make_event):
    def _reserve(item_id, qty, status="reserved"):
        db.session.add(EquipmentReservation(
            event_id=make_event(organiser), equipment_item_id=item_id, quantity=qty,
            start_datetime=START, end_datetime=END, status=status,
        ))
        db.session.commit()
    return _reserve


def test_all_units_free_with_no_reservations(projector):
    r = check_availability(projector, 4, START, END)
    assert r["available"] is True and r["freeQuantity"] == 10
    assert "shortfall" not in r


def test_shortfall_is_requested_minus_free(projector, reserve):
    reserve(projector.id, 8)
    r = check_availability(projector, 5, START, END)
    assert r["available"] is False and r["freeQuantity"] == 2 and r["shortfall"] == 3


@pytest.mark.parametrize("wanted,expected", [(4, True), (5, True), (6, False)])
def test_boundary_around_free_quantity(projector, reserve, wanted, expected):
    reserve(projector.id, 5)
    assert check_availability(projector, wanted, START, END)["available"] is expected


def test_inactive_item_has_zero_free_and_reason(projector):
    projector.status = "damaged"
    r = check_availability(projector, 1, START, END)
    assert r["available"] is False and r["freeQuantity"] == 0
    assert "damaged" in r["reason"]


def test_released_reservation_is_not_counted(projector, reserve):
    reserve(projector.id, 8, status="released")
    assert check_availability(projector, 10, START, END)["available"] is True


def test_result_echoes_item_quantity_and_period(projector):
    r = check_availability(projector, 2, START, END)
    assert r["item"]["name"] == "Projector" and r["requestedQuantity"] == 2
    assert r["start"] == START.isoformat() and r["end"] == END.isoformat()