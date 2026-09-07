import hashlib
import json
import sqlite3
from pathlib import Path
from protocol/
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
import uvicorn

app = FastAPI()
PORT = 8000

rooms = []
connected_clients = []
DATABASE_PATH = Path(__file__).with_name("users.db")


def create_users_table():
    with sqlite3.connect(DATABASE_PATH) as database:
        database.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                username TEXT PRIMARY KEY,
                password TEXT NOT NULL
            )
            """
        )


def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()


def signup(username, password):
    if not username or not password:
        return False, "Username and password cannot be empty."

    try:
        with sqlite3.connect(DATABASE_PATH) as database:
            database.execute(
                "INSERT INTO users (username, password) VALUES (?, ?)",
                (username, hash_password(password)),
            )
    except sqlite3.IntegrityError:
        return False, "Username already exists."

    return True, "Signup successful."


def login(username, password):
    with sqlite3.connect(DATABASE_PATH) as database:
        user = database.execute(
            "SELECT password FROM users WHERE username = ?", (username,)
        ).fetchone()

    if user is None or user[0] != hash_password(password):
        return False, "Wrong username or password."

    return True, "Login successful."


async def authenticate(websocket):
    await websocket.send_text(
        json.dumps({"message": "Please sign up or log in."})
    )

    while True:
        try:
            request = json.loads(await websocket.receive_text())
            action = request.get("action")
            username = request.get("username", "").strip()
            password = request.get("password", "")
        except (json.JSONDecodeError, AttributeError):
            await websocket.send_text(
                json.dumps({"success": False, "message": "Invalid request."})
            )
            continue

        if action == "signup":
            success, message = signup(username, password)
        elif action == "login":
            success, message = login(username, password)
        else:
            success, message = False, "Choose signup or login."

        await websocket.send_text(
            json.dumps({"success": success, "message": message})
        )
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
