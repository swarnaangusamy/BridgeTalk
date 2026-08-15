"""Phase 1 — authentication flow tests.

Covers the three things that actually break in a JWT auth system: passwords
being stored or returned in the clear, tokens being accepted when they should
not be, and duplicate accounts slipping through.
"""

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from app.models.user import User, UserRole


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def test_register_returns_token_and_public_user(client):
    response = client.post(
        "/api/auth/register",
        json={
            "name": "Thamizhthilaga S D S",
            "email": "thamizh@example.com",
            "password": "a-strong-password",
            "role": "hearing",
        },
    )

    assert response.status_code == 201, response.text
    body = response.json()

    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["user"]["email"] == "thamizh@example.com"
    assert body["user"]["role"] == "hearing"

    # The single most important assertion in this file: the password must not
    # appear anywhere in the response, hashed or otherwise.
    assert "password" not in body["user"]
    assert "password_hash" not in body["user"]
    assert "a-strong-password" not in response.text


def test_register_stores_a_hash_not_the_password(client, db_session):
    client.post(
        "/api/auth/register",
        json={
            "name": "Hash Check",
            "email": "hash@example.com",
            "password": "plaintext-must-not-persist",
            "role": "deaf",
        },
    )

    user = db_session.scalar(select(User).where(User.email == "hash@example.com"))
    assert user is not None
    assert user.password_hash != "plaintext-must-not-persist"
    assert user.password_hash.startswith("$2")  # bcrypt hashes start with $2a/$2b
    assert verify_password("plaintext-must-not-persist", user.password_hash)


def test_register_normalises_email_case(client):
    client.post(
        "/api/auth/register",
        json={"name": "Case", "email": "Mixed@Example.COM", "password": "password123"},
    )

    # Logging in with different casing must reach the same account, otherwise
    # users create duplicates and cannot work out why their password "broke".
    response = client.post(
        "/api/auth/login/json",
        json={"email": "mixed@example.com", "password": "password123"},
    )
    assert response.status_code == 200, response.text


def test_register_rejects_duplicate_email(client, registered_user):
    response = client.post(
        "/api/auth/register",
        json={"name": "Impostor", "email": "swarna@example.com", "password": "password123"},
    )
    assert response.status_code == 409
    assert "already exists" in response.json()["detail"]


@pytest.mark.parametrize(
    ("payload", "reason"),
    [
        ({"name": "X", "email": "not-an-email", "password": "password123"}, "bad email"),
        ({"name": "X", "email": "short@example.com", "password": "abc"}, "password too short"),
        ({"name": "", "email": "empty@example.com", "password": "password123"}, "empty name"),
        ({"name": "X", "email": "role@example.com", "password": "password123", "role": "cat"},
         "invalid role"),
    ],
)
def test_register_rejects_invalid_input(client, payload, reason):
    response = client.post("/api/auth/register", json=payload)
    assert response.status_code == 422, f"should reject: {reason}"


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------


def test_login_with_correct_credentials(client, registered_user):
    response = client.post(
        "/api/auth/login/json",
        json={"email": "swarna@example.com", "password": "correct horse battery"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["access_token"]


def test_login_form_flow_works_for_swagger(client, registered_user):
    """The OAuth2 form flow is what Swagger UI's Authorize button posts."""
    response = client.post(
        "/api/auth/login",
        data={"username": "swarna@example.com", "password": "correct horse battery"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["access_token"]


def test_login_with_wrong_password_is_rejected(client, registered_user):
    response = client.post(
        "/api/auth/login/json",
        json={"email": "swarna@example.com", "password": "wrong-password"},
    )
    assert response.status_code == 401


def test_unknown_email_and_wrong_password_are_indistinguishable(client, registered_user):
    """Different messages here would leak which emails have accounts.

    That is a real privacy problem for a platform whose users are identifiable
    by disability, so both failures must look identical from outside.
    """
    unknown = client.post(
        "/api/auth/login/json",
        json={"email": "nobody@example.com", "password": "whatever12"},
    )
    wrong = client.post(
        "/api/auth/login/json",
        json={"email": "swarna@example.com", "password": "wrong-password"},
    )

    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json()["detail"] == wrong.json()["detail"]


# ---------------------------------------------------------------------------
# Protected routes
# ---------------------------------------------------------------------------


def test_me_returns_the_current_user(client, auth_headers):
    response = client.get("/api/auth/me", headers=auth_headers)
    assert response.status_code == 200, response.text

    body = response.json()
    assert body["email"] == "swarna@example.com"
    assert body["role"] == "deaf"
    assert "password_hash" not in body


def test_me_without_a_token_is_401(client):
    assert client.get("/api/auth/me").status_code == 401


def test_me_with_a_garbage_token_is_401(client):
    response = client.get("/api/auth/me", headers={"Authorization": "Bearer not.a.jwt"})
    assert response.status_code == 401


def test_expired_token_is_rejected(client, registered_user):
    """A token past its `exp` claim must fail even though it is correctly signed."""
    expired = create_access_token(
        subject=registered_user["user"]["id"],
        expires_delta=timedelta(seconds=-60),  # already expired a minute ago
    )
    response = client.get("/api/auth/me", headers={"Authorization": f"Bearer {expired}"})
    assert response.status_code == 401


def test_token_signed_with_another_secret_is_rejected(client, registered_user):
    """The signature is the whole point — a forged token must not be accepted."""
    from jose import jwt

    forged = jwt.encode(
        {"sub": str(registered_user["user"]["id"]), "exp": 9999999999},
        "an-attackers-secret",
        algorithm="HS256",
    )
    response = client.get("/api/auth/me", headers={"Authorization": f"Bearer {forged}"})
    assert response.status_code == 401


def test_token_for_a_deleted_user_is_rejected(client, db_session, registered_user, auth_headers):
    """Signature validity is not enough; the user must still exist.

    Without the database lookup in get_current_user, a deleted account could
    keep making requests until its token expired — up to a day later.
    """
    user = db_session.scalar(select(User).where(User.email == "swarna@example.com"))
    db_session.delete(user)
    db_session.commit()

    assert client.get("/api/auth/me", headers=auth_headers).status_code == 401


# ---------------------------------------------------------------------------
# Security primitives
# ---------------------------------------------------------------------------


def test_same_password_produces_different_hashes():
    """Per-password salting: identical passwords must not collide in the table."""
    first = hash_password("identical-password")
    second = hash_password("identical-password")

    assert first != second
    assert verify_password("identical-password", first)
    assert verify_password("identical-password", second)


def test_verify_password_rejects_a_non_bcrypt_value():
    """A row hand-inserted with a plaintext password is a failed login, not a 500."""
    assert verify_password("anything", "not-a-bcrypt-hash") is False


def test_password_over_bcrypt_limit_is_rejected():
    """bcrypt truncates at 72 bytes; silently ignoring the tail would be worse."""
    with pytest.raises(ValueError):
        hash_password("x" * 73)


def test_decode_rejects_a_tampered_token():
    token = create_access_token(subject=1)
    tampered = token[:-3] + ("aaa" if not token.endswith("aaa") else "bbb")
    assert decode_access_token(tampered) is None


def test_role_defaults_to_hearing(client):
    response = client.post(
        "/api/auth/register",
        json={"name": "No Role", "email": "norole@example.com", "password": "password123"},
    )
    assert response.status_code == 201
    assert response.json()["user"]["role"] == UserRole.HEARING.value
