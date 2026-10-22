"""Technical review: an event's equipment requirements with reservation details."""
from app.equipment.services.reservation import RESERVED
from app.extensions import db
from app.models.equipment import EquipmentReservation
from app.models.event import Event


def get_event_requirements(event_id: int) -> dict:
    """Raises LookupError if the event does not exist."""
    event = db.session.get(Event, event_id)
    if event is None:
        raise LookupError("Event not found")

    active = EquipmentReservation.query.filter_by(
        event_id=event.id, status=RESERVED
    ).all()
    by_requirement = {r.equipment_requirement_id: r for r in active}

    rows = []
    for requirement in sorted(event.equipment_requirements, key=lambda r: r.id):
        row = requirement.to_dict()
        booking = by_requirement.get(requirement.id)
        row["reservation"] = None if booking is None else {
            "id": booking.id,
            "quantity": booking.quantity,
            "start": booking.start_datetime.isoformat(),
            "end": booking.end_datetime.isoformat(),
        }
        rows.append(row)

    return {
        "eventId": event.id,
        "name": event.name,
        "status": event.status,
        "requirements": rows,
    }