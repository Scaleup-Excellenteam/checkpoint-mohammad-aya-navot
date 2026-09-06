import asyncio
import websockets

SERVER_URL = "ws://172.20.10.3:8000/messanger"
OWN_SERVER_URL = "ws://172.20.10.12:8000/messanger"
OWN_SERVER_URL_2 = "ws://127.0.0.1:8000/messanger"


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


async def main():
    async with websockets.connect(SERVER_URL) as ws:
        print("Connected to server")

        await asyncio.gather(
            receive_messages(ws),
            send_messages(ws)
        )


asyncio.run(main())