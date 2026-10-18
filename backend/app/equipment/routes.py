from datetime import datetime

from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity

from app.auth.decorators import roles_required
from app.equipment.services import availability, catalogue, preparation, reservation
from app.models.equipment import EquipmentReservation
from app.models.event import Event, EventEquipmentRequirement
from app.models.user import User

equipment_bp = Blueprint("equipment", __name__)


def _current_user():
    return User.query.get(int(get_jwt_identity()))


# ---------------------------------------------------------------------
# Equipment catalogue (backs Equipment Availability Checking)
# ---------------------------------------------------------------------

@equipment_bp.post("/items")
@roles_required("technical_support_staff")
def create_item():
    try:
        item = catalogue.create_item(request.get_json() or {})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify(item.to_dict()), 201


@equipment_bp.get("/items")
@roles_required("technical_support_staff", "event_coordinator")
def list_items():
    return jsonify([i.to_dict() for i in catalogue.list_items()]), 200


@equipment_bp.put("/items/<int:item_id>")
@roles_required("technical_support_staff")
def update_item(item_id):
    item = catalogue.get_item(item_id)
    if not item:
        return jsonify({"error": "Equipment item not found"}), 404
    item = catalogue.update_item(item, request.get_json() or {})
    return jsonify(item.to_dict()), 200


@equipment_bp.post("/items/<int:item_id>/mark-unavailable")
@roles_required("technical_support_staff")
def mark_item_unavailable(item_id):
    item = catalogue.get_item(item_id)
    if not item:
        return jsonify({"error": "Equipment item not found"}), 404
    item = catalogue.mark_unavailable(item)
    return jsonify(item.to_dict()), 200


@equipment_bp.post("/items/<int:item_id>/mark-active")
@roles_required("technical_support_staff")
def mark_item_active(item_id):
    item = catalogue.get_item(item_id)
    if not item:
        return jsonify({"error": "Equipment item not found"}), 404
    item = catalogue.mark_active(item)
    return jsonify(item.to_dict()), 200


# ---------------------------------------------------------------------
# Equipment Availability Checking
# ---------------------------------------------------------------------

@equipment_bp.get("/items/<int:item_id>/availability")
@roles_required("technical_support_staff", "event_coordinator")
def check_item_availability(item_id):
    item = catalogue.get_item(item_id)
    if not item:
        return jsonify({"error": "Equipment item not found"}), 404
    start = request.args.get("start")
    end = request.args.get("end")
    quantity = request.args.get("quantity", type=int, default=1)
    if not start or not end:
        return jsonify({"error": "start and end query params (ISO datetimes) are required"}), 400
    result = availability.check_availability(item, quantity, datetime.fromisoformat(start), datetime.fromisoformat(end))
    return jsonify(result), 200


# ---------------------------------------------------------------------
# Equipment Reservation
# ---------------------------------------------------------------------

@equipment_bp.post("/reservations")
@roles_required("technical_support_staff")
def reserve_equipment():
    user = _current_user()
    data = request.get_json() or {}

    event = Event.query.get(data.get("eventId"))
    requirement = EventEquipmentRequirement.query.get(data.get("requirementId"))
    item = catalogue.get_item(data.get("equipmentItemId"))
    if not event or not requirement or not item:
        return jsonify({"error": "Event, requirement, or equipment item not found"}), 404

    try:
        result = reservation.reserve(
            event,
            requirement,
            item,
            datetime.fromisoformat(data.get("start")),
            datetime.fromisoformat(data.get("end")),
            user.id,
        )
    except (ValueError, TypeError) as e:
        return jsonify({"error": str(e)}), 400
    return jsonify(result.to_dict()), 201


@equipment_bp.post("/reservations/<int:reservation_id>/release")
@roles_required("technical_support_staff")
def release_equipment(reservation_id):
    record = EquipmentReservation.query.get(reservation_id)
    if not record:
        return jsonify({"error": "Reservation not found"}), 404
    try:
        result = reservation.release(record)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify(result.to_dict()), 200


@equipment_bp.put("/requirements/<int:requirement_id>/preparation")
@roles_required("technical_support_staff")
def update_requirement_preparation(requirement_id):
    requirement = EventEquipmentRequirement.query.get(requirement_id)
    if not requirement:
        return jsonify({"error": "Equipment requirement not found"}), 404
    try:
        result = preparation.update_equipment_preparation(
            requirement, _current_user(), request.get_json() or {}
        )
    except PermissionError as exc:
        return jsonify({"error": str(exc)}), 403
    except preparation.EquipmentPreparationError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify(result.to_dict()), 200
