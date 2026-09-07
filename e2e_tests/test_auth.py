import json
import unittest

import websockets

from e2e_tests.common import (
    DEFAULT_PASSWORD,
    WS_URL,
    login,
    receive_json,
    receive_text,
    signup,
    unique_username,
)


class AuthenticationE2ETests(unittest.IsolatedAsyncioTestCase):

    async def test_signup_success(self):
        username = unique_username("signup")

        async with websockets.connect(WS_URL) as websocket:

            response = await signup(
                websocket,
                username,
                DEFAULT_PASSWORD,
            )

            self.assertEqual(
                response.get("type"),
                "ACK",
            )

            self.assertEqual(
                response.get("content"),
                "SIGNUP",
            )

    async def test_duplicate_username_is_rejected(self):
        username = unique_username("duplicate")

        async with websockets.connect(WS_URL) as websocket:

            first_response = await signup(
                websocket,
                username,
                DEFAULT_PASSWORD,
            )

            self.assertEqual(
                first_response.get("type"),
                "ACK",
            )

            second_response = await signup(
                websocket,
                username,
                DEFAULT_PASSWORD,
            )

            self.assertEqual(
                second_response.get("type"),
                "ERROR",
            )

            self.assertIn(
                "already exists",
                second_response.get("content", "").lower(),
            )

    async def test_wrong_password_is_rejected(self):
        username = unique_username("wrong_password")

        async with websockets.connect(WS_URL) as websocket:

            signup_response = await signup(
                websocket,
                username,
                DEFAULT_PASSWORD,
            )

            self.assertEqual(
                signup_response.get("type"),
                "ACK",
            )

            login_response = await login(
                websocket,
                username,
                "DefinitelyWrongPassword",
            )

            self.assertEqual(
                login_response.get("type"),
                "ERROR",
            )

            self.assertIn(
                "wrong username or password",
                login_response.get("content", "").lower(),
            )

    async def test_login_success(self):
        username = unique_username("login")

        async with websockets.connect(WS_URL) as websocket:

            signup_response = await signup(
                websocket,
                username,
                DEFAULT_PASSWORD,
            )

            self.assertEqual(
                signup_response.get("type"),
                "ACK",
            )

            login_response = await login(
                websocket,
                username,
                DEFAULT_PASSWORD,
            )

            self.assertEqual(
                login_response.get("type"),
                "ACK",
            )

            self.assertEqual(
                login_response.get("content"),
                "LOGIN",
            )

            lounge = await receive_text(websocket)

            self.assertIn(
                "Rooms:",
                lounge,
            )

    async def test_unauthenticated_user_cannot_join_room(self):
        async with websockets.connect(WS_URL) as websocket:

            await websocket.send(
                json.dumps({
                    "type": "JOIN",
                    "room": "secret-room",
                })
            )

            response = await receive_json(websocket)

            self.assertEqual(
                response.get("type"),
                "ERROR",
            )

            self.assertEqual(
                response.get("code"),
                "AUTH_MESSAGE_REQUIRED",
            )

    async def test_invalid_json_is_rejected(self):
        async with websockets.connect(WS_URL) as websocket:

            await websocket.send(
                "this is definitely not json"
            )

            response = await receive_json(websocket)

            self.assertEqual(
                response.get("type"),
                "ERROR",
            )

            self.assertEqual(
                response.get("code"),
                "INVALID_MESSAGE",
            )


if __name__ == "__main__":
    unittest.main()