"""
TSPO Chat - mock_auth.py (TEMPORARY - for local testing only)

A minimal standalone server that speaks the same protocol.py contract as
the real server, so the client can be developed and tested WITHOUT waiting
on the real server/identity code to be ready.

Supports: SIGNUP, LOGIN, CREATE_ROOM, JOIN, LEAVE, CHAT (broadcast per room).
In-memory only - no persistence, no real security. DO NOT use this as the
final submission - it's a stand-in, meant to be deleted once the real
server/identity teammates have something working.

Requires: pip install websockets
Usage:
    python mock_auth.py
    (listens on ws://0.0.0.0:9090/messanger, matching the real server's address)
"""

import asyncio
import logging
import websockets

from protocol.models import Message, MessageType
from protocol.protocol import (
    make_ack,
    make_error,
    make_system,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("mock_auth")

# in-memory "database" - NOT how the real identity teammate should do it,
# just enough to unblock client testing
USERS = {}  # username -> password (plaintext - mock only!)

# connection state
CONNECTIONS = {}   # websocket -> {"username": str|None, "room": str|None}
ROOMS = {}         # room_name -> set of websockets


async def broadcast(room: str, raw_message: str, exclude=None):
    for ws in ROOMS.get(room, set()):
        if ws is not exclude:
            try:
                await ws.send(raw_message)
            except websockets.exceptions.ConnectionClosed:
                pass


async def handle_client(websocket):
    CONNECTIONS[websocket] = {"username": None, "room": None}
    log.info("client connected")

    try:
        async for raw in websocket:
            state = CONNECTIONS[websocket]
            try:
                msg = Message.from_json(raw)
            except ValueError as e:
                log.warning(f"rejected invalid message: {e}")
                await websocket.send(make_error(str(e)))
                continue

            # ---- SIGNUP ----
            if msg.type == MessageType.SIGNUP:
                if msg.username in USERS:
                    await websocket.send(make_error("Username already exists"))
                else:
                    USERS[msg.username] = msg.password
                    log.info(f"signup: {msg.username}")
                    await websocket.send(make_ack("SIGNUP"))

            # ---- LOGIN ----
            elif msg.type == MessageType.LOGIN:
                if USERS.get(msg.username) == msg.password:
                    state["username"] = msg.username
                    log.info(f"login: {msg.username}")
                    await websocket.send(make_ack("LOGIN"))
                else:
                    log.warning(f"login failed for: {msg.username}")
                    await websocket.send(make_error("Invalid username or password"))

            # ---- JOIN ----
            elif msg.type == MessageType.JOIN:
                if not state["username"]:
                    await websocket.send(make_error("You must log in first"))
                    continue
                ROOMS.setdefault(msg.room, set()).add(websocket)
                state["room"] = msg.room
                log.info(f"{state['username']} joined room '{msg.room}'")
                await websocket.send(make_ack("JOIN", room=msg.room))
                await broadcast(msg.room, make_system(f"{state['username']} joined"), exclude=websocket)

            # ---- LEAVE ----
            elif msg.type == MessageType.LEAVE:
                room = state["room"]
                if room and websocket in ROOMS.get(room, set()):
                    ROOMS[room].discard(websocket)
                    log.info(f"{state['username']} left room '{room}'")
                    await broadcast(room, make_system(f"{state['username']} left"))
                    await websocket.send(make_ack("LEAVE", room=room))
                else:
                    await websocket.send(make_error("You are not in that room"))
                state["room"] = None

            # ---- CHAT ----
            elif msg.type == MessageType.CHAT:
                if not state["username"]:
                    await websocket.send(make_error("You must log in first"))
                    continue
                if state["room"] != msg.room:
                    await websocket.send(make_error("You are not in that room"))
                    continue
                # server overwrites sender - never trust the client's claim
                outgoing = Message(type=MessageType.CHAT, sender=state["username"],
                                    room=msg.room, content=msg.content)
                log.info(f"CHAT [{msg.room}] {state['username']}: {msg.content}")
                await broadcast(msg.room, outgoing.to_json())

            else:
                await websocket.send(make_error(f"Unsupported in mock: {msg.type.value}"))

    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        state = CONNECTIONS.pop(websocket, {})
        room = state.get("room")
        if room and websocket in ROOMS.get(room, set()):
            ROOMS[room].discard(websocket)
        log.info(f"client disconnected (was: {state.get('username')})")


async def main():
    async with websockets.serve(handle_client, "0.0.0.0", 9090):
        log.info("mock_auth server listening on ws://0.0.0.0:9090/messanger")
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())