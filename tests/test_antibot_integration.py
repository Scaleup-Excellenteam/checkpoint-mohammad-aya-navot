import unittest
from unittest.mock import AsyncMock, patch

from protocol.models import Room, User
from security.antibot import AntiBotDecision, Verdict
from security.dlp_engine import DlpVerdict
from server import server


class Socket:
    def __init__(self, incoming=()):
        self.incoming = iter(incoming)
        self.messages = []

    async def receive_text(self):
        return next(self.incoming)

    async def send_text(self, message):
        self.messages.append(message)


class AntiBotIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def run_chat(self, dlp_action, allowed):
        room = Room('test')
        peer = Socket()
        await room.add_client(User('bob'), peer)
        sender = Socket(['example.com', 'quit'])
        decision = AntiBotDecision(allowed, Verdict.CLEAN if allowed else Verdict.MALICIOUS, 'Antibot blocked')
        with patch.object(server.dlp, 'check_message', return_value=DlpVerdict(dlp_action, 'DLP result')):
            with patch.object(server.antibot, 'check_message', new_callable=AsyncMock, return_value=decision) as check:
                await server.room_chat(sender, User('alice'), room)
        return sender, peer, check

    async def test_allowed_message_reaches_peer(self):
        _, peer, check = await self.run_chat('allow', True)
        check.assert_awaited_once_with('example.com', username='alice')
        self.assertIn('alice : example.com', peer.messages)

    async def test_antibot_block_does_not_reach_peer(self):
        sender, peer, check = await self.run_chat('allow', False)
        check.assert_awaited_once()
        self.assertNotIn('alice : example.com', peer.messages)
        self.assertTrue(any('Antibot blocked' in message for message in sender.messages))

    async def test_dlp_block_skips_antibot(self):
        _, peer, check = await self.run_chat('block', True)
        check.assert_not_awaited()
        self.assertNotIn('alice : example.com', peer.messages)
