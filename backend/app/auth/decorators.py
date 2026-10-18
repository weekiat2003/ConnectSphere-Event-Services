from functools import wraps

from flask import jsonify, request
from flask_jwt_extended import get_jwt, verify_jwt_in_request


def roles_required(*allowed_roles):
    """Restrict access to users with at least one allowed role."""

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):

            # Allow browser CORS preflight requests
            if request.method == "OPTIONS":
                return "", 204

            verify_jwt_in_request()

            claims = get_jwt()
            user_roles = set(claims.get("roles", []))

            if not user_roles.intersection(allowed_roles):
                return jsonify({
                    "error": "Forbidden: insufficient role"
                }), 403

            return fn(*args, **kwargs)

        return wrapper

    return decorator