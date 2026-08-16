"""WebSocket endpoint: hand landmarks in, recognised text out.

    WS /ws/predict/{meeting_code}?token=<jwt>

WHAT CROSSES THIS SOCKET
------------------------
Coordinates. Twenty-one (x, y, z) triples per hand — about 500 bytes a frame,
roughly 5 KB/s at our 10 FPS send rate. **No video frame ever travels this
socket**, and there is no code path here that could accept one. MediaPipe runs
in the browser, so the user's camera feed never leaves their machine.

That is the central privacy claim of BridgeTalk's architecture, and this file is
where it is either true or not. It is true.

WHY THE TOKEN IS IN THE QUERY STRING
------------------------------------
The browser WebSocket API cannot set an Authorization header — the constructor
takes a URL and nothing else. The options are a query parameter, a cookie, or a
first message containing the token. We use a query parameter, which is standard
practice, with one caveat worth knowing: query strings appear in server access
logs in a way headers do not. On a locally-hosted project that is acceptable;
in production it would argue for short-lived, single-use socket tickets.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from app.core.security import decode_access_token
from app.database import SessionLocal
from app.ml.normalization import normalize_primary_hand
from app.ml.predictor import ModelNotLoadedError, predictor
from app.ml.smoothing import NEUTRAL_LABEL, PredictionSmoother
from app.models.meeting import Meeting
from app.models.user import User
from app.ws.connection_manager import inference_manager

logger = logging.getLogger("bridgetalk.ws.inference")

router = APIRouter()

# WebSocket close codes. 1008 is "policy violation", the conventional code for
# an authentication failure, and 1011 is "internal error".
WS_POLICY_VIOLATION = 1008
WS_INTERNAL_ERROR = 1011


def _authenticate(token: str) -> User | None:
    """Resolve a JWT from the query string into a User.

    Uses its own short-lived session rather than the request-scoped `get_db`
    dependency: a WebSocket lives for minutes or hours, and holding a database
    connection open for that whole time would exhaust the pool with a handful
    of participants.
    """
    payload = decode_access_token(token)
    if payload is None:
        return None

    subject = payload.get("sub")
    if subject is None:
        return None

    try:
        user_id = int(subject)
    except (TypeError, ValueError):
        return None

    with SessionLocal() as session:
        return session.get(User, user_id)


def _meeting_exists(meeting_code: str) -> bool:
    """Check the meeting is real before accepting a socket for it."""
    with SessionLocal() as session:
        meeting = session.scalar(
            select(Meeting).where(Meeting.code == meeting_code.strip().upper())
        )
        return meeting is not None and meeting.ended_at is None


def _error(code: str, message: str) -> dict[str, Any]:
    return {"type": "error", "code": code, "message": message}


@router.websocket("/ws/predict/{meeting_code}")
async def predict_socket(
    websocket: WebSocket,
    meeting_code: str,
    token: str = Query(..., description="JWT from POST /api/auth/login"),
) -> None:
    """Stream landmarks in, stream predictions out."""

    # --- authenticate ---------------------------------------------------------
    # The handshake is completed FIRST, then the socket is closed with an
    # application close code if authentication fails.
    #
    # Rejecting before accepting is the tempting alternative, but Starlette
    # turns that into a plain HTTP 403 and the browser reports a generic
    # code 1006 ("abnormal closure") — indistinguishable from the server being
    # down. The client then retries a bad token twelve times with backoff.
    # Accepting first lets us send code 1008 with a reason the UI can act on,
    # and the socket is closed immediately, so nothing useful is exposed.
    user = _authenticate(token)
    if user is None:
        await websocket.accept()
        await websocket.send_json(
            _error("UNAUTHORIZED", "Invalid or expired token — please log in again")
        )
        await websocket.close(code=WS_POLICY_VIOLATION, reason="Invalid or expired token")
        return

    normalized_code = meeting_code.strip().upper()

    # A "DEMO" code is allowed so the sign-detection panel can be exercised
    # without first creating a meeting. It is still authenticated — it skips
    # the meeting lookup, not the token check.
    if normalized_code != "DEMO" and not _meeting_exists(normalized_code):
        await websocket.accept()
        await websocket.send_json(
            _error("MEETING_NOT_FOUND", f"No active meeting with code {normalized_code}")
        )
        await websocket.close(
            code=WS_POLICY_VIOLATION, reason="No such meeting, or it has ended"
        )
        return

    connection = await inference_manager.connect(
        websocket, normalized_code, user.id, user.name
    )

    # One smoother per connection. Sharing state between two people signing at
    # once would interleave their letters into a single sentence.
    smoother = PredictionSmoother()
    connection.state["smoother"] = smoother

    # Tell the client what it is connected to, so the UI can show model status
    # rather than silently producing nothing when no model is loaded.
    await inference_manager.send_personal(
        connection,
        {
            "type": "connected",
            "meeting_code": normalized_code,
            "user": {"id": user.id, "name": user.name},
            "model": predictor.describe(),
            "config": {
                "confidence_threshold": smoother.config.confidence_threshold,
                "majority_window": smoother.config.majority_window,
                "majority_min": smoother.config.majority_min,
                "cooldown_ms": smoother.config.cooldown_ms,
            },
        },
    )

    if not predictor.is_loaded:
        await inference_manager.send_personal(
            connection,
            _error(
                "MODEL_NOT_LOADED",
                predictor.load_error or "No sign model is loaded on the server",
            ),
        )

    try:
        while True:
            message = await websocket.receive_json()
            message_type = message.get("type")

            # --- UI controls ---------------------------------------------
            if message_type == "clear":
                smoother.clear()
                await inference_manager.send_personal(
                    connection, {"type": "sentence", "sentence": ""}
                )
                continue

            if message_type == "backspace":
                await inference_manager.send_personal(
                    connection, {"type": "sentence", "sentence": smoother.backspace()}
                )
                continue

            if message_type == "ping":
                await inference_manager.send_personal(connection, {"type": "pong"})
                continue

            if message_type != "landmarks":
                await inference_manager.send_personal(
                    connection,
                    _error("INVALID_MESSAGE", f"Unknown message type: {message_type!r}"),
                )
                continue

            # --- the actual work ------------------------------------------
            received_at = time.perf_counter()
            hands = message.get("hands") or []

            # No hand in frame. This is the neutral state, and it is resolved
            # WITHOUT calling the model — there are no landmarks to classify.
            # It is also why 'nothing' is not a trained class: see
            # ml/models/dataset_manifest.json.
            if not hands:
                result = smoother.push(None, 0.0)
                await inference_manager.send_personal(
                    connection,
                    {
                        "type": "prediction",
                        "label": NEUTRAL_LABEL,
                        "confidence": 0.0,
                        "stable": False,
                        "sentence": result.sentence,
                        "hand_detected": False,
                        "latency_ms": round((time.perf_counter() - received_at) * 1000, 1),
                    },
                )
                continue

            try:
                features = normalize_primary_hand(hands)
            except (ValueError, TypeError) as exc:
                await inference_manager.send_personal(
                    connection, _error("INVALID_MESSAGE", f"Bad landmark data: {exc}")
                )
                continue

            try:
                label, confidence, _ = predictor.predict(features)
            except ModelNotLoadedError as exc:
                await inference_manager.send_personal(
                    connection, _error("MODEL_NOT_LOADED", str(exc))
                )
                continue
            except ValueError as exc:
                await inference_manager.send_personal(
                    connection, _error("INVALID_MESSAGE", str(exc))
                )
                continue

            result = smoother.push(label, confidence)
            latency_ms = round((time.perf_counter() - received_at) * 1000, 1)

            await inference_manager.send_personal(
                connection,
                {
                    "type": "prediction",
                    "label": result.label,
                    "confidence": round(result.confidence, 4),
                    "stable": result.stable,
                    "emitted": result.emitted,
                    "sentence": result.sentence,
                    "hand_detected": True,
                    # Server receive-to-send time. Surfacing a real number the
                    # UI can display is worth a lot in a review — it turns
                    # "it feels fast" into "38 milliseconds".
                    "latency_ms": latency_ms,
                },
            )

            # --- broadcast to the other participant ------------------------
            # Only accepted letters are broadcast, never per-frame flicker, so
            # the other person's subtitle updates when something was actually
            # recognised rather than 10 times a second.
            if result.emitted is not None and normalized_code != "DEMO":
                await inference_manager.broadcast(
                    normalized_code,
                    {
                        "type": "subtitle",
                        "from": {"id": user.id, "name": user.name},
                        "source": "sign",
                        "text": result.sentence,
                        "emitted": result.emitted,
                        "confidence": round(result.confidence, 4),
                    },
                    exclude=connection,
                )

    except WebSocketDisconnect:
        # Normal: the tab closed or the user left the meeting.
        pass
    except Exception:  # noqa: BLE001
        logger.exception("Inference socket failed for %s", user.name)
        try:
            await websocket.close(code=WS_INTERNAL_ERROR)
        except RuntimeError:
            # Already closed — nothing to do.
            pass
    finally:
        await inference_manager.disconnect(connection)
