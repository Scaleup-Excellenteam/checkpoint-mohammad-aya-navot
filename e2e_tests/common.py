import asyncio
import json
import os
import uuid


HTTP_BASE_URL = os.getenv(
    "E2E_HTTP_URL",
    "http://127.0.0.1:8000"
).rstrip("/")

WS_URL = os.getenv(
    "E2E_WS_URL",
    "ws://127.0.0.1:8000/messanger"
)

DEFAULT_PASSWORD = "TestPassword123!"


def unique_username(prefix="e2e_user"):
    """
    Create a unique username for every test run.

    This prevents tests from failing because a username
    already exists in the SQLite database.
    """
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def unique_room(prefix="e2e_room"):
    """
    Create a unique room name for every test run.
    """
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def signup_message(username, password):
    return json.dumps({
        "type": "SIGNUP",
        "username": username,
        "password": password,
    })


def login_message(username, password):
    return json.dumps({
        "type": "LOGIN",
        "username": username,
        "password": password,
    })


async def receive_json(websocket, timeout=3):
    """
    Receive a WebSocket message and parse it as JSON.
    """
    raw = await asyncio.wait_for(
        websocket.recv(),
        timeout=timeout,
    )

    return json.loads(raw)


async def receive_text(websocket, timeout=3):
    """
    Receive a normal text WebSocket message.
    """
    return await asyncio.wait_for(
        websocket.recv(),
        timeout=timeout,
    )


async def signup(websocket, username, password=DEFAULT_PASSWORD):
    await websocket.send(
        signup_message(username, password)
    )

    return await receive_json(websocket)


async def login(websocket, username, password=DEFAULT_PASSWORD):
    await websocket.send(
        login_message(username, password)
    )

    return await receive_json(websocket)


async def signup_and_login(websocket, username=None, password=DEFAULT_PASSWORD):
    """
    Create a new user, login, and consume the lounge message.

    Returns:
        username, password, lounge_message
    """

    if username is None:
        username = unique_username()

    signup_response = await signup(
        websocket,
        username,
        password,
    )

    if signup_response.get("type") != "ACK":
        raise AssertionError(
            f"Signup failed: {signup_response}"
        )

    login_response = await login(
        websocket,
        username,
        password,
    )

    if login_response.get("type") != "ACK":
        raise AssertionError(
            f"Login failed: {login_response}"
        )

    lounge_message = await receive_text(websocket)

    return username, password, lounge_message