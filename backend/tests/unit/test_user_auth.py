import pytest

from unittest.mock import patch, MagicMock

from flask import Flask
from flask_jwt_extended import JWTManager, create_refresh_token

from app.auth.routes import auth_bp

from flask_jwt_extended import (
    create_access_token,
)

@pytest.fixture
def app():
    """
    Create a test Flask application with JWT enabled.
    """
    app = Flask(__name__)

    app.config["JWT_SECRET_KEY"] = "test-secret-key"

    JWTManager(app)

    app.register_blueprint(auth_bp)

    return app


@pytest.fixture
def client(app):
    """
    Create a Flask test client.
    """
    return app.test_client()


def create_test_refresh_token(app):
    """
    Create a valid refresh token for testing routes
    protected by @jwt_required(refresh=True).
    """
    with app.app_context():
        return create_refresh_token(identity="1")


@patch("app.auth.routes.authenticate")
def test_login_missing_email_or_password(mock_authenticate, client):
    # Test when email or password is missing

    response = client.post(
        "/login",
        json={"email": "test@example.com"}
    )

    assert response.status_code == 400
    assert response.json == {
        "error": "email and password are required"
    }

    response = client.post(
        "/login",
        json={"password": "password123"}
    )

    assert response.status_code == 400
    assert response.json == {
        "error": "email and password are required"
    }


@patch("app.auth.routes.authenticate")
def test_login_invalid_credentials(mock_authenticate, client):
    # Test when credentials are invalid

    mock_authenticate.return_value = None

    response = client.post(
        "/login",
        json={
            "email": "test@example.com",
            "password": "wrongpassword"
        }
    )

    assert response.status_code == 401
    assert response.json == {
        "error": "Invalid credentials"
    }


@patch("app.auth.routes.issue_tokens")
@patch("app.auth.routes.authenticate")
def test_login_successful(
    mock_authenticate,
    mock_issue_tokens,
    client
):
    # Test successful login

    mock_user = MagicMock()

    mock_user.to_dict.return_value = {
        "id": 1,
        "email": "test@example.com"
    }

    mock_authenticate.return_value = mock_user

    mock_issue_tokens.return_value = (
        "access_token_mock",
        "refresh_token_mock"
    )

    response = client.post(
        "/login",
        json={
            "email": "test@example.com",
            "password": "password123"
        }
    )

    assert response.status_code == 200

    assert response.json == {
        "accessToken": "access_token_mock",
        "refreshToken": "refresh_token_mock",
        "user": {
            "id": 1,
            "email": "test@example.com"
        },
    }

    mock_authenticate.assert_called_once_with(
        "test@example.com",
        "password123"
    )

    mock_issue_tokens.assert_called_once_with(mock_user)


@patch("app.auth.routes.authenticate")
def test_login_unexpected_error(mock_authenticate, client):
    # Simulate an unexpected exception during authentication

    mock_authenticate.side_effect = Exception("Unexpected error")

    response = client.post(
        "/login",
        json={
            "email": "test@example.com",
            "password": "password123"
        }
    )

    assert response.status_code == 500

    assert response.get_json() == {
        "error": "An unexpected error occurred"
    }


@patch("app.auth.routes.revoke_refresh_token")
@patch("app.auth.routes.get_jwt")
def test_logout_success(
    mock_get_jwt,
    mock_revoke_refresh_token,
    client,
    app
):
    # Mock the JWT claims and revoke function

    mock_get_jwt.return_value = {
        "jti": "test-jti"
    }

    mock_revoke_refresh_token.return_value = None

    # Create a valid refresh JWT.
    # The identity must be a string.
    refresh_token = create_test_refresh_token(app)

    response = client.post(
        "/logout",
        headers={
            "Authorization": f"Bearer {refresh_token}"
        }
    )

    assert response.status_code == 200

    assert response.get_json() == {
        "message": "Successfully logged out"
    }

    mock_get_jwt.assert_called_once()

    mock_revoke_refresh_token.assert_called_once_with(
        "test-jti"
    )


