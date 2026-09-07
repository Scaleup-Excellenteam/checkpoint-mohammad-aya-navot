# Room chat

Run from this directory:

```bash
pip install -r requirements.txt
python -m server.server
python -m client.client
```

The client connects to `ws://localhost:8000/manager`. `/messanger` also works.
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
