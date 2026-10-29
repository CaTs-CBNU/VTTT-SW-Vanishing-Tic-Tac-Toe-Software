"""Portable LAN discovery and a bounded, reconnecting TCP JSON channel."""
from dataclasses import dataclass, asdict
import json
import queue
import select
import socket
import struct
import threading
import time
import uuid

GROUP, DISCOVERY_PORT = '239.255.77.77', 44244
VERSION = 1
MAX_FRAME = 65536


@dataclass(frozen=True)
class Room:
    id: str
    number: str
    host: str
    port: int
    available: bool = True


def encode(message):
    data = json.dumps(message, ensure_ascii=True, separators=(',', ':')).encode() + b'\n'
    if len(data) > MAX_FRAME:
        raise ValueError('network frame too large')
    return data


class Discovery:
    def __init__(self, port=DISCOVERY_PORT):
        self.port = port
        self.rooms = {}
        self.advertisement = None
        self.error = ''
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        try:
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if hasattr(socket, 'SO_REUSEPORT'):
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            self.socket.bind(('', port))
            self.socket.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP,
                                   socket.inet_aton(GROUP) + socket.inet_aton('0.0.0.0'))
            self.socket.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 1)
            self.socket.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 1)
            self.socket.settimeout(.15)
        except OSError:
            self.socket.close()
            raise
        self.thread = threading.Thread(target=self._run, daemon=True, name='vttt-discovery')
        self.thread.start()

    def advertise(self, room):
        self.advertisement = room

    def list_rooms(self):
        now = time.monotonic()
        with self.lock:
            return sorted([room for room, seen in self.rooms.values() if now - seen < 3 and room.available],
                          key=lambda r: (r.number, r.id))

    def find_room(self, room_id):
        with self.lock:
            entry = self.rooms.get(room_id)
            return entry[0] if entry and time.monotonic() - entry[1] < 3 else None

    def _run(self):
        sent = 0
        while not self.stop.is_set():
            room = self.advertisement
            if room is not None and time.monotonic() - sent > .5:
                packet = encode({'service': 'vttt-lan', 'version': VERSION, **asdict(room)})
                for address in (GROUP, '255.255.255.255'):
                    try:
                        self.socket.sendto(packet, (address, self.port))
                    except OSError:
                        self.error = '방 검색 패킷을 보낼 수 없습니다'
                sent = time.monotonic()
            try:
                data, (address, _) = self.socket.recvfrom(2048)
                value = json.loads(data)
                if (value.get('service') != 'vttt-lan' or value.get('version') != VERSION or
                        not isinstance(value.get('id'), str) or len(value['id']) != 32 or
                        not isinstance(value.get('number'), str) or not value['number'].isdigit() or
                        len(value['number']) != 4 or type(value.get('port')) is not int or
                        not 1 <= value['port'] <= 65535):
                    continue
                room = Room(value['id'], value['number'], address, value['port'], value.get('available') is True)
                with self.lock:
                    if len(self.rooms) > 128:
                        self.rooms = {k: v for k, v in self.rooms.items() if time.monotonic() - v[1] < 3}
                    self.rooms[room.id] = (room, time.monotonic())
            except socket.timeout:
                continue
            except (OSError, ValueError, TypeError, AttributeError):
                continue

    def close(self):
        self.stop.set()
        self.thread.join(timeout=.4)
        self.socket.close()


