"""Equipment Availability Checking epic."""
from app.models.equipment import EquipmentItem, EquipmentReservation


ACTIVE = "active"
RESERVED = "reserved"


def check_availability(equipment_item: EquipmentItem, quantity_needed: int, start, end) -> dict:
    """Returns whether enough units are free for [start, end], excluding
    equipment already committed to another overlapping event and equipment
    that is not active (damaged, maintenance or retired)."""
    result = {
        "item": {"id": equipment_item.id, "name": equipment_item.name},
        "requestedQuantity": quantity_needed,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "totalQuantity": equipment_item.total_quantity,
    }

    if equipment_item.status != ACTIVE:
        result.update(
            available=False,
            freeQuantity=0,
            shortfall=quantity_needed,
            reason=f"Equipment is not active (status: {equipment_item.status})",
        )
        return result

    overlapping = EquipmentReservation.query.filter(
        EquipmentReservation.equipment_item_id == equipment_item.id,
        EquipmentReservation.status == RESERVED,
        EquipmentReservation.start_datetime < end,
        EquipmentReservation.end_datetime > start,
    ).all()
    committed = sum(r.quantity for r in overlapping)
    free = equipment_item.total_quantity - committed

    result.update(available=free >= quantity_needed, freeQuantity=free)
    if free < quantity_needed:
        result["shortfall"] = quantity_needed - free
    return result