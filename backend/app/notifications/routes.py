"""In-app notification inbox. Any logged-in user sees only their own notifications."""
from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required

from app.notifications.services import core

notifications_bp = Blueprint("notifications", __name__)


def _user_id() -> int:
    return int(get_jwt_identity())


@notifications_bp.get("")
@jwt_required()
def list_mine():
    """GET /api/notifications?unread=true&limit=50"""
    unread_only = request.args.get("unread", "").lower() in ("1", "true", "yes")
    try:
        limit = max(1, min(int(request.args.get("limit", 50)), 200))
    except ValueError:
        limit = 50
    items = core.list_for_user(_user_id(), unread_only=unread_only, limit=limit)
    return jsonify([n.to_dict() for n in items]), 200


@notifications_bp.get("/unread-count")
@jwt_required()
def unread_count():
    return jsonify({"count": core.unread_count(_user_id())}), 200


@notifications_bp.post("/<int:notification_id>/read")
@jwt_required()
def mark_read(notification_id):
    try:
        notification = core.mark_read(notification_id, _user_id())
    except (LookupError, PermissionError):
        return jsonify({"error": "Notification not found"}), 404
    return jsonify(notification.to_dict()), 200


@notifications_bp.post("/read-all")
@jwt_required()
def mark_all_read():
    return jsonify({"updated": core.mark_all_read(_user_id())}), 200
