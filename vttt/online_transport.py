"""Room directory and reconnecting relay link, compatible with the LAN controller."""

import json
import queue
import select
import socket
import threading
import time
import uuid

from .lan_transport import LanLink, MAX_FRAME, Room, VERSION, encode


def request(host, port, operation):
    """Perform a bounded directory request; the persistent link uses its own socket."""
    with socket.create_connection((host, port), timeout=2) as sock:
        sock.sendall(encode(dict(version=VERSION, **operation)))
        data = bytearray()
        while b'\n' not in data:
            part = sock.recv(4096)
            if not part:
                raise OSError('relay closed the request')
            data.extend(part)
            if len(data) > MAX_FRAME:
                raise ValueError('relay reply too large')
        value = json.loads(bytes(data).split(b'\n', 1)[0])
        if not isinstance(value, dict):
            raise ValueError('bad relay reply')
        return value


class OnlineDirectory:
    """Poll a central room list without network I/O in the render loop."""

    def __init__(self, host, port):
        self.host, self.port = host, port
        self.rooms = []
        self.error = ''
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True, name='vttt-online-directory')
        self.thread.start()

    def create(self):
        """Reserve one room and return its host credential separately from its public ID."""
        value = request(self.host, self.port, dict(op='create'))
        if value.get('type') != 'created' or not all(isinstance(value.get(k), str) for k in ('id', 'number', 'token')):
            raise ValueError('bad room reservation')
        return Room(value['id'], value['number'], self.host, self.port), value['token']

    def _run(self):
        while not self.stop.is_set():
            try:
                value = request(self.host, self.port, dict(op='list'))
                if value.get('type') != 'rooms' or not isinstance(value.get('rooms'), list) or len(value['rooms']) > 64:
                    raise ValueError('bad room list')
                rooms = []
                for item in value['rooms']:
                    if (not isinstance(item, dict) or not isinstance(item.get('id'), str) or
                            len(item['id']) != 32 or not isinstance(item.get('number'), str) or
                            len(item['number']) != 4 or not item['number'].isdigit()):
                        raise ValueError('bad room entry')
                    rooms.append(Room(item['id'], item['number'], self.host, self.port))
                self.rooms = sorted(rooms, key=lambda r: r.number)
                self.error = ''
            except (OSError, ValueError, TypeError, KeyError):
                self.rooms = []
                self.error = '중계 서버에 연결할 수 없습니다'
            self.stop.wait(1)

    def list_rooms(self):
        """Return the last complete room list."""
        return list(self.rooms)

    def find_room(self, room_id):
        """A central endpoint stays fixed even when a room is no longer listed."""
        return None

    def advertise(self, room):
        """The server derives availability from attached player identities."""

    def close(self):
        """Stop polling the room directory."""
        self.stop.set()
        self.thread.join(timeout=2.5)


class OnlineLink(LanLink):
    """Keep the host role while both devices dial the same central endpoint."""

    def __init__(self, room, host=False, token=None):
        self.is_host = host
        self.room = room
        self.identity = token or uuid.uuid4().hex
        self.events = queue.Queue()
        self.outgoing = queue.Queue(maxsize=128)
        self.stop = threading.Event()
        self.connected = self.ever_connected = False
        self.socket = self.listener = None
        self.heartbeat, self.timeout = .5, 4.0
        self.thread = threading.Thread(target=self._run, daemon=True, name='vttt-online-link')
        self.thread.start()

    def _disconnected(self):
        if self.connected:
            self.connected = False
            self.events.put(('disconnected', None))

    def _run(self):
        while not self.stop.is_set():
            sock = None
            try:
                sock = socket.create_connection((self.room.host, self.room.port), timeout=2)
                self.socket = sock
                sock.settimeout(1)
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                sock.sendall(encode(dict(op='connect', version=VERSION, room=self.room.id,
                                         role='host' if self.is_host else 'guest', token=self.identity)))
                buffer = b''
                heard, sent = time.monotonic(), 0
                welcomed = False
                while not self.stop.is_set():
                    while b'\n' in buffer:
                        line, buffer = buffer.split(b'\n', 1)
                        if len(line) + 1 > MAX_FRAME:
                            raise ValueError('frame too large')
                        value = json.loads(line)
                        if not isinstance(value, dict):
                            raise ValueError('bad relay frame')
                        heard = time.monotonic()
                        kind = value.get('type')
                        if not welcomed:
                            if kind != 'welcome' or value.get('version') != VERSION:
                                raise ValueError('bad relay welcome')
                            welcomed = True
                        elif kind == 'peer_ready':
                            while not self.outgoing.empty():
                                try:
                                    self.outgoing.get_nowait()
                                except queue.Empty:
                                    break
                            self.connected = self.ever_connected = True
                            self.events.put(('connected', None))
                        elif kind == 'peer_down':
                            self._disconnected()
                        elif kind == 'leave':
                            self.events.put(('left', None))
                            self.stop.set()
                        elif kind != 'ping' and self.connected:
                            self.events.put(('message', value))
                    if len(buffer) > MAX_FRAME:
                        raise ValueError('frame too large')
                    while not self.outgoing.empty():
                        try:
                            value = self.outgoing.get_nowait()
                        except queue.Empty:
                            break
                        if self.connected:
                            sock.sendall(encode(value))
                    now = time.monotonic()
                    if now - sent >= self.heartbeat:
                        sock.sendall(encode(dict(type='ping')))
                        sent = now
                    if now - heard > self.timeout:
                        raise OSError('relay heartbeat timeout')
                    readable, _, _ = select.select([sock], [], [], .05)
                    if readable:
                        data = sock.recv(8192)
                        if not data:
                            raise OSError('relay closed')
                        buffer += data
            except (OSError, ValueError, TypeError):
                pass
            finally:
                self._disconnected()
                if sock:
                    if self.stop.is_set():
                        try:
                            sock.sendall(encode(dict(type='leave')))
                        except OSError:
                            pass
                    sock.close()
                self.socket = None
            self.stop.wait(.4)
