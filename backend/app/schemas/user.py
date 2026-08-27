"""Pydantic schemas for users and authentication.

These classes are the *wire contract*. Keeping them separate from the ORM
models is what guarantees `password_hash` can never leak into a JSON response —
there is simply no field for it to travel in.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.user import UserRole


class UserRegister(BaseModel):
    """Request body for POST /api/auth/register."""

    name: str = Field(min_length=1, max_length=120, examples=["Swarna Rathna A"])

    # EmailStr rejects malformed addresses before any database work happens.
    email: EmailStr = Field(examples=["swarna@example.com"])

    # 8 characters is the floor; 72 bytes is bcrypt's hard truncation limit, so
    # the schema refuses longer input rather than silently ignoring the tail.
    password: str = Field(min_length=8, max_length=72, examples=["strongpassword123"])

    role: UserRole = Field(
        default=UserRole.HEARING,
        description="'deaf' or 'hearing' — selects which side of the meeting UI you get.",
    )


class UserLogin(BaseModel):
    """Request body for the JSON login endpoint."""

    email: EmailStr
    password: str


class UserPublic(BaseModel):
    """Everything the API is willing to say about a user.

    Note what is absent: `password_hash`. That omission is the security
    boundary, and it is enforced by this class existing rather than by
    remembering to strip a field in every endpoint.
    """

    # from_attributes lets FastAPI build this straight from a SQLAlchemy row.
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: EmailStr
    role: UserRole
    created_at: datetime


class Token(BaseModel):
    """Response body for POST /api/auth/login.

    `token_type` is always "bearer"; it is part of the OAuth2 password-flow
    contract that Swagger UI and most HTTP clients expect.
    """

    access_token: str
    token_type: str = "bearer"
    expires_in: int = Field(description="Token lifetime in seconds.")
    user: UserPublic
