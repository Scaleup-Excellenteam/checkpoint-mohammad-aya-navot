import argparse
import asyncio
import json
import statistics
import time
import uuid

import websockets


DEFAULT_URL = "ws://127.0.0.1:8000/messanger"
DEFAULT_PASSWORD = "LoadTestPassword123!"


class ClientStats:
    def __init__(self, client_id):
        self.client_id = client_id
        self.username = None

        self.connected = False
        self.signed_up = False
        self.logged_in = False
        self.joined_room = False

        self.messages_sent = 0
        self.messages_received = 0

        self.connect_time = 0.0
        self.auth_time = 0.0

        self.error = None


def unique_name(prefix):
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def signup_message(username, password):
    return json.dumps({
        "type": "SIGNUP",
        "username": username,
        "password": password,
    })


def login_message(username, password):
    return json.dumps({
        "type": "LOGIN",
        "username": username,
        "password": password,
    })


async def receive_json(websocket, timeout=10):
    raw = await asyncio.wait_for(
        websocket.recv(),
        timeout=timeout,
    )

    return json.loads(raw)


async def receive_until(websocket, text, timeout=10):
    """
    Keep reading messages until one contains the requested text.

    This is useful because room join notifications may arrive
    while clients are entering the room.
    """

    end_time = asyncio.get_running_loop().time() + timeout

    while True:
        remaining = end_time - asyncio.get_running_loop().time()

        if remaining <= 0:
            raise asyncio.TimeoutError(
                f"Did not receive message containing: {text}"
            )

        message = await asyncio.wait_for(
            websocket.recv(),
            timeout=remaining,
        )

        if text.lower() in message.lower():
            return message


async def authenticate_client(websocket, stats):
    username = unique_name(f"load_user_{stats.client_id}")
    stats.username = username

    auth_start = time.perf_counter()

    await websocket.send(
        signup_message(username, DEFAULT_PASSWORD)
    )

    signup_response = await receive_json(websocket)

    if signup_response.get("type") != "ACK":
        raise RuntimeError(
            f"Signup failed: {signup_response}"
        )

    stats.signed_up = True

    await websocket.send(
        login_message(username, DEFAULT_PASSWORD)
    )

    login_response = await receive_json(websocket)

    if login_response.get("type") != "ACK":
        raise RuntimeError(
            f"Login failed: {login_response}"
        )

    stats.logged_in = True

    # Consume the lounge message shown after login.
    await receive_until(
        websocket,
        "Rooms:",
    )

    stats.auth_time = (
        time.perf_counter() - auth_start
    )


async def connect_client(url, stats):
    start = time.perf_counter()

    websocket = await websockets.connect(
        url,
        open_timeout=10,
        close_timeout=5,
    )

    stats.connect_time = (
        time.perf_counter() - start
    )

    stats.connected = True

    await authenticate_client(
        websocket,
        stats,
    )

    return websocket


async def create_room(websocket, room_name):
    await websocket.send("/create")

    await receive_until(
        websocket,
        "Enter a name",
    )

    await websocket.send(room_name)

    # Once we see this, room_chat() has started.
    await receive_until(
        websocket,
        "Type quit",
    )


async def join_room(websocket, room_name):
    await websocket.send(room_name)

    await receive_until(
        websocket,
        "Type quit",
    )


async def message_reader(websocket, stats, stop_event):
    """
    Continuously consume messages so the server can freely
    broadcast while the test is running.
    """

    while not stop_event.is_set():
        try:
            message = await asyncio.wait_for(
                websocket.recv(),
                timeout=0.25,
            )

            # Count actual chat messages.
            if "load-message-" in message:
                stats.messages_received += 1

        except asyncio.TimeoutError:
            continue

        except websockets.ConnectionClosed:
            break


async def message_sender(
    websocket,
    stats,
    messages_per_client,
    delay,
):
    for message_number in range(messages_per_client):

        message = (
            f"load-message-"
            f"{stats.client_id}-"
            f"{message_number}"
        )

        await websocket.send(message)

        stats.messages_sent += 1

        if delay > 0:
            await asyncio.sleep(delay)


async def run_load_test(
    url,
    client_count,
    messages_per_client,
    message_delay,
    settle_time,
):
    print()
    print("=" * 60)
    print("TSPO WEBSOCKET LOAD TEST")
    print("=" * 60)

    print(f"Server:              {url}")
    print(f"Clients:             {client_count}")
    print(f"Messages per client: {messages_per_client}")
    print()

    test_start = time.perf_counter()

    stats_list = [
        ClientStats(i)
        for i in range(client_count)
    ]

    sockets = []

    room_name = unique_name("load_room")

    print("[1/5] Connecting and authenticating clients...")

    async def setup_client(stats):
        try:
            websocket = await connect_client(
                url,
                stats,
            )

            return websocket

        except Exception as error:
            stats.error = str(error)
            return None

    connection_results = await asyncio.gather(
        *[
            setup_client(stats)
            for stats in stats_list
        ]
    )

    for websocket in connection_results:
        if websocket is not None:
            sockets.append(websocket)

    successful_clients = len(sockets)

    print(
        f"      {successful_clients}/{client_count} "
        "clients authenticated."
    )

    if not sockets:
        print()
        print("No clients connected.")
        print("Load test aborted.")
        return

    print(f"[2/5] Creating room '{room_name}'...")

    try:
        await create_room(
            sockets[0],
            room_name,
        )

        stats_list[0].joined_room = True

    except Exception as error:
        print(f"Could not create room: {error}")

        for websocket in sockets:
            await websocket.close()

        return

    print("[3/5] Joining remaining clients...")

    async def join_one(index):
        try:
            await join_room(
                sockets[index],
                room_name,
            )

            stats_list[index].joined_room = True

        except Exception as error:
            stats_list[index].error = str(error)

    await asyncio.gather(
        *[
            join_one(index)
            for index in range(1, len(sockets))
        ]
    )

    joined_count = sum(
        stats.joined_room
        for stats in stats_list
    )

    print(
        f"      {joined_count}/{successful_clients} "
        "clients joined the room."
    )

    print("[4/5] Sending messages...")

    stop_event = asyncio.Event()

    readers = []

    for index, websocket in enumerate(sockets):
        reader = asyncio.create_task(
            message_reader(
                websocket,
                stats_list[index],
                stop_event,
            )
        )

        readers.append(reader)

    message_start = time.perf_counter()

    send_results = await asyncio.gather(
        *[
            message_sender(
                sockets[index],
                stats_list[index],
                messages_per_client,
                message_delay,
            )
            for index in range(len(sockets))
            if stats_list[index].joined_room
        ],
        return_exceptions=True,
    )

    message_send_duration = (
        time.perf_counter() - message_start
    )

    # Give pending broadcasts time to arrive.
    await asyncio.sleep(settle_time)

    stop_event.set()

    await asyncio.gather(
        *readers,
        return_exceptions=True,
    )

    print("[5/5] Closing clients...")

    for websocket in sockets:
        try:
            await websocket.close()
        except Exception:
            pass

    total_duration = (
        time.perf_counter() - test_start
    )

    print_results(
        stats_list,
        client_count,
        messages_per_client,
        total_duration,
        message_send_duration,
    )