@patch("app.auth.routes.revoke_refresh_token")
@patch("app.auth.routes.get_jwt")
def test_logout_unexpected_error(
    mock_get_jwt,
    mock_revoke_refresh_token,
    client,
    app
):
    # Simulate an unexpected error during logout

    mock_get_jwt.side_effect = Exception("Unexpected error")

    # Create a valid refresh JWT.
    # The identity must be a string.
    refresh_token = create_test_refresh_token(app)

    response = client.post(
        "/logout",
        headers={
            "Authorization": f"Bearer {refresh_token}"
        }
    )

    assert response.status_code == 500

    assert response.get_json() == {
        "error": "An unexpected error occurred"
    }

@patch("app.auth.routes.issue_tokens")
@patch("app.auth.routes.User")
@patch("app.auth.routes.is_refresh_token_valid")
@patch("app.auth.routes.get_jwt")
def test_refresh_success(
    mock_get_jwt,
    mock_is_refresh_token_valid,
    mock_user_model,
    mock_issue_tokens,
    client,
    app
):
    mock_get_jwt.return_value = {
        "jti": "test-jti"
    }

    mock_is_refresh_token_valid.return_value = True

    mock_user = MagicMock()
    mock_user.is_active = True
    mock_user_model.query.get.return_value = mock_user

    mock_issue_tokens.return_value = (
        "new_access_token",
        "new_refresh_token"
    )

    refresh_token = create_test_refresh_token(app)

    response = client.post(
        "/refresh",
        headers={
            "Authorization": f"Bearer {refresh_token}"
        }
    )

    assert response.status_code == 200

    assert response.get_json() == {
        "accessToken": "new_access_token",
        "refreshToken": "new_refresh_token"
    }

    mock_is_refresh_token_valid.assert_called_once_with("test-jti")
    mock_issue_tokens.assert_called_once_with(mock_user)

@patch("app.auth.routes.is_refresh_token_valid")
@patch("app.auth.routes.get_jwt")
def test_refresh_revoked_token(
    mock_get_jwt,
    mock_is_refresh_token_valid,
    client,
    app
):
    mock_get_jwt.return_value = {
        "jti": "revoked-jti"
    }

    mock_is_refresh_token_valid.return_value = False

    refresh_token = create_test_refresh_token(app)

    response = client.post(
        "/refresh",
        headers={
            "Authorization": f"Bearer {refresh_token}"
        }
    )

    assert response.status_code == 401

    assert response.get_json() == {
        "error": "Refresh token has been revoked"
    }

@patch("app.auth.routes.User")
@patch("app.auth.routes.get_jwt_identity")
def test_me_success(
    mock_get_jwt_identity,
    mock_user_model,
    client,
    app
):
    mock_get_jwt_identity.return_value = "1"

    mock_user = MagicMock()

    mock_user.to_dict.return_value = {
        "id": 1,
        "email": "test@example.com"
    }

    mock_user_model.query.get.return_value = mock_user

    with app.app_context():
        access_token = create_access_token(identity="1")

    response = client.get(
        "/me",
        headers={
            "Authorization": f"Bearer {access_token}"
        }
    )

    assert response.status_code == 200

    assert response.get_json() == {
        "id": 1,
        "email": "test@example.com"
    }

    mock_get_jwt_identity.assert_called_once()
    mock_user_model.query.get.assert_called_once_with(1)

@patch("app.auth.routes.User")
@patch("app.auth.routes.get_jwt_identity")
def test_me_user_not_found(
    mock_get_jwt_identity,
    mock_user_model,
    client,
    app
):
    mock_get_jwt_identity.return_value = "999"

    # User.query.get(...) returns None
    mock_user_model.query.get.return_value = None

    with app.app_context():
        access_token = create_access_token(identity="999")

    response = client.get(
        "/me",
        headers={
            "Authorization": f"Bearer {access_token}"
        }
    )

    assert response.status_code == 404

    assert response.get_json() == {
        "error": "User not found"
    }

    mock_get_jwt_identity.assert_called_once()
    mock_user_model.query.get.assert_called_once_with(999)

@patch("app.auth.routes.User")
@patch("app.auth.routes.is_refresh_token_valid")
@patch("app.auth.routes.get_jwt")
def test_refresh_user_not_found(
    mock_get_jwt,
    mock_is_refresh_token_valid,
    mock_user_model,
    client,
    app
):
    mock_get_jwt.return_value = {
        "jti": "test-jti"
    }

    mock_is_refresh_token_valid.return_value = True

    mock_user_model.query.get.return_value = None

    refresh_token = create_test_refresh_token(app)

    response = client.post(
        "/refresh",
        headers={
            "Authorization": f"Bearer {refresh_token}"
        }
    )

    assert response.status_code == 401

    assert response.get_json() == {
        "error": "User not found or inactive"
    }

