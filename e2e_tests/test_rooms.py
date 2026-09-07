import asyncio
import unittest

import websockets

from e2e_tests.common import (
    WS_URL,
    receive_text,
    signup_and_login,
    unique_room,
)


async def create_room(websocket, room_name):
    """
    Assumes the client is logged in and currently in the lounge.
    """

    await websocket.send("/create")

    prompt = await receive_text(websocket)

    if "name" not in prompt.lower():
        raise AssertionError(
            f"Expected room-name prompt, got: {prompt}"
        )

    await websocket.send(room_name)

    joined_message = await receive_text(websocket)
    instructions = await receive_text(websocket)

    return joined_message, instructions


async def join_room(websocket, room_name):
    """
    Assumes the client is logged in and currently in the lounge.
    """

    await websocket.send(room_name)

    joined_message = await receive_text(websocket)
    instructions = await receive_text(websocket)

    return joined_message, instructions


class RoomE2ETests(unittest.IsolatedAsyncioTestCase):

    async def test_create_room_and_leave(self):
        room_name = unique_room("create_leave")

        async with websockets.connect(WS_URL) as websocket:

            username, _, lounge = await signup_and_login(websocket)

            self.assertIn(
                "Rooms:",
                lounge,
            )

            joined, instructions = await create_room(
                websocket,
                room_name,
            )

            self.assertIn(
                username,
                joined,
            )

            self.assertIn(
                "joined",
                joined.lower(),
            )

            self.assertIn(
                "quit",
                instructions.lower(),
            )

            # Leave the room
            await websocket.send("quit")

            # Server should return the client to the lounge
            lounge_again = await receive_text(websocket)

            self.assertIn(
                "Rooms:",
                lounge_again,
            )

            self.assertIn(
                room_name,
                lounge_again,
            )

    async def test_message_is_delivered_to_same_room(self):
        room_name = unique_room("delivery")

        async with websockets.connect(WS_URL) as alice_socket:
            async with websockets.connect(WS_URL) as bob_socket:

                alice, _, _ = await signup_and_login(
                    alice_socket
                )

                bob, _, _ = await signup_and_login(
                    bob_socket
                )

                await create_room(
                    alice_socket,
                    room_name,
                )

                await join_room(
                    bob_socket,
                    room_name,
                )

                # Alice receives notification that Bob joined.
                bob_joined_notification = await receive_text(
                    alice_socket
                )

                self.assertIn(
                    bob,
                    bob_joined_notification,
                )

                test_message = "hello-from-e2e-test"

                await alice_socket.send(
                    test_message
                )

                alice_received = await receive_text(
                    alice_socket
                )

                bob_received = await receive_text(
                    bob_socket
                )

                self.assertIn(
                    alice,
                    alice_received,
                )

                self.assertIn(
                    test_message,
                    alice_received,
                )

                self.assertIn(
                    alice,
                    bob_received,
                )

                self.assertIn(
                    test_message,
                    bob_received,
                )

    async def test_room_isolation(self):
        room_one = unique_room("room_one")
        room_two = unique_room("room_two")

        async with websockets.connect(WS_URL) as alice_socket:
            async with websockets.connect(WS_URL) as bob_socket:
                async with websockets.connect(WS_URL) as outsider_socket:

                    alice, _, _ = await signup_and_login(
                        alice_socket
                    )

                    _, _, _ = await signup_and_login(
                        bob_socket
                    )

                    _, _, _ = await signup_and_login(
                        outsider_socket
                    )

                    # Alice creates room 1.
                    await create_room(
                        alice_socket,
                        room_one,
                    )

                    # Bob joins room 1.
                    await join_room(
                        bob_socket,
                        room_one,
                    )

                    # Alice receives Bob's join notification.
                    await receive_text(
                        alice_socket
                    )

                    # Outsider creates a completely different room.
                    await create_room(
                        outsider_socket,
                        room_two,
                    )

                    secret_message = "room-one-only-message"

                    await alice_socket.send(
                        secret_message
                    )

                    alice_received = await receive_text(
                        alice_socket
                    )

                    bob_received = await receive_text(
                        bob_socket
                    )

                    self.assertIn(
                        secret_message,
                        alice_received,
                    )

                    self.assertIn(
                        secret_message,
                        bob_received,
                    )

                    # Outsider is in room 2 and should receive nothing.
                    with self.assertRaises(asyncio.TimeoutError):
                        await asyncio.wait_for(
                            outsider_socket.recv(),
                            timeout=0.5,
                        )


if __name__ == "__main__":
    unittest.main()