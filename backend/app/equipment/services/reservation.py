"""Equipment Reservation epic."""
from app.extensions import db
from app.equipment.services.availability import check_availability
from app.models.equipment import EquipmentItem, EquipmentReservation
from app.models.event import Event, EventEquipmentRequirement

RESERVED = "reserved"
RELEASED = "released"
ACTIVE = "active"
RESERVABLE_EVENT_STATUSES = ("approved", "planning", "safety_check", "confirmed")


def reserve(
    event: Event,
    requirement: EventEquipmentRequirement,
    equipment_item: EquipmentItem,
    start,
    end,
    user_id: int,
) -> EquipmentReservation:
    try:
        if end <= start:
            raise ValueError("end must be after start")
    except TypeError:
        raise ValueError("start and end must both include, or both omit, a timezone")

    if requirement.event_id != event.id:
        raise ValueError("Requirement does not belong to this event")

    if event.status not in RESERVABLE_EVENT_STATUSES:
        raise ValueError(
            f"Equipment cannot be reserved for an event with status '{event.status}'"
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
        raise ValueError(f"{item.name} is not active (status: {item.status})")

    # Locking reads see the latest committed rows, not an older snapshot.
    already_reserved = (
        EquipmentReservation.query.filter_by(
            equipment_requirement_id=requirement.id, status=RESERVED
        )
        .with_for_update()
        .first()
    )
    if already_reserved:
        raise ValueError("This requirement already has a reservation")

    result = check_availability(
        item, requirement.quantity, start, end, lock_reservations=True
    )
    if not result["available"]:
        raise ValueError(f"Not enough {item.name} available for the requested period")

    reservation = EquipmentReservation(
        event_id=event.id,
        equipment_requirement_id=requirement.id,
        equipment_item_id=item.id,
        quantity=requirement.quantity,
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