def print_results(
    stats_list,
    requested_clients,
    messages_per_client,
    total_duration,
    message_send_duration,
):
    connected = sum(
        stats.connected
        for stats in stats_list
    )

    authenticated = sum(
        stats.logged_in
        for stats in stats_list
    )

    joined = sum(
        stats.joined_room
        for stats in stats_list
    )

    total_sent = sum(
        stats.messages_sent
        for stats in stats_list
    )

    total_received = sum(
        stats.messages_received
        for stats in stats_list
    )

    failures = [
        stats
        for stats in stats_list
        if stats.error is not None
    ]

    connect_times = [
        stats.connect_time
        for stats in stats_list
        if stats.connected
    ]

    auth_times = [
        stats.auth_time
        for stats in stats_list
        if stats.logged_in
    ]

    expected_deliveries = (
        total_sent * joined
        if joined > 0
        else 0
    )

    if expected_deliveries:
        delivery_percentage = (
            total_received
            / expected_deliveries
            * 100
        )
    else:
        delivery_percentage = 0

    if message_send_duration > 0:
        send_rate = (
            total_sent
            / message_send_duration
        )
    else:
        send_rate = 0

    print()
    print("=" * 60)
    print("LOAD TEST RESULTS")
    print("=" * 60)

    print(
        f"Clients requested:       {requested_clients}"
    )

    print(
        f"Clients connected:       {connected}"
    )

    print(
        f"Clients authenticated:   {authenticated}"
    )

    print(
        f"Clients joined room:     {joined}"
    )

    print()
    print(
        f"Messages per client:     {messages_per_client}"
    )

    print(
        f"Messages sent:           {total_sent}"
    )

    print(
        f"Messages received:       {total_received}"
    )

    print(
        f"Expected deliveries:     {expected_deliveries}"
    )

    print(
        f"Observed delivery:       {delivery_percentage:.2f}%"
    )

    print()
    print(
        f"Message send duration:   {message_send_duration:.2f}s"
    )

    print(
        f"Send throughput:         {send_rate:.2f} msg/s"
    )

    print(
        f"Total test duration:     {total_duration:.2f}s"
    )

    if connect_times:
        print(
            f"Average connect time:    "
            f"{statistics.mean(connect_times):.3f}s"
        )

        print(
            f"Max connect time:        "
            f"{max(connect_times):.3f}s"
        )

    if auth_times:
        print(
            f"Average auth time:       "
            f"{statistics.mean(auth_times):.3f}s"
        )

        print(
            f"Max auth time:           "
            f"{max(auth_times):.3f}s"
        )

    print(
        f"Client failures:         {len(failures)}"
    )

    if failures:
        print()
        print("FAILURES:")

        for stats in failures:
            print(
                f"  Client {stats.client_id}: "
                f"{stats.error}"
            )

    print()
    print("=" * 60)

    if len(failures) == 0 and connected == requested_clients:
        print("RESULT: SERVER REMAINED AVAILABLE UNDER THIS LOAD")
    else:
        print("RESULT: FAILURES WERE OBSERVED UNDER THIS LOAD")

    print("=" * 60)


def parse_arguments():
    parser = argparse.ArgumentParser(
        description="TSPO WebSocket load tester"
    )

    parser.add_argument(
        "--url",
        default=DEFAULT_URL,
        help="WebSocket server URL",
    )

    parser.add_argument(
        "--clients",
        type=int,
        default=10,
        help="Number of concurrent clients",
    )

    parser.add_argument(
        "--messages",
        type=int,
        default=5,
        help="Messages sent by each client",
    )

    parser.add_argument(
        "--delay",
        type=float,
        default=0.05,
        help="Delay between messages from one client",
    )

    parser.add_argument(
        "--settle",
        type=float,
        default=2.0,
        help="Time to wait for final broadcasts",
    )

    return parser.parse_args()


async def main():
    args = parse_arguments()

    if args.clients < 1:
        raise ValueError(
            "--clients must be at least 1"
        )

    if args.messages < 1:
        raise ValueError(
            "--messages must be at least 1"
        )

    await run_load_test(
        url=args.url,
        client_count=args.clients,
        messages_per_client=args.messages,
        message_delay=args.delay,
        settle_time=args.settle,
    )


if __name__ == "__main__":
    asyncio.run(main())