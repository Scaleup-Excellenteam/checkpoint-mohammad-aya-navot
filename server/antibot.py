"""Server-side Anti-Bot URL, domain, and IP reputation checks."""

from __future__ import annotations

import base64
import ipaddress
import logging
import os
import re
import time
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional
from urllib.parse import quote, urlsplit, urlunsplit

import httpx
from dotenv import load_dotenv


load_dotenv()

log = logging.getLogger("server.antibot")

URL_PATTERN = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
DOMAIN_PATTERN = re.compile(
    r"(?<![@\w-])(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"[a-z]{2,63}(?![\w-])",
    re.IGNORECASE,
)
IPV4_PATTERN = re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])")
IPV6_PATTERN = re.compile(
    r"(?<![\w:])(?:[0-9a-f]{0,4}:){2,7}[0-9a-f]{0,4}(?![\w:])",
    re.IGNORECASE,
)
LOCALHOST_PATTERN = re.compile(r"(?<![\w.-])localhost(?![\w.-])", re.IGNORECASE)


class Verdict(str, Enum):
    NO_INDICATORS = "NO_INDICATORS"
    CLEAN = "CLEAN"
    MALICIOUS = "MALICIOUS"
    SUSPICIOUS = "SUSPICIOUS"
    UNKNOWN = "UNKNOWN"
    API_ERROR = "API_ERROR"
    LOCAL_PRIVATE = "LOCAL_PRIVATE"


@dataclass(frozen=True)
class Indicator:
    kind: str
    value: str

    @property
    def cache_key(self) -> tuple[str, str]:
        return self.kind, self.value


@dataclass(frozen=True)
class ReputationResult:
    indicator: Indicator
    verdict: Verdict
    malicious: int = 0
    suspicious: int = 0
    reason: str = ""
    cacheable: bool = False


@dataclass(frozen=True)
class AntiBotDecision:
    allowed: bool
    verdict: Verdict
    reason: str
    results: tuple[ReputationResult, ...] = ()


def url_to_id(url: str) -> str:
    """Return the URL-safe, unpadded VirusTotal URL identifier."""
    return base64.urlsafe_b64encode(url.encode()).decode().rstrip("=")


def _normalize_host(host: str) -> Optional[str]:
    host = host.strip().rstrip(".").lower()
    if not host:
        return None
    try:
        return host.encode("idna").decode("ascii")
    except UnicodeError:
        return None


def _normalize_url(raw_url: str) -> Optional[str]:
    raw_url = raw_url.rstrip(".,!?;:")
    for opening, closing in (("(", ")"), ("[", "]"), ("{", "}")):
        while raw_url.endswith(closing) and raw_url.count(closing) > raw_url.count(
            opening
        ):
            raw_url = raw_url[:-1]
    try:
        parsed = urlsplit(raw_url)
        host = _normalize_host(parsed.hostname or "")
        if parsed.scheme.lower() not in ("http", "https") or not host:
            return None

        port = parsed.port
        default_port = (parsed.scheme.lower() == "http" and port == 80) or (
            parsed.scheme.lower() == "https" and port == 443
        )
        display_host = f"[{host}]" if ":" in host else host
        netloc = (
            display_host
            if port is None or default_port
            else f"{display_host}:{port}"
        )
        return urlunsplit(
            (parsed.scheme.lower(), netloc, parsed.path, parsed.query, "")
        )
    except ValueError:
        return None


def _normalize_ip(raw_ip: str) -> Optional[str]:
    try:
        return str(ipaddress.ip_address(raw_ip.strip("[]")))
    except ValueError:
        return None


def extract_indicators(content: str) -> list[Indicator]:
    """Extract unique normalized URLs, public/private IPs, and bare domains."""
    indicators: list[Indicator] = []
    seen: set[tuple[str, str]] = set()
    url_hosts: set[str] = set()
    masked_content = list(content)

    def add(indicator: Indicator) -> None:
        if indicator.cache_key not in seen:
            seen.add(indicator.cache_key)
            indicators.append(indicator)

    for match in URL_PATTERN.finditer(content):
        normalized_url = _normalize_url(match.group(0))
        if not normalized_url:
            continue
        add(Indicator("url", normalized_url))
        host = urlsplit(normalized_url).hostname
        if host:
            url_hosts.add(host.lower())
        for index in range(match.start(), match.end()):
            masked_content[index] = " "

    remaining = "".join(masked_content)

    for pattern in (IPV4_PATTERN, IPV6_PATTERN):
        for match in pattern.finditer(remaining):
            normalized_ip = _normalize_ip(match.group(0))
            if normalized_ip and normalized_ip not in url_hosts:
                add(Indicator("ip", normalized_ip))

    for match in DOMAIN_PATTERN.finditer(remaining):
        domain = _normalize_host(match.group(0))
        if domain and domain not in url_hosts:
            add(Indicator("domain", domain))

    for match in LOCALHOST_PATTERN.finditer(remaining):
        add(Indicator("domain", match.group(0).lower()))

    return indicators


