"""
TSPO Chat - Client (Day 1, full-featured)

Flow:
  1. Connect to server (auto-reconnects with backoff if the connection drops)
  2. SIGNUP (optional) then LOGIN - each step waits for the server's real
     ACK/ERROR response before proceeding to the next (no fixed delays/guessing)
  3. JOIN a room - also waits for real confirmation before proceeding
  4. Send/receive CHAT messages concurrently
  5. Commands: /join <room>, /leave, /quit - /join and /leave wait for the
     server's ACK/ERROR (via a correlated pending-future) before updating
     local room state, instead of assuming success optimistically
  6. Client-side validation before sending (empty / too long / control chars)
  7. All events logged to client.log - password is ALWAYS redacted (even a
     best-effort regex fallback for malformed/unparseable messages), never
     written in plaintext to any log line
  8. Password entry uses getpass (not shown on screen while typing)

Known, accepted limitations (documented, not silently ignored):
  - If the server connection drops while send_loop is blocked waiting on
    input() (which runs in a separate OS thread via asyncio.to_thread),
    asyncio.gather() will NOT reconnect immediately: gather() only returns
    once ALL of its tasks finish, and a blocking input() call in a thread
    cannot be cancelled by asyncio. In practice, reconnection is delayed
    until the user's next keystroke/Enter. A full fix would require a
    non-blocking stdin reader (e.g. a dedicated async input library) - out
    of scope for Day 1.

Requires: pip install websockets
Requires: the protocol/ package (models.py + protocol.py) importable from
the project root - shared contract with server/identity code

Usage:
    python -m client.client ws://<server-ip>:9090/messanger
"""

import asyncio
import getpass
import json
import logging
import re
import sys
import websockets

from protocol.models import Message, MessageType
from protocol.protocol import (
    make_signup,
    make_login,
    make_join,
    make_leave,
    make_chat,
)

# ---------------------------------------------------------------------------
# Logging - file + console, password always redacted
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("client.log"),
        logging.StreamHandler(sys.stderr),  # keep chat prompt on stdout clean
    ],
)
log = logging.getLogger("client")


_PASSWORD_FALLBACK_PATTERN = re.compile(r'("password"\s*:\s*")([^"]*)(")')


def redact_for_log(raw_json: str) -> str:
    """
    Never write a real password to the log file. Parses the JSON, replaces
    the password field if present. If the text isn't valid JSON (malformed
    message), we can't safely parse it - but as a best-effort defensive
    measure, we still scrub anything that LOOKS like a "password": "..."
    fragment before falling back to logging the raw text. This is a
    regex heuristic, not a guarantee - genuinely obfuscated or oddly
    formatted malformed input could still slip through. In practice this
    only matters for RECV logs of malformed *server* messages, and the
    server should never be echoing a password back in the first place.
    """
    try:
        data = json.loads(raw_json)
        if "password" in data:
            data["password"] = "***REDACTED***"
        return json.dumps(data)
    except (json.JSONDecodeError, TypeError):
        return _PASSWORD_FALLBACK_PATTERN.sub(r'\1***REDACTED***\3', raw_json)


# ---------------------------------------------------------------------------
# Client-side input validation - reject bad input BEFORE sending to server
# ---------------------------------------------------------------------------
MAX_MESSAGE_LENGTH = 1000


def validate_chat_text(text: str) -> "tuple[bool, str]":
    """Returns (is_valid, reason_if_not)."""
    if not text.strip():
        return False, "Message is empty"
    if len(text) > MAX_MESSAGE_LENGTH:
        return False, f"Message too long ({len(text)} chars, max {MAX_MESSAGE_LENGTH})"
    # reject control characters (other than normal printable text) - things
    # like raw null bytes or terminal escape sequences shouldn't be sent
    if any(ord(ch) < 32 and ch not in ("\t",) for ch in text):
        return False, "Message contains invalid control characters"
    return True, ""


