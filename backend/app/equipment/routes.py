from datetime import datetime


from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity


from app.auth.decorators import roles_required
from app.equipment.services import availability, catalogue, preparation, reservation, technical_review
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
    reason = (request.get_json(silent=True) or {}).get("reason")
    try:
        item = catalogue.mark_unavailable(item, reason)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    body = item.to_dict()
    body["affectedReservations"] = [r.to_dict() for r in catalogue.affected_reservations(item)]
    return jsonify(body), 200



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
def _parse_availability_args(args):
    """Validates the availability query string; the error message names the bad field."""
    try:
        start = datetime.fromisoformat(args.get("start") or "")
    except ValueError:
        raise ValueError("start is required and must be an ISO datetime")
    try:
        end = datetime.fromisoformat(args.get("end") or "")
    except ValueError:
        raise ValueError("end is required and must be an ISO datetime")
    try:
        if end <= start:
            raise ValueError("end must be after start")
    except TypeError:
        raise ValueError("start and end must both include, or both omit, a timezone")
    try:
        quantity = int(args.get("quantity", "1"))
    except ValueError:
        raise ValueError("quantity must be a whole number")
    if quantity < 1:
        raise ValueError("quantity must be at least 1")
    return start, end, quantity


@equipment_bp.get("/items/<int:item_id>/availability")
@roles_required("technical_support_staff", "event_coordinator")
def check_item_availability(item_id):
    item = catalogue.get_item(item_id)
    if not item:
        return jsonify({"error": "Equipment item not found"}), 404
    try:
        start, end, quantity = _parse_availability_args(request.args)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify(availability.check_availability(item, quantity, start, end)), 200


@equipment_bp.get("/events/<int:event_id>/availability")
@roles_required("technical_support_staff", "event_coordinator")
def check_event_availability(event_id):
    event = Event.query.get(event_id)
    if not event:
        return jsonify({"error": "Event not found"}), 404
    try:
        start, end, _ = _parse_availability_args(request.args)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


    requirements = (
        EventEquipmentRequirement.query.filter_by(event_id=event.id)
        .order_by(EventEquipmentRequirement.id)
        .all()
    )
    results = []
    for req in requirements:
        item = catalogue.get_item_by_name(req.equipment_type)
        if item:
            result = availability.check_availability(
                item,
                req.quantity,
                start,
                end,
                exclude_event_id=event.id,
            )
        else:
            result = {
                "available": False,
                "requestedQuantity": req.quantity,
                "reason": f"No catalogue item named '{req.equipment_type}'",
            }
        results.append({"requirementId": req.id, "type": req.equipment_type, **result})


    return jsonify({
        "eventId": event.id,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "results": results,
        "available": all(r["available"] for r in results),
    }), 200



# ---------------------------------------------------------------------
# Equipment Reservation
# ---------------------------------------------------------------------


def _parse_reservation_period(data):
    try:
        start = datetime.fromisoformat(data.get("start") or "")
    except (TypeError, ValueError):
        raise ValueError("start is required and must be an ISO datetime")
    try:
        end = datetime.fromisoformat(data.get("end") or "")
    except (TypeError, ValueError):
        raise ValueError("end is required and must be an ISO datetime")
    return start, end


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
        start, end = _parse_reservation_period(data)
        result = reservation.reserve(event, requirement, item, start, end, user.id)
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



# ---------------------------------------------------------------------
# Technical review (Technical Support Staff view an event's requirements)
# ---------------------------------------------------------------------


@equipment_bp.get("/events/<int:event_id>/requirements")
@roles_required("technical_support_staff")
def technical_review_requirements(event_id):
    try:
        result = technical_review.get_event_requirements(event_id)
    except LookupError as exc:
        return jsonify({"error": str(exc)}), 404
    return jsonify(result), 200