"""Equipment Availability Checking epic."""
from app.models.equipment import EquipmentItem, EquipmentReservation


ACTIVE = "active"
RESERVED = "reserved"


def check_availability(
    equipment_item: EquipmentItem,
    quantity_needed: int,
    start,
    end,
    exclude_event_id=None,
    lock_reservations=False,
) -> dict:
    """Return availability for [start, end).

    Count only reserved units for this item whose periods overlap.
    Optionally exclude the checking event's own reservations.
    Inactive equipment has no available units.
    """
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

    query = EquipmentReservation.query.filter(
        EquipmentReservation.equipment_item_id == equipment_item.id,
        EquipmentReservation.status == RESERVED,
        EquipmentReservation.start_datetime < end,
        EquipmentReservation.end_datetime > start,
    )

    if exclude_event_id is not None:
        query = query.filter(
            EquipmentReservation.event_id != exclude_event_id
        )

    if lock_reservations:
        query = query.with_for_update()

    overlapping = query.all()
    committed = sum(r.quantity for r in overlapping)
    free = max(0, equipment_item.total_quantity - committed)

    result.update(
        available=free >= quantity_needed,
        freeQuantity=free,
    )

    if free < quantity_needed:
        result["shortfall"] = quantity_needed - free

    return result