# ---------------------------------------------------------------------------
# Receiving: parse every incoming message and display it appropriately
# ---------------------------------------------------------------------------
async def receive_loop(ws, state: dict):
    async for raw_message in ws:
        log.info(f"RECV: {redact_for_log(raw_message)}")
        try:
            msg = Message.from_json(raw_message)
        except ValueError as e:
            log.warning(f"could not parse incoming message: {e}")
            print(f"\n[unparseable message from server]\n> ", end="", flush=True)
            continue

        # if send_loop is waiting on a specific ACK/ERROR (e.g. after a
        # /join command), resolve that wait here. receive_loop is the ONLY
        # coroutine reading from the socket, so this is the one place that
        # can safely correlate "a response arrived" with "someone is
        # waiting for one".
        pending = state.get("pending_ack")
        if pending is not None and not pending.done() and msg.type in (MessageType.ACK, MessageType.ERROR):
            pending.set_result(msg)

        if msg.type == MessageType.CHAT:
            line = f"{msg.sender}: {msg.content}"
        elif msg.type == MessageType.SYSTEM:
            line = f"[system] {msg.content}"
        elif msg.type == MessageType.ACK:
            line = f"[ok] {msg.content} succeeded" + (f" (room: {msg.room})" if msg.room else "")
        elif msg.type == MessageType.ERROR:
            line = f"[error] {msg.content}"
        else:
            line = f"[{msg.type.value}] {msg.content}"

        print(f"\n{line}\n> ", end="", flush=True)
    # loop exits naturally when the server closes the connection -
    # caller (session()) is responsible for detecting the disconnect


# ---------------------------------------------------------------------------
# Sending: commands (/join, /leave, /quit) and chat messages
# ---------------------------------------------------------------------------
class UserQuit(Exception):
    """Raised when the user explicitly asks to quit - stops reconnect retries."""


ACK_WAIT_TIMEOUT = 5  # seconds


async def send_and_wait_for_ack(ws, state: dict, raw_json: str, label: str):
    """
    Sends `raw_json`, then waits (up to ACK_WAIT_TIMEOUT seconds) for
    receive_loop to correlate the server's ACK/ERROR response back to us,
    via the shared `state["pending_ack"]` future. Returns the parsed
    Message, or None if we timed out with no response at all.

    This replaces "fire and hope" sending: the caller only updates local
    state (e.g. state["room"]) after actually seeing a real ACK, not
    optimistically before confirmation.
    """
    pending = asyncio.get_event_loop().create_future()
    state["pending_ack"] = pending
    await ws.send(raw_json)
    log.info(f"SENT: {label}")
    try:
        return await asyncio.wait_for(pending, timeout=ACK_WAIT_TIMEOUT)
    except asyncio.TimeoutError:
        print(f"[warning] No response from server for {label} within {ACK_WAIT_TIMEOUT}s")
        log.warning(f"{label} timed out waiting for server response")
        return None
    finally:
        state["pending_ack"] = None


async def send_loop(ws, state: dict):
    """
    `state` is a small shared dict: {"room": str|None, "pending_ack": Future|None}.
    Using a dict (not plain variables) lets this function's changes be
    visible to receive_loop and vice versa, since asyncio tasks can't
    return values to each other mid-run - this is how /join and /leave
    correlate a specific server response back to the command that
    triggered it (see send_and_wait_for_ack).
    """
    while True:
        text = await asyncio.to_thread(input, "> ")
        stripped = text.strip()

        if stripped.lower() in ("/quit", "/exit"):
            if state["room"]:
                await ws.send(make_leave(state["room"]))
            await ws.close()
            raise UserQuit()

        if stripped.lower() == "/leave":
            if not state["room"]:
                print("[info] You are not in a room.")
                continue
            resp = await send_and_wait_for_ack(ws, state, make_leave(state["room"]), "LEAVE")
            if resp is not None and resp.type == MessageType.ACK:
                state["room"] = None
            continue

        if stripped.lower().startswith("/join "):
            new_room = stripped[len("/join "):].strip()
            if not new_room:
                print("[info] Usage: /join <room name>")
                continue
            resp = await send_and_wait_for_ack(ws, state, make_join(new_room), "JOIN")
            if resp is not None and resp.type == MessageType.ACK:
                state["room"] = new_room
            # on ERROR or timeout, state["room"] is left unchanged - no
            # more "optimistic" update before confirmation
            continue

        # plain chat message
        if not state["room"]:
            print("[info] You're not in a room. Use /join <room> first.")
            continue

        is_valid, reason = validate_chat_text(text)
        if not is_valid:
            print(f"[rejected] {reason}")
            continue

        await ws.send(make_chat(state["room"], text))
        log.info(f"SENT: CHAT room={state['room']}")


