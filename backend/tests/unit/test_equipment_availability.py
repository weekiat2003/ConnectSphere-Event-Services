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



# ---------------------------------------------------------------------
# ISP-60: exclude equipment committed to overlapping events
# ---------------------------------------------------------------------


@pytest.mark.parametrize("start,end,free", [
    (datetime(2026, 12, 1, 10), datetime(2026, 12, 1, 11), 7),
    (datetime(2026, 12, 1, 8), datetime(2026, 12, 1, 10), 7),
    (datetime(2026, 12, 1, 11), datetime(2026, 12, 1, 14), 7),
    (datetime(2026, 12, 1, 12), datetime(2026, 12, 1, 15), 10),
    (datetime(2026, 12, 1, 8), datetime(2026, 12, 1, 9), 10),
    (datetime(2026, 12, 1, 11, 59), datetime(2026, 12, 1, 15), 7),
    (datetime(2026, 12, 1, 13), datetime(2026, 12, 1, 15), 10),
])
def test_overlap_rule_boundaries(projector, organiser, make_event, start, end, free):
    db.session.add(EquipmentReservation(
        event_id=make_event(organiser), equipment_item_id=projector.id, quantity=3,
        start_datetime=datetime(2026, 12, 1, 9), end_datetime=datetime(2026, 12, 1, 12),
        status="reserved",
    ))
    db.session.commit()
    assert check_availability(projector, 1, start, end)["freeQuantity"] == free



def test_exclude_event_id_ignores_only_that_events_reservation(projector, organiser, make_event):
    a, b = make_event(organiser), make_event(organiser)
    for event_id, qty in ((a, 3), (b, 2)):
        db.session.add(EquipmentReservation(
            event_id=event_id, equipment_item_id=projector.id, quantity=qty,
            start_datetime=START, end_datetime=END, status="reserved",
        ))
    db.session.commit()