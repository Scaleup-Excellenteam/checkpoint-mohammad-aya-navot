from fastapi import FastAPI, WebSocket, WebSocketDisconnect
import uvicorn

app = FastAPI()
PORT = 8000

connected_clients = []


@app.get("/health")
async def health_check():
    return {"Status": "Healthy"}


@app.websocket("/messanger")
async def websocket_messanger(websocket: WebSocket):
    await websocket.accept()

    connected_clients.append(websocket)

    print(f"Client connected. Total clients: {len(connected_clients)}")

    try:
        while True:
            data = await websocket.receive_text()

            print(f"Received data: {data}")

            # Send the message to EVERY connected client
            for client in connected_clients:
                await client.send_text(data)

    except WebSocketDisconnect:
        connected_clients.remove(websocket)
        print(f"Client disconnected. Total clients: {len(connected_clients)}")


def main():
    uvicorn.run(app, host="0.0.0.0", port=PORT)


if __name__ == "__main__":
    main()