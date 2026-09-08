from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
from fastapi import WebSocket, WebSocketDisconnect

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
    password: str = ""
    # connection_id: str
    authenticated: bool = False
    current_room: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "username": self.username,
            # "connection_id": self.connection_id,
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

    def to_string(self) -> str:
        return f"{self.sender} : {self.content}"

    def to_json(self) -> str:
        payload = {
            "type": self.type.value,
            "sender": self.sender,
            "timestamp": self.timestamp,
        }

        if self.room is not None:
            payload["room"] = self.room
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

        if not isinstance(type_raw, str) or type_raw not in MessageType._value2member_map_:
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
            "code",
        ):
            if field_name in data and data[field_name] is not None:
                if not isinstance(data[field_name], str):
                    raise ValueError(
                        f"{field_name} must be a string, "
                        f"got {type(data[field_name]).__name__}"
                    )

        for field_name in REQUIRED_FIELDS[msg_type]:
            if not isinstance(data[field_name], str):
                raise ValueError(f"{field_name} must be a string")
        if "room" in data and (not isinstance(data["room"], str) or not data["room"].strip()):
            raise ValueError("room must be a non-empty string")
        if "sender" in data and not isinstance(data["sender"], str):
            raise ValueError("sender must be a string")
        if "content" in data and not isinstance(data["content"], str):
            raise ValueError("content must be a string")
        if "timestamp" in data and (isinstance(data["timestamp"], bool) or not isinstance(data["timestamp"], (int, float))):
            raise ValueError("timestamp must be a number")

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




class Room:
    MSG_JOIN = "{user_name} has joined"
    MSG_LEAVE = "{user_name} has left"

    def __init__(self, room_id: str):
        self.room_id = room_id
        self.connected_clients: dict[WebSocket, User] = {}

    async def broadcast(
        self, message: str, *, sender: Optional[WebSocket] = None,
        own_message: Optional[str] = None,
    ):
        for websocket, user in list(self.connected_clients.items()):
            try:
                outgoing = own_message if websocket is sender and own_message is not None else message
                await websocket.send_text(outgoing)
            except (WebSocketDisconnect, OSError, RuntimeError):
                self.connected_clients.pop(websocket, None)
                if user.current_room == self.room_id:
                    user.current_room = None

    async def add_client(self, user: User, websocket: WebSocket):
        if websocket in self.connected_clients:
            return
        self.connected_clients[websocket] = user
        user.current_room = self.room_id
       

    async def remove_client(self, websocket: WebSocket):
        user = self.connected_clients.pop(websocket, None)
        if user is None:
            return
        if user.current_room == self.room_id:
            user.current_room = None
       
