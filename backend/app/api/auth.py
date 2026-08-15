"""Authentication endpoints: register, login, me."""

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select

from app.config import settings
from app.core.deps import CurrentUser, DbSession
from app.core.security import create_access_token, hash_password, verify_password
from app.models.user import User
from app.schemas.user import Token, UserLogin, UserPublic, UserRegister

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _build_token_response(user: User) -> Token:
    """Issue a JWT for `user` and wrap it in the standard login response.

    Shared by register and login so a newly registered user is logged in
    immediately, and so both paths cannot drift apart.
    """
    access_token = create_access_token(subject=user.id)
    return Token(
        access_token=access_token,
        token_type="bearer",
        expires_in=settings.access_token_expire_minutes * 60,
        user=UserPublic.model_validate(user),
    )


@router.post(
    "/register",
    response_model=Token,
    status_code=status.HTTP_201_CREATED,
    summary="Create an account and receive a token",
)
def register(payload: UserRegister, db: DbSession) -> Token:
    """Create a user, then log them straight in.

    Returning a token here rather than making the client immediately call
    /login removes a round trip and a whole class of "registered but the login
    request failed" states from the frontend.
    """
    # Emails are matched case-insensitively by normalising on the way in.
    # Without this, alice@x.com and Alice@X.com become two separate accounts
    # and the user cannot work out why their password "stopped working".
    email = payload.email.strip().lower()

    existing = db.scalar(select(User).where(User.email == email))
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists",
        )

    user = User(
        name=payload.name.strip(),
        email=email,
        password_hash=hash_password(payload.password),
        role=payload.role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)  # populate server-generated id and created_at

    return _build_token_response(user)


@router.post("/login", response_model=Token, summary="Exchange credentials for a token")
def login(
    db: DbSession,
    form_data: OAuth2PasswordRequestForm = Depends(),
) -> Token:
    """OAuth2 password-flow login (form-encoded).

    This form-encoded shape is what Swagger UI's "Authorize" button posts, so
    using it means /docs can authenticate and exercise the protected endpoints
    without any extra work. The OAuth2 spec names the identifier field
    `username`; we put the email in it.

    A JSON-friendly equivalent lives at /login/json for the React client.
    """
    return _authenticate(db, form_data.username, form_data.password)


@router.post("/login/json", response_model=Token, summary="Log in with a JSON body")
def login_json(payload: UserLogin, db: DbSession) -> Token:
    """Same authentication, JSON body — what the frontend actually calls."""
    return _authenticate(db, payload.email, payload.password)


def _authenticate(db: DbSession, email: str, password: str) -> Token:
    """Verify credentials or raise 401.

    The error message is deliberately identical for "no such email" and "wrong
    password". Distinguishing them would let anyone probe which email addresses
    have accounts here — a real privacy leak for a platform whose users are
    identifiable by disability.
    """
    user = db.scalar(select(User).where(User.email == email.strip().lower()))

    if user is None or not verify_password(password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return _build_token_response(user)


@router.get("/me", response_model=UserPublic, summary="Profile of the current user")
def read_current_user(current_user: CurrentUser) -> UserPublic:
    """Return the caller's own profile.

    The frontend calls this on page load to decide whether a stored token is
    still valid — a 401 here means "log in again".
    """
    return UserPublic.model_validate(current_user)
