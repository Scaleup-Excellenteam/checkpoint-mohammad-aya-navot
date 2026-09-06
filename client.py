import asyncio
import websockets

SERVER_URL = "ws://localhost:9090"

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