from flask import Blueprint, jsonify, request

from flask_jwt_extended import get_jwt, get_jwt_identity, jwt_required

from app.auth.decorators import roles_required
from app.auth.services import (
    authenticate,
    is_refresh_token_valid,
    issue_tokens,
    list_active_users,
    revoke_refresh_token,
)

from app.models.user import User


auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/login", methods=["POST"])
def login():
    try:
        data = request.get_json()
        email = data.get("email")
        password = data.get("password")

        if not email or not password:
            return jsonify({"error": "email and password are required"}), 400

        user = authenticate(email, password)

        if not user:
            return jsonify({"error": "Invalid credentials"}), 401

        access_token, refresh_token = issue_tokens(user)

        return jsonify({
            "accessToken": access_token,
            "refreshToken": refresh_token,
            "user": user.to_dict(),
        }), 200

    except Exception:
        import traceback
        traceback.print_exc()
        return jsonify({"error": "An unexpected error occurred"}), 500


@auth_bp.post("/refresh")
@jwt_required(refresh=True)
def refresh():
    claims = get_jwt()

    if not is_refresh_token_valid(claims["jti"]):
        return jsonify({"error": "Refresh token has been revoked"}), 401

    user = User.query.get(int(get_jwt_identity()))

    if not user or not user.is_active:
        return jsonify({"error": "User not found or inactive"}), 401

    access_token, refresh_token = issue_tokens(user)

    return jsonify({
        "accessToken": access_token,
        "refreshToken": refresh_token,
    }), 200


@auth_bp.post("/logout")
@jwt_required(refresh=True)
def logout():
    try:
        claims = get_jwt()
        jti = claims["jti"]  # JWT ID

        revoke_refresh_token(jti)  # Function to revoke the token

        return jsonify({"message": "Successfully logged out"}), 200

    except KeyError:
        # Handle missing or invalid JWT claims
        return jsonify({"error": "Invalid token"}), 400

    except Exception:
        # Handle unexpected errors
        return jsonify({"error": "An unexpected error occurred"}), 500


@auth_bp.get("/me")
@jwt_required()
def me():
    user = User.query.get(int(get_jwt_identity()))

    if not user:
        return jsonify({"error": "User not found"}), 404

    return jsonify(user.to_dict()), 200


@auth_bp.get("/users")
@roles_required("event_coordinator")
def list_users():
    """
    Active users, optionally filtered by ?role=.
    Currently used to populate the Coordinator picker for
    reassignment, so a Coordinator doesn't have to know
    another Coordinator's raw user ID by heart.
    """
    role_name = request.args.get("role")
    users = list_active_users(role_name)

    return jsonify([u.to_dict() for u in users]), 200