@patch("app.auth.routes.User")
@patch("app.auth.routes.is_refresh_token_valid")
@patch("app.auth.routes.get_jwt")
def test_refresh_inactive_user(
    mock_get_jwt,
    mock_is_refresh_token_valid,
    mock_user_model,
    client,
    app
):
    mock_get_jwt.return_value = {
        "jti": "test-jti"
    }

    mock_is_refresh_token_valid.return_value = True

    mock_user = MagicMock()
    mock_user.is_active = False

    mock_user_model.query.get.return_value = mock_user

    refresh_token = create_test_refresh_token(app)

    response = client.post(
        "/refresh",
        headers={
            "Authorization": f"Bearer {refresh_token}"
        }
    )

    assert response.status_code == 401

    assert response.get_json() == {
        "error": "User not found or inactive"
    }

@patch("app.auth.routes.list_active_users")
def test_list_users_success(
    mock_list_active_users,
    client,
    app
):
    # Mock active users
    mock_user_1 = MagicMock()
    mock_user_1.to_dict.return_value = {
        "id": 1,
        "email": "user1@example.com",
        "role": "event_coordinator",
    }

    mock_user_2 = MagicMock()
    mock_user_2.to_dict.return_value = {
        "id": 2,
        "email": "user2@example.com",
        "role": "event_coordinator",
    }

    mock_list_active_users.return_value = [
        mock_user_1,
        mock_user_2,
    ]

    # Create JWT with the required role
    with app.app_context():
        access_token = create_access_token(
            identity="1",
            additional_claims={
                "roles": ["event_coordinator"]
            }
        )

    response = client.get(
        "/users",
        headers={
            "Authorization": f"Bearer {access_token}"
        }
    )

    assert response.status_code == 200

    assert response.get_json() == [
        {
            "id": 1,
            "email": "user1@example.com",
            "role": "event_coordinator",
        },
        {
            "id": 2,
            "email": "user2@example.com",
            "role": "event_coordinator",
        },
    ]

    mock_list_active_users.assert_called_once_with(None)

@patch("app.auth.routes.list_active_users")
def test_list_users_with_role_filter(
    mock_list_active_users,
    client,
    app
):
    mock_user = MagicMock()

    mock_user.to_dict.return_value = {
        "id": 1,
        "email": "coordinator@example.com",
        "role": "event_coordinator",
    }

    mock_list_active_users.return_value = [mock_user]

    with app.app_context():
        access_token = create_access_token(
            identity="1",
            additional_claims={
                "roles": ["event_coordinator"]
            }
        )

    response = client.get(
        "/users?role=event_coordinator",
        headers={
            "Authorization": f"Bearer {access_token}"
        }
    )

    assert response.status_code == 200

    assert response.get_json() == [
        {
            "id": 1,
            "email": "coordinator@example.com",
            "role": "event_coordinator",
        }
    ]

    mock_list_active_users.assert_called_once_with(
        "event_coordinator"
    )

def test_list_users_insufficient_role(client, app):
    with app.app_context():
        access_token = create_access_token(
            identity="1",
            additional_claims={
                "roles": ["regular_user"]
            }
        )

    response = client.get(
        "/users",
        headers={
            "Authorization": f"Bearer {access_token}"
        }
    )

    assert response.status_code == 403

    assert response.get_json() == {
        "error": "Forbidden: insufficient role"
    }

@patch("app.auth.routes.get_jwt")
def test_logout_invalid_token(mock_get_jwt, client, app):
    # Simulate a JWT with a missing "jti" claim.
    # Accessing claims["jti"] will raise KeyError.

    mock_get_jwt.return_value = {}

    refresh_token = create_test_refresh_token(app)

    response = client.post(
        "/logout",
        headers={
            "Authorization": f"Bearer {refresh_token}"
        }
    )

    assert response.status_code == 400

    assert response.get_json() == {
        "error": "Invalid token"
    }

    mock_get_jwt.assert_called_once()