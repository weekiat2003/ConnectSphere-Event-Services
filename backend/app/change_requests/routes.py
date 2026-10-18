from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity

from app.auth.decorators import roles_required
from app.change_requests.services import (
    ChangeRequestError,
    can_request_change,
    list_change_requests_for_coordinator,
    list_change_requests_for_event,
    submit_change_request,
    current_venue_id,
    can_request_withdrawal,
    request_withdrawal,
    get_review_detail,
    list_review_queue,
    process_routine_change,
    trigger_re_review,
    apply_re_reviewed_change,
    reject_change_request,

)
from app.models.event import Event
from app.models.user import User
from app.extensions import db
from app.venues.services import catalogue as venue_catalogue

change_requests_bp = Blueprint("change_requests", __name__)
# What an organiser may see of a venue: enough to choose one, nothing internal
# (no setup/turnaround minutes, operating hours or description).
CATALOGUE_VENUE_FIELDS = ("id", "name", "location", "capacity", "facilities", "supportedLayouts", "accessibilityFeatures")


def _current_user():
    return User.query.get(int(get_jwt_identity()))


def _own_event(event_id, user):
    event = Event.query.get(event_id)
    return event if event and event.organiser_id == user.id else None


@change_requests_bp.get("/events/<int:event_id>")
@roles_required("event_organiser")
def organiser_view(event_id):
    """Whether the option is offered, plus the organiser's tracking list."""
    user = _current_user()
    event = _own_event(event_id, user)
    if not event:
        return jsonify({"error": "Event not found"}), 404
    return jsonify({
        "canRequestChange": can_request_change(event, user.id),
        "currentVenueId": current_venue_id(event),
        "requests": [r.to_dict() for r in list_change_requests_for_event(event, user.id)],
        "canRequestWithdrawal": can_request_withdrawal(event, user.id),
    }), 200


@change_requests_bp.post("/events/<int:event_id>")
@roles_required("event_organiser")
def submit(event_id):
    user = _current_user()
    event = _own_event(event_id, user)
    if not event:
        return jsonify({"error": "Event not found"}), 404
    data = request.get_json() or {}
    try:
        created = submit_change_request(event, user.id, data.get("changes"), data.get("reason"))
    except ChangeRequestError as e:
        return jsonify({"error": "Change request could not be submitted", "errors": e.errors}), 400
    except PermissionError as e:
        return jsonify({"error": str(e)}), 403
    return jsonify(created.to_dict()), 201

@change_requests_bp.post("/events/<int:event_id>/withdrawal")
@roles_required("event_organiser")
def request_event_withdrawal(event_id):
    user = _current_user()
    event = _own_event(event_id, user)
    if not event:
        return jsonify({"error": "Event not found"}), 404
    data = request.get_json() or {}
    try:
        created = request_withdrawal(event, user.id, data.get("reason"))
    except ChangeRequestError as e:
        return jsonify({"error": "Withdrawal request could not be submitted", "errors": e.errors}), 400
    except PermissionError as e:
        return jsonify({"error": str(e)}), 403
    return jsonify(created.to_dict()), 201

@change_requests_bp.get("/assigned")
@roles_required("event_coordinator")
def assigned_to_me():
    user = _current_user()
    return jsonify([r.to_dict() for r in list_change_requests_for_coordinator(user.id)]), 200

@change_requests_bp.get("/review")
@roles_required("event_coordinator")
def review_queue():
    user = _current_user()
    return jsonify(list_review_queue(user.id)), 200


@change_requests_bp.get("/<int:request_id>/review")
@roles_required("event_coordinator")
def review_detail(request_id):
    user = _current_user()
    try:
        return jsonify(get_review_detail(request_id, user.id)), 200
    except LookupError:
        return jsonify({"error": "Change request not found"}), 404
    except PermissionError as e:
        return jsonify({"error": str(e)}), 403

