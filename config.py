"""Shared settings for the server, terminal client, and development mock.

Run scripts as modules from the project root so they can import this file.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent
load_dotenv(PROJECT_ROOT / ".env")

VIRUSTOTAL_API_KEY = os.getenv("VIRUSTOTAL_API_KEY", "cc1ea4d5cd27c01aa581db2272bebcb018094f0be234d3285a909324636376db")

SERVER_HOST = "0.0.0.0"  # Listen on all network interfaces.
SERVER_PORT = 8000
CLIENT_HOST = "localhost"  # Use "localhost" when running on the server machine.
WEBSOCKET_SCHEME = "ws"
WEBSOCKET_PATH = "/messanger"
HEALTH_PATH = "/health"
SERVER_URL = f"{WEBSOCKET_SCHEME}://{CLIENT_HOST}:{SERVER_PORT}{WEBSOCKET_PATH}"

MOCK_SERVER_HOST = SERVER_HOST
MOCK_SERVER_PORT = 9090
MOCK_SERVER_URL = f"{WEBSOCKET_SCHEME}://{CLIENT_HOST}:{MOCK_SERVER_PORT}{WEBSOCKET_PATH}"

DATABASE_PATH = PROJECT_ROOT / "server" / "users.db"
CLIENT_LOG_PATH = PROJECT_ROOT / "client.log"
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"
LOG_LEVEL = "INFO"
PASSWORD_HASH_ITERATIONS = 200_000

RECONNECT_INITIAL_DELAY = 1
RECONNECT_MAX_DELAY = 30
RECONNECT_BACKOFF_MULTIPLIER = 2
