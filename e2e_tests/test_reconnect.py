import unittest

import websockets

from e2e_tests.common import (
    DEFAULT_PASSWORD,
    WS_URL,
    login,
    receive_text,
    signup,
    unique_username,
)


class ReconnectE2ETests(unittest.IsolatedAsyncioTestCase):

    async def test_user_can_disconnect_and_reconnect(self):
        username = unique_username("reconnect")
        password = DEFAULT_PASSWORD

        # First connection
        async with websockets.connect(WS_URL) as websocket:

            signup_response = await signup(
                websocket,
                username,
                password,
            )

            self.assertEqual(
                signup_response.get("type"),
                "ACK",
            )

            login_response = await login(
                websocket,
                username,
                password,
            )

            self.assertEqual(
                login_response.get("type"),
                "ACK",
            )

            lounge = await receive_text(websocket)

            self.assertIn(
                "Rooms:",
                lounge,
            )

        # At this point the first WebSocket is closed.

        # Second connection
        async with websockets.connect(WS_URL) as websocket:

            login_response = await login(
                websocket,
                username,
                password,
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


if __name__ == "__main__":
    unittest.main()