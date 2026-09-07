import hashlib
import hmac
import secrets
import sqlite3
from pathlib import Path
from protocol/
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
import uvicorn

from protocol.models import Message, MessageType
from protocol.protocol import make_ack, make_error

app = FastAPI()
PORT = 8000

rooms = []
connected_clients = []
DATABASE_PATH = Path(__file__).with_name("users.db")
PASSWORD_HASH_ITERATIONS = 200_000


def create_users_table():
    with sqlite3.connect(DATABASE_PATH) as database:
        database.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                username TEXT PRIMARY KEY,
                password TEXT NOT NULL,
                salt TEXT NOT NULL
            )
            """
        )

        columns = {
            column[1] for column in database.execute("PRAGMA table_info(users)")
        }
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
                "INSERT INTO users (username, password, salt) VALUES (?, ?, ?)",
                (username, hash_password(password, salt), salt),
            )
    except sqlite3.IntegrityError:
        return False, "Username already exists."

    return True, "Signup successful."


def login(username, password):
    with sqlite3.connect(DATABASE_PATH) as database:
        user = database.execute(
            "SELECT password, salt FROM users WHERE username = ?", (username,)
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
                    "UPDATE users SET password = ?, salt = ? WHERE username = ?",
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


@app.get("/health")
async def health_check():
    return {"Status": "Healthy"}


@app.websocket("/messanger")
async def websocket_messanger(websocket: WebSocket):
    # +==== Initial Handshake ====+
    await websocket.accept()

    # +==== Authentication Phase ====+
    try:
        username = await authenticate(websocket)
    except WebSocketDisconnect:
        return

    # +==== Room Selection ====+
    select_room()
    connected_clients.append(websocket)
    print(f"{username} connected. Total clients: {len(connected_clients)}")


    # +==== Room Routine ====+
    try:
        while True:
            data = await websocket.receive_text()
            print(f"Received data from {username}: {data}")

            # +==== Router ====+
            for client in connected_clients:
                await client.send_text(f"{username}: {data}")

    except WebSocketDisconnect:
        connected_clients.remove(websocket)
        print(f"{username} disconnected. Total clients: {len(connected_clients)}")


def main():
    uvicorn.run(app, host="0.0.0.0", port=PORT)



if __name__ == "__main__":
    main()
