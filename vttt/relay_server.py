"""Bounded two-player TCP relay. Run with ``python3 -m vttt.relay_server``.

The room host remains authoritative for rules and presentation, just as on LAN.
Only the Python standard library is needed on the server.
"""

import argparse
import asyncio
from dataclasses import dataclass, field
import json
import logging
import secrets
import sys
import time

from .lan_transport import MAX_FRAME, VERSION, encode

LOG = logging.getLogger(__name__)


@dataclass(eq=False)
class Peer:
    writer: object
    outgoing: object = field(default_factory=lambda: asyncio.Queue(maxsize=128))

    def send(self, message):
        """Queue one message without allowing a slow reader to block its opponent."""
        try:
            self.outgoing.put_nowait(message)
        except asyncio.QueueFull:
            self.writer.close()

    async def write(self):
        """Serialize and drain outbound frames with a bounded write timeout."""
        while True:
            value = await self.outgoing.get()
            self.writer.write(encode(value))
            await asyncio.wait_for(self.writer.drain(), 2)


@dataclass
class RelayRoom:
    id: str
    number: str
    host_token: str
    guest_token: str = ''
    peers: dict = field(default_factory=dict)
    touched: float = field(default_factory=time.monotonic)


class RelayServer:
    """Keep room identities across brief disconnections; forget idle rooms after a minute."""

    def __init__(self, max_rooms=64, max_connections=160, idle_seconds=60):
        self.rooms = {}
        self.writers = set()
        self.tasks = set()
        self.max_rooms = max_rooms
        self.max_connections = max_connections
        self.idle_seconds = idle_seconds
        self.server = None

    async def start(self, host='0.0.0.0', port=24040):
        """Bind a listener; port zero is useful for integration tests."""
        self.server = await asyncio.start_server(self.handle, host, port, limit=MAX_FRAME + 1)
        return self.server.sockets[0].getsockname()[1]

    async def close(self):
        """Close listener, client connections and their tasks."""
        self.server.close()
        await self.server.wait_closed()
        for writer in list(self.writers):
            writer.close()
        if self.tasks:
            await asyncio.gather(*list(self.tasks), return_exceptions=True)

    def prune(self):
        """Bound reservations left behind by clients that never return."""
        now = time.monotonic()
        for rid, room in list(self.rooms.items()):
            if not room.peers and now - room.touched > self.idle_seconds:
                del self.rooms[rid]

    async def read(self, reader):
        """Read one bounded JSON object, disconnecting idle or malformed clients."""
        line = await asyncio.wait_for(reader.readline(), 5)
        if not line or len(line) > MAX_FRAME or not line.endswith(b'\n'):
            raise ValueError('bad frame')
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError('expected object')
        return value

    async def handle(self, reader, writer):
        """Handle a short directory request or a persistent player connection."""
        task = asyncio.current_task()
        if len(self.writers) >= self.max_connections:
            writer.close()
            await writer.wait_closed()
            return
        self.tasks.add(task)
        self.writers.add(writer)
        room = peer = role = pump = None
        try:
            self.prune()
            request = await self.read(reader)
            if request.get('version') != VERSION:
                raise ValueError('unsupported protocol version')
            operation = request.get('op')
            if operation == 'create':
                if len(self.rooms) >= self.max_rooms:
                    raise ValueError('server room limit reached')
                numbers = {r.number for r in self.rooms.values()}
                number = str(1000 + secrets.randbelow(9000))
                while number in numbers:
                    number = str(1000 + secrets.randbelow(9000))
                room = RelayRoom(secrets.token_hex(16), number, secrets.token_hex(16))
                self.rooms[room.id] = room
                reply = dict(type='created', id=room.id, number=room.number, token=room.host_token)
                LOG.info('Room %s created', number)
            elif operation == 'list':
                reply = dict(type='rooms', rooms=[dict(id=r.id, number=r.number)
                             for r in self.rooms.values() if 'host' in r.peers and not r.guest_token])
            elif operation == 'connect':
                room = self.rooms.get(request.get('room'))
                if room is None:
                    raise ValueError('room no longer exists')
                role, token = request.get('role'), request.get('token')
                if role not in ('host', 'guest') or not isinstance(token, str) or len(token) != 32:
                    raise ValueError('bad player identity')
                expected = room.host_token if role == 'host' else room.guest_token
                if expected and not secrets.compare_digest(token, expected):
                    raise ValueError('room already reserved')
                if role in room.peers:
                    raise ValueError('player already connected')
                if role == 'guest':
                    room.guest_token = token
                peer = Peer(writer)
                room.peers[role] = peer
                room.touched = time.monotonic()
                peer.send(dict(type='welcome', version=VERSION))
                if len(room.peers) == 2:
                    for member in room.peers.values():
                        member.send(dict(type='peer_ready'))
                    LOG.info('Room %s paired', room.number)
                pump = asyncio.create_task(peer.write())
                while True:
                    message = await self.read(reader)
                    kind = message.get('type')
                    if kind == 'ping':
                        peer.send(dict(type='ping'))
                    elif kind == 'leave':
                        self.rooms.pop(room.id, None)
                        other = room.peers.get('guest' if role == 'host' else 'host')
                        if other:
                            other.send(dict(type='leave'))
                        return
                    elif kind == ('state' if role == 'host' else 'command'):
                        other = room.peers.get('guest' if role == 'host' else 'host')
                        if other:
                            other.send(message)
                    else:
                        raise ValueError('unexpected message type')
            else:
                raise ValueError('unknown operation')
            writer.write(encode(reply))
            await asyncio.wait_for(writer.drain(), 2)
        except (OSError, ValueError, TypeError, asyncio.TimeoutError):
            # Malformed clients and network outages must not stop other rooms.
            pass
        finally:
            if pump:
                pump.cancel()
                await asyncio.gather(pump, return_exceptions=True)
            if peer and room.peers.get(role) is peer:
                del room.peers[role]
                room.touched = time.monotonic()
                for other in room.peers.values():
                    other.send(dict(type='peer_down'))
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass
            self.writers.discard(writer)
            self.tasks.discard(task)


async def serve(host, port):
    """Run until the operator stops the server."""
    relay = RelayServer()
    await relay.start(host, port)
    LOG.info('VTTT relay listening on %s:%s', host, port)
    try:
        await relay.server.serve_forever()
    finally:
        await relay.close()


def main():
    """Parse the deployment address and start the relay."""
    parser = argparse.ArgumentParser(description='VTTT two-player relay server')
    parser.add_argument('--bind', default='0.0.0.0')
    parser.add_argument('--port', type=int, default=24040)
    parser.add_argument('--check', metavar='HOST', help='check a running relay and exit')
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error('--port must be 1..65535')
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    if args.check:
        from .online_transport import request
        try:
            reply = request(args.check, args.port, dict(op='list'))
            if reply.get('type') != 'rooms' or not isinstance(reply.get('rooms'), list):
                raise ValueError('not a VTTT relay')
            print('VTTT relay OK: %d room(s)' % len(reply['rooms']))
            return 0
        except (OSError, ValueError):
            LOG.error('Cannot reach VTTT relay at %s:%s', args.check, args.port)
            return 1
    try:
        asyncio.run(serve(args.bind, args.port))
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    sys.exit(main())
