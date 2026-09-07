import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import WebSocketDisconnect
from protocol.models import Message, MessageType, Room, User
from protocol.protocol import make_chat, make_join, make_leave, make_login, make_signup

# Keep the server's startup database initialization out of the working tree.
import sqlite3
_original_connect = sqlite3.connect
with tempfile.TemporaryDirectory() as directory:
    with patch('sqlite3.connect', side_effect=lambda _: _original_connect(Path(directory) / 'users.db')):
        from server import server


class Socket:
    def __init__(self, incoming=()):
        self.incoming = iter(incoming)
        self.messages = []

    async def accept(self):
        pass

    async def receive_text(self):
        try:
            return next(self.incoming)
        except StopIteration:
            raise WebSocketDisconnect()

    async def send_text(self, raw):
        self.messages.append(raw)


class ContractTests(unittest.TestCase):
    def test_roundtrip(self):
        for raw in (make_signup('alice', 'pw'), make_login('alice', 'pw'),
                    make_join('a'), make_leave('a'), make_chat('a', '')):
            message = Message.from_json(raw)
            self.assertEqual(Message.from_json(message.to_json()), message)

    def test_invalid_fields(self):
        for payload in ({'type': []}, {'type': 'JOIN', 'room': None},
                        {'type': 'JOIN', 'room': ' '},
                        {'type': 'LOGIN', 'username': None, 'password': 'pw'},
                        {'type': 'CHAT', 'room': 'a', 'content': 42}):
            with self.assertRaises(ValueError):
                Message.from_json(json.dumps(payload))


class RoomTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        server.rooms.clear()

    async def test_lounge_lists_rooms_and_rejects_unknown_room(self):
        server.rooms['one'] = Room('one')
        socket = Socket(['missing', 'one'])
        room = await server.room_lounge(socket)
        self.assertIs(room, server.rooms['one'])
        self.assertIn('one', socket.messages[0])
        self.assertEqual(socket.messages[1], "server : Room does not exist.")
        self.assertNotIn('missing', server.rooms)

    async def test_lounge_creates_room_and_rejects_duplicates(self):
        existing = Room('one')
        server.rooms['one'] = existing
        socket = Socket(['/create', 'one', '/create', 'two'])
        room = await server.room_lounge(socket)
        self.assertIs(server.rooms['one'], existing)
        self.assertIs(room, server.rooms['two'])
        self.assertIn("server : Room already exists.", socket.messages)

    async def test_chat_isolation_and_quit(self):
        room, other = Room('one'), Room('two')
        peer, outsider = Socket(), Socket()
        await room.add_client(User('bob'), peer)
        await other.add_client(User('carol'), outsider)
        peer.messages.clear()
        outsider.messages.clear()
        alice = User('alice')
        socket = Socket(['hello', '/join two', 'quit'])
        await server.room_chat(socket, alice, room)
        self.assertEqual(peer.messages, [
            'server : alice has joined', 'alice : hello', 'alice : /join two',
            'server : alice has left',
        ])
        self.assertEqual(outsider.messages, [])
        self.assertIsNone(alice.current_room)
        self.assertNotIn(socket, room.connected_clients)

    async def test_manager_auth_lounge_return_and_disconnect(self):
        socket = Socket([make_join('one'), make_login('alice', 'pw'),
                         '/create', 'one', 'hello', 'quit', 'one', 'again'])
        with patch.object(server, 'login', return_value=(True, 'Login successful.')):
            await server.websocket_manager(socket)
        self.assertEqual(Message.from_json(socket.messages[0]).code, 'AUTH_MESSAGE_REQUIRED')
        self.assertEqual(Message.from_json(socket.messages[1]).content, 'LOGIN')
        lounges = [m for m in socket.messages if m.startswith('Rooms:')]
        self.assertEqual(len(lounges), 2)
        self.assertIn('one', lounges[1])
        chats = [m for m in socket.messages if m.startswith('alice : ')]
        self.assertEqual(chats, ['alice : hello', 'alice : again'])
        self.assertEqual(server.rooms['one'].connected_clients, {})

    async def test_failed_socket_does_not_interrupt_broadcast(self):
        class BrokenSocket(Socket):
            async def send_text(self, raw):
                raise WebSocketDisconnect()
        room = Room('one')
        dead, live = BrokenSocket(), Socket()
        user = User('dead', current_room='one')
        room.connected_clients = {dead: user, live: User('live', current_room='one')}
        await room.broadcast('alice : hello')
        self.assertEqual(live.messages[-1], 'alice : hello')
        self.assertNotIn(dead, room.connected_clients)
        self.assertIsNone(user.current_room)


if __name__ == '__main__':
    unittest.main()
