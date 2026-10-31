"""Equipment Reservation epic."""
from app.extensions import db
from app.equipment.services.availability import check_availability
from app.models.equipment import EquipmentItem, EquipmentReservation
from app.models.event import Event, EventEquipmentRequirement

RESERVED = "reserved"
RELEASED = "released"
ACTIVE = "active"
RESERVABLE_EVENT_STATUSES = ("approved", "planning", "safety_check", "confirmed")
_USE_REQUIREMENT_QUANTITY = object()


class ReservationError(ValueError):
    """A reservation validation error with its corresponding HTTP status."""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def reserve(
    event: Event,
    requirement: EventEquipmentRequirement,
    equipment_item: EquipmentItem,
    start,
    end,
    user_id: int,
    quantity=_USE_REQUIREMENT_QUANTITY,
) -> EquipmentReservation:
    try:
        if end <= start:
            raise ReservationError("end must be after start")
    except TypeError:
        raise ReservationError("start and end must both include, or both omit, a timezone")

    if requirement.event_id != event.id:
        raise ReservationError("Requirement does not belong to this event")

    if event.status not in RESERVABLE_EVENT_STATUSES:
        raise ReservationError(
            f"Equipment cannot be reserved for an event with status '{event.status}'"
        )

    if quantity is _USE_REQUIREMENT_QUANTITY:
        quantity = requirement.quantity
    if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 1:
        raise ReservationError("quantity must be a positive whole number")
    if quantity > requirement.quantity:
        raise ReservationError(
            "Reservation quantity cannot exceed the requirement's requested quantity"
        )

    # Lock the item row so two reservations cannot both claim the last units.
    item = (
        db.session.query(EquipmentItem)
        .filter_by(id=equipment_item.id)
        .populate_existing()
        .with_for_update()
        .one()
    )
    if item.status != ACTIVE:
        raise ReservationError(f"{item.name} is not active (status: {item.status})")

    if item.name.strip().casefold() != requirement.equipment_type.strip().casefold():
        raise ReservationError("This item doesn't match the requested equipment type.")

    # Locking reads see the latest committed rows, not an older snapshot.
    already_reserved = (
        EquipmentReservation.query.filter_by(
            equipment_requirement_id=requirement.id, status=RESERVED
        )
        .with_for_update()
        .first()
    )
    if already_reserved:
        raise ReservationError("This requirement already has a reservation")

    result = check_availability(
        item, quantity, start, end, lock_reservations=True
    )
    if not result["available"]:
        raise ReservationError(f"Not enough {item.name} available for the requested period")

    reservation = EquipmentReservation(
        event_id=event.id,
        equipment_requirement_id=requirement.id,
        equipment_item_id=item.id,
        quantity=quantity,
        start_datetime=start,
        end_datetime=end,
        status=RESERVED,
        created_by=user_id,
    )
    db.session.add(reservation)
    requirement.status = "confirmed"
    db.session.commit()

    from app.events.services.status import try_advance_to_safety_check

    try_advance_to_safety_check(event, user_id)
    return reservation


def release(reservation: EquipmentReservation) -> EquipmentReservation:
    """Releases equipment back to availability when an event is cancelled
    or the requirement is removed."""
    if reservation.status != RESERVED:
        raise ValueError("Only a currently reserved item can be released")
    reservation.status = RELEASED
    db.session.commit()

    from app.events.services.status import reconsider_event_after_arrangement_loss

    reconsider_event_after_arrangement_loss(
        reservation.event,
        reservation.created_by,
        reason=f"Equipment reservation {reservation.id} was released; arrangements need review",
    )
    return reservation