def _is_local_or_private(indicator: Indicator) -> bool:
    value = indicator.value
    if indicator.kind == "url":
        value = urlsplit(value).hostname or ""

    if value.lower() == "localhost" or value.lower().endswith(".local"):
        return True

    normalized_ip = _normalize_ip(value)
    if not normalized_ip:
        return False

    address = ipaddress.ip_address(normalized_ip)
    return not address.is_global


class VirusTotalClient:
    """Small asynchronous VirusTotal API v3 client for reputation lookups."""

    BASE_URL = "https://www.virustotal.com/api/v3"

    def __init__(
        self,
        api_key: Optional[str] = None,
        timeout_seconds: float = 5.0,
    ) -> None:
        self.api_key = api_key if api_key is not None else os.getenv(
            "VIRUSTOTAL_API_KEY", ""
        )
        self.timeout_seconds = timeout_seconds

    def _endpoint(self, indicator: Indicator) -> str:
        if indicator.kind == "url":
            return f"{self.BASE_URL}/urls/{url_to_id(indicator.value)}"
        if indicator.kind == "domain":
            return f"{self.BASE_URL}/domains/{quote(indicator.value, safe='')}"
        if indicator.kind == "ip":
            return f"{self.BASE_URL}/ip_addresses/{quote(indicator.value, safe='')}"
        raise ValueError(f"unsupported indicator type: {indicator.kind}")

    async def lookup(self, indicator: Indicator) -> ReputationResult:
        if not self.api_key:
            return ReputationResult(
                indicator,
                Verdict.API_ERROR,
                reason="VIRUSTOTAL_API_KEY is not configured",
            )

        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.get(
                    self._endpoint(indicator),
                    headers={"x-apikey": self.api_key},
                )
        except httpx.TimeoutException:
            return ReputationResult(
                indicator,
                Verdict.API_ERROR,
                reason="VirusTotal request timed out",
            )
        except httpx.RequestError as error:
            return ReputationResult(
                indicator,
                Verdict.API_ERROR,
                reason=f"VirusTotal network failure ({type(error).__name__})",
            )

        if response.status_code == 404:
            return ReputationResult(
                indicator,
                Verdict.UNKNOWN,
                reason="report not found",
            )
        if response.status_code >= 400:
            return ReputationResult(
                indicator,
                Verdict.API_ERROR,
                reason=f"VirusTotal returned HTTP {response.status_code}",
            )

        try:
            stats = response.json()["data"]["attributes"]["last_analysis_stats"]
            malicious = int(stats.get("malicious", 0) or 0)
            suspicious = int(stats.get("suspicious", 0) or 0)
        except (KeyError, TypeError, ValueError):
            return ReputationResult(
                indicator,
                Verdict.API_ERROR,
                reason="VirusTotal returned an invalid response",
            )

        if malicious > 0:
            verdict = Verdict.MALICIOUS
        elif suspicious > 0:
            verdict = Verdict.SUSPICIOUS
        else:
            verdict = Verdict.CLEAN

        return ReputationResult(
            indicator,
            verdict,
            malicious=malicious,
            suspicious=suspicious,
            cacheable=True,
        )


