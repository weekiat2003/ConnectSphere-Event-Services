from functools import wraps

from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity

from app.auth.decorators import roles_required
from app.registrations import service

registrations_bp = Blueprint("registrations", __name__)


def _user_id():
    return int(get_jwt_identity())


def _handle(fn):
    """Turn the service's RegistrationError into a JSON error response."""

    @wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except service.RegistrationError as e:
            body = {"error": str(e), "code": e.code}
            if isinstance(e, service.EventFull):
                body["waitlistAvailable"] = True
            return jsonify(body), e.status_code

    return wrapper


# ---------------------------------------------------------------- attendees
@registrations_bp.get("/events")
@roles_required("attendee")
@_handle
def browse_events():
    return jsonify(service.list_events(_user_id())), 200


@registrations_bp.get("/events/<int:event_id>")
@roles_required("attendee")
@_handle
def view_event(event_id):
    return jsonify(service.get_event(event_id, _user_id())), 200


@registrations_bp.post("/events/<int:event_id>/register")
@roles_required("attendee")
@_handle
def register(event_id):
    registration = service.register(event_id, _user_id())
    return jsonify(registration.to_dict()), 201


@registrations_bp.post("/events/<int:event_id>/waitlist")
@roles_required("attendee")
@_handle
def join_waitlist(event_id):
    registration = service.join_waitlist(event_id, _user_id())
    body = registration.to_dict()
    body["queuePosition"] = service.queue_position(registration)
    return jsonify(body), 201


@registrations_bp.post("/events/<int:event_id>/follow")
@roles_required("attendee")
@_handle
def follow_event(event_id):
    """Opt in to updates for this event (ISP-108)."""
    return jsonify(service.set_following(event_id, _user_id(), True)), 200


@registrations_bp.delete("/events/<int:event_id>/follow")
@roles_required("attendee")
@_handle
def unfollow_event(event_id):
    return jsonify(service.set_following(event_id, _user_id(), False)), 200


@registrations_bp.get("/mine")
@roles_required("attendee")
@_handle
def my_registrations():
    return jsonify(service.my_registrations(_user_id())), 200


@registrations_bp.post("/<int:registration_id>/withdraw")
@roles_required("attendee")
@_handle
def withdraw(registration_id):
    registration, promoted = service.withdraw(registration_id, _user_id())
    return jsonify({**registration.to_dict(), "promotedRegistrationIds": [p.id for p in promoted]}), 200


# ------------------------------------------------- organisers & coordinators
@registrations_bp.get("/manage/events")
@roles_required("event_organiser", "event_coordinator")
@_handle
def managed_events():
    return jsonify(service.list_managed_events(_user_id())), 200


@registrations_bp.post("/events/<int:event_id>/open")
@roles_required("event_organiser")
@_handle
def open_registration(event_id):
    service.open_registration(event_id, _user_id())
    return jsonify({"eventId": event_id, "registrationOpen": True}), 200


@registrations_bp.post("/events/<int:event_id>/close")
@roles_required("event_organiser")
@_handle
def close_registration(event_id):
    service.close_registration(event_id, _user_id())
    return jsonify({"eventId": event_id, "registrationOpen": False}), 200


@registrations_bp.get("/events/<int:event_id>/attendees")
@roles_required("event_organiser", "event_coordinator")
@_handle
def attendee_list(event_id):
    page = request.args.get("page", 1, type=int)
    page_size = request.args.get("pageSize", 50, type=int)
    return jsonify(service.list_attendees(event_id, _user_id(), page, page_size)), 200
