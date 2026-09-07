# TSPO Load Testing

This folder contains an external WebSocket load test for the TSPO chat
server.

The load tester does not import or modify server internals. It behaves
like multiple real users connecting to the running server.

## Scenario

Each virtual client:

1. Opens a WebSocket connection.
2. Creates a unique account.
3. Logs in.
4. Enters the same chat room.
5. Sends multiple chat messages.
6. Receives messages broadcast by other users.
7. Disconnects.

The test reports:

- Successful connections
- Successful authentications
- Successful room joins
- Messages sent
- Messages received
- Approximate delivery percentage
- Message throughput
- Average connection time
- Average authentication time
- Client failures
- Total test duration

## Start the server

From the repository root:

```bash
python -m server.server