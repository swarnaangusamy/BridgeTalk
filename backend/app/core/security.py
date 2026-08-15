"""Password hashing and JWT creation/verification.

Two separate concerns live here on purpose:

* **Hashing** protects passwords *at rest*. If the database leaks, bcrypt makes
  each password expensive to crack rather than instantly readable.
* **JWTs** carry identity *in flight*. The client presents a signed token
  instead of a password on every request, so the password crosses the network
  exactly once, at login.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.config import settings

# bcrypt is deliberately slow. That is the feature: an attacker who steals the
# `users` table can only test a few thousand guesses per second instead of
# billions, which is the difference between a leaked database being a crisis
# and being an inconvenience.
#
# `deprecated="auto"` means that if we ever add a stronger scheme, passlib will
# transparently mark old bcrypt hashes for rehashing on next login.
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# bcrypt truncates silently at 72 bytes. Rejecting longer passwords up front is
# better than accepting one and quietly ignoring everything past character 72,
# which would make "correct horse battery staple…<200 more chars>" equivalent to
# its first 72 characters.
MAX_PASSWORD_BYTES = 72


def hash_password(plain_password: str) -> str:
    """Return the bcrypt hash of a plaintext password.

    The salt is generated per call and stored inside the returned hash string,
    which is why two users with the same password get different hashes.
    """
    if len(plain_password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        raise ValueError(f"Password must be at most {MAX_PASSWORD_BYTES} bytes long")
    return pwd_context.hash(plain_password)


def verify_password(plain_password: str, password_hash: str) -> bool:
    """Check a plaintext password against a stored hash.

    passlib performs a constant-time comparison internally, so this does not
    leak information through how long it takes to fail.
    """
    try:
        return pwd_context.verify(plain_password, password_hash)
    except ValueError:
        # Raised when the stored value is not a valid bcrypt hash at all — for
        # example a row hand-inserted in Workbench with a plaintext password.
        # That is a failed login, not a server error.
        return False


def create_access_token(
    subject: str | int,
    expires_delta: Optional[timedelta] = None,
    extra_claims: Optional[dict[str, Any]] = None,
) -> str:
    """Create a signed JWT identifying `subject` (our user id).

    The token is *signed*, not *encrypted* — anyone can read its contents with
    a base64 decoder. Never put anything secret in the claims. The signature
    only guarantees that the claims have not been altered.
    """
    now = datetime.now(timezone.utc)
    expire = now + (expires_delta or timedelta(minutes=settings.access_token_expire_minutes))

    claims: dict[str, Any] = {
        "sub": str(subject),  # standard claim: who the token is about
        "iat": int(now.timestamp()),  # issued at
        "exp": int(expire.timestamp()),  # expiry — python-jose enforces this
    }
    if extra_claims:
        claims.update(extra_claims)

    return jwt.encode(claims, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> Optional[dict[str, Any]]:
    """Verify a JWT's signature and expiry, returning its claims.

    Returns `None` for anything invalid — bad signature, expired, malformed, or
    signed with a different algorithm. Callers treat `None` as "not
    authenticated" and never need to catch an exception.

    Passing `algorithms=[...]` explicitly is a security requirement, not a
    formality: without it, a decoder can be tricked into accepting a token that
    declares `"alg": "none"` in its own header.
    """
    try:
        return jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except JWTError:
        return None