@change_requests_bp.post("/<int:request_id>/process")
@roles_required("event_coordinator")
def process_change(request_id):
    user = _current_user()
    data = request.get_json() or {}
    try:
        # Refusals come first, so nobody is asked to confirm something that would fail.
        process_routine_change(request_id, user.id, dry_run=True)
        if data.get("confirmed") is not True:
            return jsonify({
                "requiresConfirmation": True,
                "message": "Apply these changes to the event? Its status, venue bookings and equipment stay as they are.",
            }), 409
        processed = process_routine_change(request_id, user.id)
    except LookupError:
        return jsonify({"error": "Change request not found"}), 404
    except PermissionError as e:
        return jsonify({"error": str(e)}), 403
    except ChangeRequestError as e:
        return jsonify({"error": "This change request could not be processed", "errors": e.errors}), 400
    return jsonify(processed.to_dict()), 200

@change_requests_bp.get("/catalogue")
@roles_required("event_organiser", "event_coordinator")
def catalogue():
    """Read-only, trimmed venue and equipment catalogue for the change screens."""
    venues = []
    for venue in venue_catalogue.list_venues():  # active venues only
        record = venue.to_dict()
        venues.append({key: record[key] for key in CATALOGUE_VENUE_FIELDS})

    # Only 'active' items can be requested. Maintenance and retired ones are hidden.
    rows = db.session.execute(
        db.text("SELECT id, name, category FROM equipment_items WHERE status = 'active' ORDER BY name")
    ).mappings().all()

    return jsonify({"venues": venues, "equipment": [dict(row) for row in rows]}), 200

@change_requests_bp.post("/<int:request_id>/reject")
@roles_required("event_coordinator")
def reject_change(request_id):
    user = _current_user()
    data = request.get_json() or {}
    reason = data.get("reason")

    try:
        # Validate first, so nobody is asked to confirm something that would fail.
        reject_change_request(request_id, user.id, reason, dry_run=True)

        if data.get("confirmed") is not True:
            return jsonify({
                "requiresConfirmation": True,
                "message": (
                    "Reject this change request? Nothing about the event will change, "
                    "and the organiser will be shown your reason."
                ),
            }), 409

        rejected = reject_change_request(request_id, user.id, reason)
    except LookupError:
        return jsonify({"error": "Change request not found"}), 404
    except PermissionError as e:
        return jsonify({"error": str(e)}), 403
    except ChangeRequestError as e:
        return jsonify({
            "error": "This change request could not be rejected",
            "errors": e.errors,
        }), 400

    return jsonify(rejected.to_dict()), 200

@change_requests_bp.post("/<int:request_id>/re-review")
@roles_required("event_coordinator")
def start_re_review(request_id):
    user = _current_user()
    data = request.get_json() or {}

    try:
        trigger_re_review(request_id, user.id, dry_run=True)

        if data.get("confirmed") is not True:
            return jsonify({
                "requiresConfirmation": True,
                "message": (
                    "Send this significant change for re-review? The event will "
                    "return to planning if it is confirmed, and affected "
                    "arrangements will be flagged for reconsideration."
                ),
            }), 409

        result = trigger_re_review(request_id, user.id)
    except LookupError:
        return jsonify({"error": "Change request not found"}), 404
    except PermissionError as e:
        return jsonify({"error": str(e)}), 403
    except ChangeRequestError as e:
        return jsonify({
            "error": "This change request could not be sent for re-review",
            "errors": e.errors,
        }), 400

    return jsonify(result.to_dict()), 200


@change_requests_bp.post("/<int:request_id>/apply")
@roles_required("event_coordinator")
def complete_re_review(request_id):
    user = _current_user()
    data = request.get_json() or {}

    try:
        apply_re_reviewed_change(request_id, user.id, dry_run=True)

        if data.get("confirmed") is not True:
            return jsonify({
                "requiresConfirmation": True,
                "message": (
                    "Record that this change is going ahead? The event details "
                    "will be updated and the reconsideration flags will be cleared."
                ),
            }), 409

        result = apply_re_reviewed_change(request_id, user.id)
    except LookupError:
        return jsonify({"error": "Change request not found"}), 404
    except PermissionError as e:
        return jsonify({"error": str(e)}), 403
    except ChangeRequestError as e:
        return jsonify({
            "error": "This change could not be recorded as going ahead",
            "errors": e.errors,
        }), 400

    return jsonify(result.to_dict()), 200