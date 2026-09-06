from typing import Optional

from .models import Message, MessageType


def make_signup(username: str, password: str) -> str:
    return Message(
        type=MessageType.SIGNUP,
        sender=username,
        username=username,
        password=password,
    ).to_json()


def make_login(username: str, password: str) -> str:
    return Message(
        type=MessageType.LOGIN,
        sender=username,
        username=username,
        password=password,
    ).to_json()


def make_create_room(room: str) -> str:
    return Message(
        type=MessageType.CREATE_ROOM,
        room=room,
    ).to_json()


def make_close_room(room: str) -> str:
    return Message(
        type=MessageType.CLOSE_ROOM,
        room=room,
    ).to_json()


def make_join(room: str) -> str:
    return Message(
        type=MessageType.JOIN,
        room=room,
    ).to_json()


def make_leave(room: str) -> str:
    return Message(
        type=MessageType.LEAVE,
        room=room,
    ).to_json()


def make_chat(room: str, content: str) -> str:
    return Message(
        type=MessageType.CHAT,
        room=room,
        content=content,
    ).to_json()


def make_system(content: str) -> str:
    return Message(
        type=MessageType.SYSTEM,
        sender="server",
        content=content,
    ).to_json()


def make_ack(action: str, room: Optional[str] = None) -> str:
    return Message(
        type=MessageType.ACK,
        sender="server",
        content=action,
        room=room,
    ).to_json()


def make_error(content: str, code: Optional[str] = None) -> str:
    return Message(
        type=MessageType.ERROR,
        sender="server",
        content=content,
        code=code,
    ).to_json()