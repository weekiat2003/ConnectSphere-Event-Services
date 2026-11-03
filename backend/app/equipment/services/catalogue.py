"""Backs Equipment Availability Checking: Technical Support Staff's real
inventory, separate from what an Organiser requests on an event."""
from app.common.time import utcnow
from app.extensions import db
from app.models.equipment import EquipmentItem, EquipmentReservation
from app.notifications.services import triggers as notifications

UNAVAILABLE_REASONS = ("damaged", "maintenance")


class ItemRetirementBlockedError(ValueError):
    def __init__(self, reservations):
        self.reservations = reservations
        super().__init__("Equipment item has active or future reservations")


def create_item(data: dict) -> EquipmentItem:
    name = (data.get("name") or "").strip()
    if not name:
        raise ValueError("Equipment name is required")
    if EquipmentItem.query.filter_by(name=name).first():
        raise ValueError("Equipment name already exists, including retired items")
    total_quantity = data.get("totalQuantity")
    if total_quantity is None or int(total_quantity) < 0:
        raise ValueError("totalQuantity must be zero or greater")

    item = EquipmentItem(name=name, category=data.get("category"), total_quantity=int(total_quantity))
    db.session.add(item)
    db.session.commit()
    return item


def update_item(item: EquipmentItem, data: dict) -> EquipmentItem:
    if item.status == "retired" and "totalQuantity" in data:
        raise ValueError("Equipment item is retired; its quantity cannot be edited")
    if "name" in data:
        item.name = data["name"]
    if "category" in data:
        item.category = data["category"]
    if "totalQuantity" in data:
        item.total_quantity = int(data["totalQuantity"])
    db.session.commit()
    return item


def mark_unavailable(item: EquipmentItem, reason) -> EquipmentItem:
    """Marks an item unavailable (ISP-61). The reason, 'damaged' or
    'maintenance', is stored as the item's status, which excludes the item
    from availability checks."""
    if item.status == "retired":
        raise ValueError("Equipment item is retired and cannot be marked unavailable")
    if reason not in UNAVAILABLE_REASONS:
        raise ValueError("reason must be 'damaged' or 'maintenance'")
    item.status = reason
    db.session.commit()
    return item


def affected_reservations(item: EquipmentItem):
    """Live reservations on this item that have not ended yet."""
    return EquipmentReservation.query.filter(
        EquipmentReservation.equipment_item_id == item.id,
        EquipmentReservation.status == "reserved",
        EquipmentReservation.end_datetime > utcnow(),
    ).all()


def mark_active(item: EquipmentItem) -> EquipmentItem:
    if item.status == "retired":
        raise ValueError("Equipment item is retired and cannot be restored to active")
    item.status = "active"
    db.session.commit()
    return item


def retire_item(item: EquipmentItem) -> EquipmentItem:
    reservations = affected_reservations(item)
    if reservations:
        raise ItemRetirementBlockedError(reservations)
    item.status = "retired"
    notifications.notify_coordinators_of_retired_equipment(item)
    db.session.commit()
    return item


def restore_retired_item(item: EquipmentItem) -> EquipmentItem:
    if item.status != "retired":
        raise ValueError("Equipment item is not retired")
    item.status = "active"
    db.session.commit()
    return item


def list_items():
    return EquipmentItem.query.order_by(EquipmentItem.name.asc()).all()


def get_item(item_id: int):
    return EquipmentItem.query.get(item_id)


def get_item_by_name(name: str):
    return EquipmentItem.query.filter_by(name=name).first()