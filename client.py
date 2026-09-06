import asyncio
import getpass
import json

import websockets

SERVER_URL = "ws://localhost:8000/messanger"


async def receive_messages(ws):
    while True:
        message = await ws.recv()
        print(f"\n{message}")


async def send_messages(ws):
    while True:
        text = await asyncio.to_thread(input, "> ")

        if text == "/quit":
            await ws.close()
            return

        await ws.send(text)


async def authenticate(ws):
    server_message = json.loads(await ws.recv())
    print(server_message["message"])

    while True:
        print("\n1) Sign up")
        print("2) Log in")
        choice = await asyncio.to_thread(input, "Choose 1 or 2: ")

        if choice == "1":
            action = "signup"
        elif choice == "2":
            action = "login"
        else:
            print("Invalid choice.")
            continue

        username = await asyncio.to_thread(input, "Username: ")
        password = await asyncio.to_thread(getpass.getpass, "Password: ")

        await ws.send(
            json.dumps(
                {
                    "action": action,
                    "username": username,
                    "password": password,
                }
            )
        )

        response = json.loads(await ws.recv())
        print(response["message"])
        if response["success"]:
            return


async def main():
    async with websockets.connect(SERVER_URL) as ws:
        print("Connected to server")

        await authenticate(ws)
        print("You entered the chat. Type /quit to leave.")

        await asyncio.gather(
            receive_messages(ws),
            send_messages(ws)
        )


if __name__ == "__main__":
    asyncio.run(main())
