"""WebSocket endpoint: WebRTC signalling relay.

    WS /ws/signal/{meeting_code}?token=<jwt>

WHAT SIGNALLING IS, AND WHY A SERVER IS NEEDED AT ALL
-----------------------------------------------------
WebRTC sends audio and video **directly between two browsers**. Our server is
not in that path and never sees a single video frame.

But two browsers behind two different home routers cannot find each other
unaided. Before any media flows they must exchange:

  * an **offer** — "here is the media I want to send, and the codecs I support"
  * an **answer** — the other side's matching description
  * **ICE candidates** — every network address each peer might be reachable on
    (local IP, router's public IP, and so on)

That exchange has a chicken-and-egg problem: they cannot send each other this
information over a connection they have not established yet. So they send it
through a server both are already connected to. That is all signalling is — a
relay for the introduction. Once the peers connect, this socket goes quiet and
the media never touches us.

STUN
----
A browser behind a NAT router does not know its own public address. A STUN
server tells it ("you look like 203.0.113.7:54321"), which it then advertises
as a candidate. We use Google's public STUN servers, configured client-side.

We do **not** run a TURN server. TURN relays media when a direct connection is
impossible — typically behind symmetric NAT or a corporate firewall. Without
one, two peers on such networks will fail to connect. On a college LAN or two
tabs on one laptop this never comes up; across two mobile networks it might.
That limit is documented in the README rather than discovered during a review.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.core.security import decode_access_token
from app.database import SessionLocal
from app.models.user import User
from app.ws.connection_manager import signaling_manager

logger = logging.getLogger("bridgetalk.ws.signaling")

router = APIRouter()

WS_POLICY_VIOLATION = 1008

# Message types relayed verbatim to the other peer. Everything else is
# rejected: this socket is a dumb pipe for a fixed vocabulary, and keeping the
# list closed means a malformed or hostile client cannot use it as a general
# purpose message bus between participants.
RELAYED_TYPES = {"offer", "answer", "ice-candidate", "hangup"}


def _authenticate(token: str) -> User | None:
    payload = decode_access_token(token)
    if payload is None:
        return None
    try:
        user_id = int(payload.get("sub"))
    except (TypeError, ValueError):
        return None
    with SessionLocal() as session:
        return session.get(User, user_id)


@router.websocket("/ws/signal/{meeting_code}")
async def signaling_socket(
    websocket: WebSocket,
    meeting_code: str,
    token: str = Query(..., description="JWT from POST /api/auth/login"),
) -> None:
    user = _authenticate(token)
    if user is None:
        # Accept first, then close with an application code — the browser
        # reports a pre-accept rejection as a generic 1006 that is
        # indistinguishable from the server being down.
        await websocket.accept()
        await websocket.send_json(
            {"type": "error", "code": "UNAUTHORIZED", "message": "Invalid or expired token"}
        )
        await websocket.close(code=WS_POLICY_VIOLATION, reason="Invalid or expired token")
        return

    normalized_code = meeting_code.strip().upper()
    connection = await signaling_manager.connect(
        websocket, normalized_code, user.id, user.name
    )

    existing_peers = await signaling_manager.peers(normalized_code, exclude=connection)

    # Tell the newcomer who is already here. `should_initiate` is the important
    # field: exactly one side must create the offer. If both peers offered
    # simultaneously the negotiation would collide ("glare"), and both would
    # have to back off and retry. The rule is simple and unambiguous — whoever
    # arrives second starts the call, because they are the one who knows
    # somebody is waiting.
    await signaling_manager.send_personal(
        connection,
        {
            "type": "joined",
            "self": {"id": user.id, "name": user.name},
            "peers": [{"id": peer.user_id, "name": peer.user_name} for peer in existing_peers],
            "should_initiate": len(existing_peers) > 0,
        },
    )

    # Let anyone already in the room know somebody arrived.
    await signaling_manager.broadcast(
        normalized_code,
        {"type": "peer-joined", "peer": {"id": user.id, "name": user.name}},
        exclude=connection,
    )

    try:
        while True:
            message: dict[str, Any] = await websocket.receive_json()
            message_type = message.get("type")

            if message_type == "ping":
                await signaling_manager.send_personal(connection, {"type": "pong"})
                continue

            if message_type not in RELAYED_TYPES:
                await signaling_manager.send_personal(
                    connection,
                    {
                        "type": "error",
                        "code": "INVALID_MESSAGE",
                        "message": f"Cannot relay message type {message_type!r}",
                    },
                )
                continue

            # Relay verbatim, stamped with who sent it. The server does not
            # parse SDP or ICE candidates — it has no reason to understand
            # them, and not parsing them means a WebRTC spec change needs no
            # backend change at all.
            delivered = await signaling_manager.broadcast(
                normalized_code,
                {
                    "type": message_type,
                    "from": {"id": user.id, "name": user.name},
                    "payload": message.get("payload"),
                },
                exclude=connection,
            )

            if delivered == 0:
                # Worth telling the sender: an offer nobody received means the
                # UI should say "waiting for the other participant" rather than
                # spinning forever on a call that can never connect.
                await signaling_manager.send_personal(
                    connection,
                    {
                        "type": "no-peers",
                        "message": "Nobody else is in this meeting yet",
                    },
                )

    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001
        logger.exception("Signalling socket failed for %s", user.name)
    finally:
        await signaling_manager.disconnect(connection)
        # Tell the remaining peer so it can tear down the RTCPeerConnection
        # and show "the other participant left" instead of a frozen last frame.
        await signaling_manager.broadcast(
            normalized_code,
            {"type": "peer-left", "peer": {"id": user.id, "name": user.name}},
        )