# ---------------------------------------------------------------------------
# One full connect-login-join-chat session. Raises on disconnect so the
# outer reconnect loop can retry.
# ---------------------------------------------------------------------------
async def wait_for_response(ws) -> Message:
    """
    Waits for exactly one message and parses it. Used ONLY during the
    sequential setup phase (SIGNUP/LOGIN/JOIN), before receive_loop starts
    consuming the socket - at this point we are the single reader, so a
    direct ws.recv() is safe and simple, no correlation needed.
    """
    raw = await ws.recv()
    log.info(f"RECV: {redact_for_log(raw)}")
    return Message.from_json(raw)


async def session(server_url: str, on_connected=None):
    async with websockets.connect(server_url) as ws:
        log.info(f"connected to {server_url}")
        print("Connected.")
        if on_connected:
            on_connected()  # lets the caller reset its reconnect backoff

        username = await asyncio.to_thread(input, "Username: ")
        password = await asyncio.to_thread(getpass.getpass, "Password: ")

        has_account = await asyncio.to_thread(input, "Do you already have an account? (y/n): ")
        if has_account.strip().lower() not in ("y", "yes"):
            await ws.send(make_signup(username, password))
            log.info(f"SENT: SIGNUP username={username}")  # never log password itself
            resp = await wait_for_response(ws)
            if resp.type == MessageType.ERROR:
                # not necessarily fatal (e.g. "username already exists") -
                # we still try to log in with the same credentials below
                print(f"[error] {resp.content}")
            else:
                print(f"[ok] SIGNUP succeeded")

        # LOGIN - wait for the actual ACK/ERROR before doing anything else.
        # This fixes the ordering bug: previously JOIN could be sent before
        # the server had confirmed LOGIN at all.
        while True:
            await ws.send(make_login(username, password))
            log.info(f"SENT: LOGIN username={username}")  # never log password itself
            resp = await wait_for_response(ws)
            if resp.type == MessageType.ACK:
                print("[ok] LOGIN succeeded")
                break
            print(f"[error] {resp.content}")
            retry = await asyncio.to_thread(input, "Try login again? (y/n): ")
            if retry.strip().lower() not in ("y", "yes"):
                raise UserQuit()
            username = await asyncio.to_thread(input, "Username: ")
            password = await asyncio.to_thread(getpass.getpass, "Password: ")

        # JOIN - same pattern: wait for real confirmation before proceeding
        while True:
            room = await asyncio.to_thread(input, "Room to join: ")
            await ws.send(make_join(room))
            log.info(f"SENT: JOIN room={room}")
            resp = await wait_for_response(ws)
            if resp.type == MessageType.ACK:
                print(f"[ok] JOIN succeeded (room: {room})")
                break
            print(f"[error] {resp.content}")

        # Only now, with LOGIN and JOIN both confirmed, do we start the
        # concurrent phase: receive_loop consuming the socket continuously,
        # and send_loop handling further user input/commands.
        state = {"room": room, "pending_ack": None}
        print(f"Type a message and press Enter. Commands: /join <room>, /leave, /quit\n")

        receiver_task = asyncio.create_task(receive_loop(ws, state))
        await asyncio.gather(
            receiver_task,
            send_loop(ws, state),
        )


async def main():
    server_url = sys.argv[1] if len(sys.argv) > 1 else "ws://localhost:9090/messanger"

    retry_delay = 1
    max_retry_delay = 30

    def reset_delay():
        nonlocal retry_delay
        retry_delay = 1

    while True:
        try:
            print(f"Connecting to {server_url} ...")
            await session(server_url, on_connected=reset_delay)
            break  # session() only returns normally if gather() finished cleanly

        except UserQuit:
            print("Bye.")
            break

        except (websockets.exceptions.ConnectionClosed, ConnectionRefusedError, OSError) as e:
            log.warning(f"disconnected/failed to connect ({e}); retrying in {retry_delay}s")
            print(f"\n[connection lost - retrying in {retry_delay}s. Ctrl+C to give up]")
            await asyncio.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, max_retry_delay)
            continue


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nBye.")