class LanLink:
    """Only I/O runs on the thread. All game state belongs to the UI thread."""
    def __init__(self, room=None, host=False, bind='0.0.0.0', heartbeat=.5, timeout=3.0):
        self.is_host = host
        self.events = queue.Queue()
        self.outgoing = queue.Queue(maxsize=128)
        self.stop = threading.Event()
        self.connected = False
        self.ever_connected = False
        self.identity = uuid.uuid4().hex
        self.allowed_peer = None
        self.heartbeat, self.timeout = heartbeat, timeout
        self.socket = None
        self.listener = None
        self.room = room
        if host:
            self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                self.listener.bind((bind, 0))
                self.listener.listen(4)
                self.listener.settimeout(.2)
                self.room = Room(uuid.uuid4().hex, str(1000 + uuid.uuid4().int % 9000), bind,
                                 self.listener.getsockname()[1])
            except OSError:
                self.listener.close()
                raise
        self.thread = threading.Thread(target=self._run, daemon=True, name='vttt-lan')
        self.thread.start()

    def send(self, message):
        try:
            self.outgoing.put_nowait(message)
        except queue.Full:
            self.drop_connection()

    def poll(self):
        result = []
        while True:
            try:
                result.append(self.events.get_nowait())
            except queue.Empty:
                return result

    def drop_connection(self):
        sock = self.socket
        if sock:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    def _hello(self, sock):
        sock.settimeout(2)
        if self.is_host:
            data = bytearray()
            while b'\n' not in data:
                fragment = sock.recv(1024)
                if not fragment:
                    raise OSError('handshake closed')
                data.extend(fragment)
                if len(data) > 2048:
                    raise ValueError('bad handshake')
            line, remainder = bytes(data).split(b'\n', 1)
            value = json.loads(line)
            peer = value.get('peer')
            if (value.get('type') != 'hello' or value.get('version') != VERSION or
                    value.get('room') != self.room.id or not isinstance(peer, str) or len(peer) != 32 or
                    (self.allowed_peer is not None and self.allowed_peer != peer)):
                raise ValueError('wrong room or peer')
            self.allowed_peer = peer
            sock.sendall(encode({'type': 'welcome', 'version': VERSION, 'room': self.room.id}))
            return remainder
        sock.sendall(encode({'type': 'hello', 'version': VERSION, 'peer': self.identity, 'room': self.room.id}))
        data = bytearray()
        while b'\n' not in data:
            fragment = sock.recv(1024)
            if not fragment:
                raise OSError('handshake closed')
            data.extend(fragment)
            if len(data) > MAX_FRAME:
                raise ValueError('bad handshake')
        line, remainder = bytes(data).split(b'\n', 1)
        value = json.loads(line)
        if value.get('type') != 'welcome' or value.get('room') != self.room.id or value.get('version') != VERSION:
            raise ValueError('bad welcome')
        return remainder

    def _run(self):
        while not self.stop.is_set():
            sock = None
            try:
                if self.is_host:
                    try:
                        sock, _ = self.listener.accept()
                    except socket.timeout:
                        continue
                else:
                    sock = socket.create_connection((self.room.host, self.room.port), timeout=.6)
                self.socket = sock
                buffer = self._hello(sock)
                sock.settimeout(.3)
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                # Old queued requests are replayed by the controller after state sync.
                while not self.outgoing.empty():
                    try:
                        self.outgoing.get_nowait()
                    except queue.Empty:
                        break
                self.connected = self.ever_connected = True
                self.events.put(('connected', None))
                heard, sent = time.monotonic(), 0
                while not self.stop.is_set():
                    while b'\n' in buffer:
                        line, buffer = buffer.split(b'\n', 1)
                        if len(line) > MAX_FRAME:
                            raise ValueError('oversized frame')
                        value = json.loads(line)
                        if not isinstance(value, dict):
                            raise ValueError('bad frame')
                        heard = time.monotonic()
                        if value.get('type') == 'leave':
                            self.events.put(('left', None))
                            self.stop.set()
                            break
                        if value.get('type') != 'ping':
                            self.events.put(('message', value))
                    if len(buffer) > MAX_FRAME:
                        raise ValueError('oversized frame')
                    while not self.outgoing.empty():
                        try:
                            sock.sendall(encode(self.outgoing.get_nowait()))
                        except queue.Empty:
                            break
                    now = time.monotonic()
                    if now - sent >= self.heartbeat:
                        sock.sendall(encode({'type': 'ping'}))
                        sent = now
                    if now - heard > self.timeout:
                        raise OSError('heartbeat timeout')
                    readable, _, _ = select.select([sock], [], [], .05)
                    if readable:
                        data = sock.recv(8192)
                        if not data:
                            raise OSError('connection closed')
                        buffer += data
            except (OSError, ValueError, TypeError, AttributeError):
                pass
            finally:
                if self.connected:
                    self.connected = False
                    self.events.put(('disconnected', None))
                if sock:
                    if self.stop.is_set():
                        try:
                            sock.sendall(encode({'type': 'leave'}))
                        except OSError:
                            pass
                    sock.close()
                self.socket = None
            if not self.is_host:
                self.stop.wait(.4)

    def close(self):
        self.stop.set()
        self.thread.join(timeout=2.5)
        if self.listener:
            self.listener.close()
        self.drop_connection()