class AntiBotService:
    """Extract indicators, retrieve reputation, cache results, and decide."""

    def __init__(
        self,
        virus_total: Optional[VirusTotalClient] = None,
        cache_ttl_seconds: float = 30 * 60,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.virus_total = virus_total or VirusTotalClient()
        self.cache_ttl_seconds = cache_ttl_seconds
        self.clock = clock
        self.cache: dict[
            tuple[str, str], tuple[float, ReputationResult]
        ] = {}

    async def _lookup_cached(
        self,
        indicator: Indicator,
        message_results: dict[tuple[str, str], ReputationResult],
    ) -> ReputationResult:
        key = indicator.cache_key
        if key in message_results:
            return message_results[key]

        cached = self.cache.get(key)
        now = self.clock()
        if cached and cached[0] > now:
            log.info("ANTIBOT_CACHE_HIT indicator=%s", indicator.value)
            message_results[key] = cached[1]
            return cached[1]
        if cached:
            del self.cache[key]

        # This boundary intentionally fails open so an unavailable reputation
        # provider cannot crash the chat server.
        try:
            result = await self.virus_total.lookup(indicator)
        except Exception as error:
            result = ReputationResult(
                indicator,
                Verdict.API_ERROR,
                reason=f"VirusTotal lookup failed ({type(error).__name__})",
            )
        message_results[key] = result
        if result.cacheable:
            self.cache[key] = (now + self.cache_ttl_seconds, result)
        return result

    async def _check_indicator(
        self,
        indicator: Indicator,
        message_results: dict[tuple[str, str], ReputationResult],
    ) -> ReputationResult:
        if _is_local_or_private(indicator):
            return ReputationResult(
                indicator,
                Verdict.LOCAL_PRIVATE,
                reason="local/private indicator was not queried",
            )

        result = await self._lookup_cached(indicator, message_results)
        if (
            indicator.kind == "url"
            and result.verdict == Verdict.UNKNOWN
            and result.reason == "report not found"
        ):
            host = urlsplit(indicator.value).hostname
            if host:
                kind = "ip" if _normalize_ip(host) else "domain"
                fallback = Indicator(kind, host.lower())
                result = await self._check_indicator(fallback, message_results)
                message_results[indicator.cache_key] = result
                if result.cacheable:
                    self.cache[indicator.cache_key] = (
                        self.clock() + self.cache_ttl_seconds,
                        result,
                    )
        return result

    @staticmethod
    def _log_result(username: str, result: ReputationResult) -> None:
        fields = (
            f"user={username} indicator={result.indicator.value} "
            f"verdict={result.verdict.value} malicious={result.malicious} "
            f"suspicious={result.suspicious}"
        )
        if result.verdict in (Verdict.MALICIOUS, Verdict.SUSPICIOUS):
            log.warning("ANTIBOT_BLOCK %s action=BLOCK", fields)
        elif result.verdict == Verdict.UNKNOWN:
            log.info("ANTIBOT_UNKNOWN %s", fields)
        elif result.verdict == Verdict.API_ERROR:
            log.warning(
                "ANTIBOT_API_ERROR indicator=%s reason=%s action=ALLOW",
                result.indicator.value,
                result.reason,
            )
        else:
            log.info("ANTIBOT_ALLOW %s action=ALLOW", fields)

    async def check_message(
        self,
        content: str,
        username: str = "unknown",
    ) -> AntiBotDecision:
        indicators = extract_indicators(content)
        if not indicators:
            return AntiBotDecision(
                True,
                Verdict.NO_INDICATORS,
                "No URL, domain, or IP address detected",
            )

        checked: list[ReputationResult] = []
        message_results: dict[tuple[str, str], ReputationResult] = {}
        overall = Verdict.CLEAN

        for indicator in indicators:
            result = await self._check_indicator(indicator, message_results)
            checked.append(result)
            self._log_result(username, result)

            if result.verdict in (Verdict.MALICIOUS, Verdict.SUSPICIOUS):
                reason = (
                    "Message blocked by Anti-Bot: VirusTotal marked "
                    f"{result.indicator.value} as {result.verdict.value.lower()} "
                    f"({result.malicious} malicious, {result.suspicious} "
                    "suspicious detections)."
                )
                return AntiBotDecision(
                    False,
                    result.verdict,
                    reason,
                    tuple(checked),
                )

            if result.verdict == Verdict.API_ERROR:
                overall = Verdict.API_ERROR
            elif result.verdict == Verdict.UNKNOWN and overall != Verdict.API_ERROR:
                overall = Verdict.UNKNOWN
            elif (
                result.verdict == Verdict.LOCAL_PRIVATE
                and overall == Verdict.CLEAN
            ):
                overall = Verdict.LOCAL_PRIVATE

        return AntiBotDecision(
            True,
            overall,
            "No malicious or suspicious indicators detected",
            tuple(checked),
        )
