from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class MessageType(str, Enum):
    SIGNUP = "SIGNUP"
    LOGIN = "LOGIN"
    CREATE_ROOM = "CREATE_ROOM"
    CLOSE_ROOM = "CLOSE_ROOM"
    JOIN = "JOIN"
    LEAVE = "LEAVE"
    CHAT = "CHAT"
    ACK = "ACK"
    SYSTEM = "SYSTEM"
    ERROR = "ERROR"


REQUIRED_FIELDS = {
    MessageType.SIGNUP: {"username", "password"},
    MessageType.LOGIN: {"username", "password"},
    MessageType.CREATE_ROOM: {"room"},
    MessageType.CLOSE_ROOM: {"room"},
    MessageType.JOIN: {"room"},
    MessageType.LEAVE: {"room"},
    MessageType.CHAT: {"room", "content"},
    MessageType.ACK: {"content"},
    MessageType.SYSTEM: {"content"},
    MessageType.ERROR: {"content"},
}


@dataclass
class User:
    username: str
    connection_id: str
    authenticated: bool = False
    current_room: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "username": self.username,
            "connection_id": self.connection_id,
            "authenticated": self.authenticated,
            "current_room": self.current_room,
        }


@dataclass
class Message:
    type: MessageType
    sender: str = "server"
    room: Optional[str] = None
    content: str = ""
    username: Optional[str] = None
    password: Optional[str] = None
    code: Optional[str] = None
    timestamp: float = field(default_factory=time.time)

    def to_json(self) -> str:
        payload = {
            "type": self.type.value,
            "sender": self.sender,
            "timestamp": self.timestamp,
        }

        if self.room is not None:
            payload["room"] = self.room
        if self.content:
            payload["content"] = self.content
        if self.username is not None:
            payload["username"] = self.username
        if self.password is not None:
            payload["password"] = self.password
        if self.code is not None:
            payload["code"] = self.code

        return json.dumps(payload)

    @staticmethod
    def from_json(raw: str) -> "Message":
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            raise ValueError(f"invalid JSON: {e}") from e

        if not isinstance(data, dict):
            raise ValueError("message must be a JSON object")

        type_raw = data.get("type")

        if type_raw not in MessageType._value2member_map_:
            raise ValueError(f"unknown message type: {type_raw}")

        msg_type = MessageType(type_raw)

        missing = REQUIRED_FIELDS[msg_type] - set(data.keys())

        if missing:
            raise ValueError(
                f"{msg_type.value} missing required fields: {sorted(missing)}"
            )

        for field_name in (
            "room",
            "content",
            "username",
            "password",
            "sender",
        ):
            if field_name in data and data[field_name] is not None:
                if not isinstance(data[field_name], str):
                    raise ValueError(
                        f"{field_name} must be a string, "
                        f"got {type(data[field_name]).__name__}"
                    )

        return Message(
            type=msg_type,
            sender=data.get("sender", "unknown"),
            room=data.get("room"),
            content=data.get("content", ""),
            username=data.get("username"),
            password=data.get("password"),
            code=data.get("code"),
            timestamp=data.get("timestamp", time.time()),
        )