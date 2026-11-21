"""WebSocket endpoint (/api/ws): initial snapshot, then periodic/coalesced pushes."""
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

import auth
from netvision import ws

router = APIRouter()


@router.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    # The HTTP auth middleware does not run for WebSockets (issue #2).
    # Browsers cannot set headers on a WebSocket, so the token comes as ?token=.
    if auth.AUTH_ENABLED:
        token = websocket.query_params.get("token")
        if not (token and auth.verify_token(token)):
            await websocket.close(code=1008)  # policy violation -> handshake rejected
            return
    await ws.ws_manager.connect(websocket)
    try:
        # send an initial snapshot
        snap = await ws._build_snapshot()
        await websocket.send_text(json.dumps(snap, default=str))
        while True:
            # keep connection alive; ignore incoming messages
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws.ws_manager.disconnect(websocket)
    except Exception:
        ws.ws_manager.disconnect(websocket)
