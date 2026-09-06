from fastapi import FastAPI, WebSocket, WebSocketDisconnect
import asyncio
import uvicorn

app = FastAPI()
PORT = 9090


@app.get("/health")
async def health_check():
    return {"Status" : "Healthy"}


@app.websocket("/messanger")
async def websocket_messanger(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_text()
            print(f"Received data: {data}")
            await websocket.send_text(data)

    except WebSocketDisconnect:
        print("User dissconected")

def main():
    uvicorn.run(app, host="0.0.0.0", port=PORT)


if __name__ == "__main__":
    main()