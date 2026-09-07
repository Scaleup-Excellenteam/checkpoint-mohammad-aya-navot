"""Terminal chat client.

Sign up/login with JSON, then send plain text in response to the server's
lounge prompts. In a room, quit returns to the lounge. Ctrl+C exits.
Run from the project root: python -m client.client
"""

import asyncio
import getpass
import json
import logging
import re
import sys
import websockets

from config import (
    CLIENT_LOG_PATH, LOG_FORMAT, LOG_LEVEL, RECONNECT_BACKOFF_MULTIPLIER,
    RECONNECT_INITIAL_DELAY, RECONNECT_MAX_DELAY, SERVER_URL,
)
from protocol.models import Message, MessageType
from protocol.protocol import make_signup, make_login

# ---------------------------------------------------------------------------
# Logging - file + console, password always redacted
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=LOG_LEVEL,
    format=LOG_FORMAT,
    handlers=[
        logging.FileHandler(CLIENT_LOG_PATH),
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


async def receive_loop(ws):
    async for text in ws:
        print(f"\n{text}\n> ", end="", flush=True)


class UserQuit(Exception):
    """Raised when the user chooses not to continue logging in."""


async def send_loop(ws):
    while True:
        text = await asyncio.to_thread(input, "> ")
        await ws.send(text)


# ---------------------------------------------------------------------------
# One full connect-login-join-chat session. Raises on disconnect so the
# outer reconnect loop can retry.
# ---------------------------------------------------------------------------
async def wait_for_response(ws) -> Message:
    """
    Waits for exactly one message and parses it. Used ONLY during the
    authentication phase (SIGNUP/LOGIN), before receive_loop starts
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

        # After login, the server guides lounge selection and room chat.
        await asyncio.gather(receive_loop(ws), send_loop(ws))


async def main():
    server_url = sys.argv[1] if len(sys.argv) > 1 else SERVER_URL

    retry_delay = RECONNECT_INITIAL_DELAY
    max_retry_delay = RECONNECT_MAX_DELAY

    def reset_delay():
        nonlocal retry_delay
        retry_delay = RECONNECT_INITIAL_DELAY

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
            retry_delay = min(retry_delay * RECONNECT_BACKOFF_MULTIPLIER, max_retry_delay)
            continue


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nBye.")
