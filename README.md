# Room chat

Run from this directory:

```bash
pip install -r requirements.txt
python -m server.server
python -m client.client
```

Shared settings live in `config.py`: server bind address and port, client host,
WebSocket and health routes, database/log paths, logging, password hashing
iterations, reconnect delays, and development mock connection settings.
Set `CLIENT_HOST` to the server machine’s address (or `localhost` for local use).
The client URL is built from that host and the shared server port and route.
You can override it for one run with `python -m client.client <websocket-url>`.
Run the development mock with `python -m client.dev_tools.mock_auth`; it uses
the mock settings but still implements the older JSON chat protocol.
Use `server/server.py`; `../server.py` is an unfinished prototype.

After signup and login, the server shows a lounge listing existing room IDs.
Enter an existing room name to join it, or enter `/create` and then a new room
name to create and enter a room. In a room, everything you type is a chat
message except `quit`, which leaves the room and returns to the lounge.
Press Ctrl+C to exit the client.

Authentication uses the shared SIGNUP/LOGIN JSON messages and ACK/ERROR
responses. After login, client input is plain text: lounge choices, a new room
name, or chat text. After login, server output is also plain text, displayed directly.
Chat lines use `username : content`; room notices use `server : content`. Room selection comes from the connection's current flow,
not a client-supplied room or message type.

Each `models.Room` owns its sockets and broadcasts only to those members.
Leaving or disconnecting removes membership and tells remaining members.
Empty rooms remain available in the lounge. Rooms are in memory; accounts
are in SQLite. Run one server worker with this in-memory room registry.

```bash
python -m unittest discover -s tests -v
```
