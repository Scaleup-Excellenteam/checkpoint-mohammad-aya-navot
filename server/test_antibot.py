import importlib
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import WebSocketDisconnect

from protocol.models import Message, MessageType
from protocol.protocol import make_chat, make_join

from server.antibot import (
    AntiBotDecision,
    AntiBotService,
    Indicator,
    ReputationResult,
    Verdict,
    extract_indicators,
    url_to_id,
)


class FakeVirusTotalClient:
    def __init__(self, handler=None):
        self.handler = handler or self._clean
        self.calls = []

    @staticmethod
    def _clean(indicator):
        return ReputationResult(indicator, Verdict.CLEAN, cacheable=True)

    async def lookup(self, indicator):
        self.calls.append(indicator.cache_key)
        return self.handler(indicator)


class FakeWebSocket:
    def __init__(self, incoming):
        self.incoming = list(incoming)
        self.sent = []
        self.accepted = False

    async def accept(self):
        self.accepted = True

    async def receive_text(self):
        if not self.incoming:
            raise WebSocketDisconnect()
        return self.incoming.pop(0)

    async def send_text(self, message):
        self.sent.append(message)


class IndicatorExtractionTests(unittest.TestCase):
    def test_extracts_public_ip(self):
        self.assertIn(
            Indicator("ip", "8.8.8.8"),
            extract_indicators("DNS server: 8.8.8.8"),
        )

    def test_extracts_bare_domain(self):
        self.assertEqual(
            [Indicator("domain", "sub.example.com")],
            extract_indicators("Visit sub.example.com today"),
        )

    def test_extracts_and_normalizes_url(self):
        self.assertEqual(
            [Indicator("url", "https://example.com/path?q=1")],
            extract_indicators("Visit HTTPS://Example.COM:443/path?q=1."),
        )

    def test_extracts_bracketed_ipv6_url(self):
        self.assertEqual(
            [Indicator("url", "http://[::1]")],
            extract_indicators("Local service: http://[::1]"),
        )

    def test_url_id_is_url_safe_and_unpadded(self):
        identifier = url_to_id("https://example.com/path")
        self.assertNotIn("=", identifier)
        self.assertEqual("aHR0cHM6Ly9leGFtcGxlLmNvbS9wYXRo", identifier)


class AntiBotNoIndicatorTests(unittest.IsolatedAsyncioTestCase):
    async def test_message_without_indicators_skips_virus_total(self):
        fake = FakeVirusTotalClient()
        decision = await AntiBotService(fake).check_message("hello everyone")

        self.assertTrue(decision.allowed)
        self.assertEqual(Verdict.NO_INDICATORS, decision.verdict)
        self.assertEqual([], fake.calls)


class ServerIntegrationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        sys.modules.pop("server.server", None)
        with patch("sqlite3.connect"):
            self.server = importlib.import_module("server.server")
        self.server.connected_clients = []
        self.server.authenticate = AsyncMock(return_value="alice")

    def tearDown(self):
        sys.modules.pop("server.server", None)

    async def test_blocked_chat_returns_error_only_to_sender(self):
        websocket = FakeWebSocket([make_chat("room", "bad.example")])
        other_client = AsyncMock()
        self.server.connected_clients.append(other_client)
        self.server.anti_bot = SimpleNamespace(
            check_message=AsyncMock(
                return_value=AntiBotDecision(
                    False,
                    Verdict.MALICIOUS,
                    "Message blocked by Anti-Bot",
                )
            )
        )

        await self.server.websocket_messanger(websocket)

        self.server.anti_bot.check_message.assert_awaited_once_with(
            "bad.example", "alice"
        )
        other_client.send_text.assert_not_awaited()
        self.assertEqual(1, len(websocket.sent))
        response = Message.from_json(websocket.sent[0])
        self.assertEqual(MessageType.ERROR, response.type)
        self.assertEqual("ANTIBOT_BLOCKED", response.code)

    async def test_non_chat_message_skips_antibot_and_uses_existing_path(self):
        raw_join = make_join("room")
        websocket = FakeWebSocket([raw_join])
        other_client = AsyncMock()
        self.server.connected_clients.append(other_client)
        self.server.anti_bot = SimpleNamespace(check_message=AsyncMock())

        await self.server.websocket_messanger(websocket)

        self.server.anti_bot.check_message.assert_not_awaited()
        other_client.send_text.assert_awaited_once_with(f"alice: {raw_join}")


class AntiBotServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_clean_domain_is_allowed(self):
        fake = FakeVirusTotalClient()
        decision = await AntiBotService(fake).check_message("visit example.com")

        self.assertTrue(decision.allowed)
        self.assertEqual(Verdict.CLEAN, decision.verdict)

    async def test_malicious_result_is_blocked(self):
        def malicious(indicator):
            return ReputationResult(
                indicator,
                Verdict.MALICIOUS,
                malicious=5,
                suspicious=1,
                cacheable=True,
            )

        decision = await AntiBotService(
            FakeVirusTotalClient(malicious)
        ).check_message("bad.example")

        self.assertFalse(decision.allowed)
        self.assertEqual(Verdict.MALICIOUS, decision.verdict)
        self.assertIn("5 malicious", decision.reason)

    async def test_suspicious_result_is_blocked(self):
        def suspicious(indicator):
            return ReputationResult(
                indicator,
                Verdict.SUSPICIOUS,
                suspicious=2,
                cacheable=True,
            )

        decision = await AntiBotService(
            FakeVirusTotalClient(suspicious)
        ).check_message("maybe.example")

        self.assertFalse(decision.allowed)
        self.assertEqual(Verdict.SUSPICIOUS, decision.verdict)

    async def test_one_malicious_indicator_blocks_entire_message(self):
        def reputation(indicator):
            verdict = (
                Verdict.MALICIOUS
                if indicator.value == "bad.example"
                else Verdict.CLEAN
            )
            return ReputationResult(
                indicator,
                verdict,
                malicious=1 if verdict == Verdict.MALICIOUS else 0,
                cacheable=True,
            )

        fake = FakeVirusTotalClient(reputation)
        decision = await AntiBotService(fake).check_message(
            "good.example and bad.example"
        )

        self.assertFalse(decision.allowed)
        self.assertEqual(
            [("domain", "good.example"), ("domain", "bad.example")],
            fake.calls,
        )

    async def test_duplicate_indicators_create_one_lookup(self):
        fake = FakeVirusTotalClient()
        decision = await AntiBotService(fake).check_message(
            "https://example.com/path, https://example.com/path and example.com"
        )

        self.assertTrue(decision.allowed)
        self.assertEqual([("url", "https://example.com/path")], fake.calls)

    async def test_cache_prevents_second_lookup(self):
        fake = FakeVirusTotalClient()
        service = AntiBotService(fake)

        await service.check_message("example.com")
        await service.check_message("example.com")

        self.assertEqual([("domain", "example.com")], fake.calls)

    async def test_api_error_allows_message_without_crashing(self):
        def api_error(indicator):
            raise RuntimeError("simulated client failure")

        decision = await AntiBotService(
            FakeVirusTotalClient(api_error)
        ).check_message("example.com")

        self.assertTrue(decision.allowed)
        self.assertEqual(Verdict.API_ERROR, decision.verdict)

    async def test_missing_url_report_falls_back_to_domain(self):
        def reputation(indicator):
            if indicator.kind == "url":
                return ReputationResult(
                    indicator,
                    Verdict.UNKNOWN,
                    reason="report not found",
                )
            return ReputationResult(
                indicator,
                Verdict.MALICIOUS,
                malicious=3,
                cacheable=True,
            )

        fake = FakeVirusTotalClient(reputation)
        decision = await AntiBotService(fake).check_message(
            "https://bad.example/path"
        )

        self.assertFalse(decision.allowed)
        self.assertEqual(
            [
                ("url", "https://bad.example/path"),
                ("domain", "bad.example"),
            ],
            fake.calls,
        )

    async def test_private_ip_is_allowed_without_lookup(self):
        fake = FakeVirusTotalClient()
        decision = await AntiBotService(fake).check_message("http://127.0.0.1")

        self.assertTrue(decision.allowed)
        self.assertEqual(Verdict.LOCAL_PRIVATE, decision.verdict)
        self.assertEqual([], fake.calls)


if __name__ == "__main__":
    unittest.main()
