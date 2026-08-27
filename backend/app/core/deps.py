"""Shared FastAPI dependencies.

`get_current_user` is the single gate every protected endpoint passes through.
Centralising it means "who is calling this?" is answered identically everywhere,
and adding, say, a ban check later is a one-line change rather than an audit of
every router.
"""

from typing import Annotated, Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.security import decode_access_token
from app.database import get_db
from app.models.user import User

# `tokenUrl` does not change how tokens are validated — it tells Swagger UI
# where its "Authorize" button should post credentials, which is what makes
# /docs usable for testing protected endpoints by hand.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

CREDENTIALS_EXCEPTION = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    # Required by the HTTP spec on a 401, and it is what tells a browser client
    # that a bearer token is the expected form of authentication.
    headers={"WWW-Authenticate": "Bearer"},
)


def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    """Resolve the bearer token into a real `User` row.

    The database lookup is not redundant with verifying the signature. A token
    stays cryptographically valid until it expires, so without this check a
    deleted user could keep making requests for up to a day.
    """
    payload = decode_access_token(token)
    if payload is None:
        raise CREDENTIALS_EXCEPTION

    subject: Optional[str] = payload.get("sub")
    if subject is None:
        raise CREDENTIALS_EXCEPTION

    try:
        user_id = int(subject)
    except (TypeError, ValueError):
        # A token whose `sub` is not an integer was not issued by us.
        raise CREDENTIALS_EXCEPTION from None

    user = db.get(User, user_id)
    if user is None:
        raise CREDENTIALS_EXCEPTION

    return user


# Type aliases so routers read as `current_user: CurrentUser` rather than
# repeating the full Annotated[...] spelling on every endpoint.
CurrentUser = Annotated[User, Depends(get_current_user)]
DbSession = Annotated[Session, Depends(get_db)]
