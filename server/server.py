import hashlib
import hmac
import secrets
import sqlite3
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
import uvicorn

from protocol.models import Message, MessageType, Room, User
from protocol.protocol import make_ack, make_error

app = FastAPI()
PORT = 8000
RED = "\033[31m"
GREEN = "\033[32m"
RESET = "\033[0m"


rooms: dict[str, Room] = {}
DATABASE_PATH = Path(__file__).with_name("users.db")
PASSWORD_HASH_ITERATIONS = 200_000


def create_users_table():
    with sqlite3.connect(DATABASE_PATH) as database:
        database.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                username TEXT PRIMARY KEY,
                password_hash TEXT NOT NULL,
                salt TEXT NOT NULL
            )
            """
        )

        columns = {
            column[1] for column in database.execute("PRAGMA table_info(users)")
        }
        if "password_hash" not in columns and "password" in columns:
            database.execute(
                "ALTER TABLE users RENAME COLUMN password TO password_hash"
            )
        if "salt" not in columns:
            database.execute("ALTER TABLE users ADD COLUMN salt TEXT")


def hash_password(password, salt):
    return hashlib.pbkdf2_hmac(
        "sha256",
        password.encode(),
        bytes.fromhex(salt),
        PASSWORD_HASH_ITERATIONS,
    ).hex()


def hash_legacy_password(password):
    return hashlib.sha256(password.encode()).hexdigest()


def signup(username, password):
    if not username or not password:
        return False, "Username and password cannot be empty."

    salt = secrets.token_hex(16)

    try:
        with sqlite3.connect(DATABASE_PATH) as database:
            database.execute(
                """
                INSERT INTO users (username, password_hash, salt)
                VALUES (?, ?, ?)
                """,
                (username, hash_password(password, salt), salt),
            )
    except sqlite3.IntegrityError:
        return False, "Username already exists."

    return True, "Signup successful."


def login(username, password):
    with sqlite3.connect(DATABASE_PATH) as database:
        user = database.execute(
            "SELECT password_hash, salt FROM users WHERE username = ?",
            (username,),
        ).fetchone()

        if user is None:
            return False, "Wrong username or password."

        stored_hash, salt = user
        if salt:
            password_matches = hmac.compare_digest(
                stored_hash,
                hash_password(password, salt),
            )
        else:
            password_matches = hmac.compare_digest(
                stored_hash,
                hash_legacy_password(password),
            )
            if password_matches:
                salt = secrets.token_hex(16)
                database.execute(
                    """
                    UPDATE users SET password_hash = ?, salt = ?
                    WHERE username = ?
                    """,
                    (hash_password(password, salt), salt, username),
                )

    if not password_matches:
        return False, "Wrong username or password."

    return True, "Login successful."


async def authenticate(websocket):
    while True:
        try:
            request = Message.from_json(await websocket.receive_text())
        except ValueError as error:
            await websocket.send_text(make_error(str(error), code="INVALID_MESSAGE"))
            continue

        if request.type not in (MessageType.SIGNUP, MessageType.LOGIN):
            await websocket.send_text(
                make_error(
                    "Choose signup or login.",
                    code="AUTH_MESSAGE_REQUIRED",
                )
            )
            continue

        username = (request.username or "").strip()
        password = request.password or ""

        if request.type == MessageType.SIGNUP:
            success, message = signup(username, password)
            response = make_ack("SIGNUP") if success else make_error(message)
            await websocket.send_text(response)
            continue

        success, message = login(username, password)
        response = make_ack("LOGIN") if success else make_error(message)
        await websocket.send_text(response)
        if success:
            return username


create_users_table()


def format_message(msg: str, mode: bool) -> str:
    if(mode == 0):
        return str(f"{RED}server: {msg} {RESET}")
    
    if(mode == 1):
        return str(f"{GREEN}{msg} {RESET}")


    


@app.get("/health")
async def health_check():
    return {"Status": "Healthy"}


async def room_lounge(websocket: WebSocket) -> Room:
    while True:
        available = ", ".join(rooms) or "(no rooms yet)"
        await websocket.send_text(
            f"Rooms: {available}\nEnter a room name, or /create to create a room."
        )
        choice = (await websocket.receive_text()).strip()
        if choice == "/create":
            await websocket.send_text(format_message("Enter a name for the new room:", False))
            room_id = (await websocket.receive_text()).strip()
            if not room_id or room_id == "/create":
                await websocket.send_text(format_message("Please choose a valid room name.", False))
                continue
            if room_id in rooms:
                await websocket.send_text(format_message("Room already exists.", False))
                continue
            rooms[room_id] = Room(room_id)
            return rooms[room_id]
        if choice in rooms:
            return rooms[choice]
        await websocket.send_text(format_message("Room does not exist.", False))


async def room_chat(websocket: WebSocket, user: User, room: Room):
    try:
        await room.add_client(user, websocket)
        await websocket.send_text(format_message("Type quit to return to the lounge."))
        while True:
            content = await websocket.receive_text()
            if content.strip().lower() == "quit":
                return
            await room.broadcast(f"{user.username} : {content}")
    finally:
        await room.remove_client(websocket)



@app.websocket("/messanger")
async def websocket_manager(websocket: WebSocket):
    await websocket.accept()
    try:
        username = await authenticate(websocket)
        user = User(username=username, authenticated=True)
        while True:
            room = await room_lounge(websocket)
            await room_chat(websocket, user, room)
    except WebSocketDisconnect:
        pass



def main():
    uvicorn.run(app, host="0.0.0.0", port=PORT)


if __name__ == "__main__":
    main()
