"""Actual TCP relay, two application controllers, and protocol isolation."""

import asyncio
import json
import threading
import unittest

import test_lan as lan_tests
from vttt.buttons import ButtonEvent
from vttt.relay_server import RelayServer
from vttt.lan_transport import VERSION, encode


class RelayHarness:
    def __init__(self):
        self.loop = asyncio.new_event_loop()
        self.relay = RelayServer()
        self.thread = threading.Thread(target=self.loop.run_forever, daemon=True)
        self.thread.start()
        self.port = asyncio.run_coroutine_threadsafe(
            self.relay.start('127.0.0.1', 0), self.loop).result(3)

    def close(self):
        asyncio.run_coroutine_threadsafe(self.relay.close(), self.loop).result(5)
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(3)
        self.loop.close()


class OnlineIntegrationTests(lan_tests.LanIntegrationTests):
    """Exercise the existing LAN scenarios over a central listener instead."""

    def setUp(self):
        self.relay = RelayHarness()
        super().setUp()
        for app in self.apps:
            app.config.update(online_host='127.0.0.1', online_port=self.relay.port)
            app.connectivity.mode = 'online'

    def tearDown(self):
        try:
            super().tearDown()
        finally:
            self.relay.close()

    def connect(self):
        self.host.go('connection')
        self.host.handle(ButtonEvent(4, 'short'))
        self.guest.go('connection')
        self.guest.handle(ButtonEvent(5, 'short'))
        self.pump(lambda: bool(self.guest.lan.rooms))
        self.guest.handle(ButtonEvent(4, 'short'))
        self.guest.handle(ButtonEvent(8, 'short'))
        self.pump(lambda: self.host.screen == 'mode' and self.guest.lan.synced)

    def test_leaving_notifies_opponent_and_removes_room(self):
        self.connect()
        rid = self.host.lan.link.room.id
        self.guest.lan.close()
        self.pump(lambda: self.host.screen == 'lan_closed')
        self.assertNotIn(rid, self.relay.relay.rooms)

    def test_missing_server_does_not_start_demo_or_local_game(self):
        self.host.config.pop('online_host')
        self.host.go('connection')
        self.host.handle(ButtonEvent(4, 'short'))
        self.assertIsNone(self.host.lan.link)
        self.assertIn('--online-server', self.host.notice)
        self.assertIsNone(self.host.game)


class RelayProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.relay = RelayServer(max_rooms=2)
        self.port = await self.relay.start('127.0.0.1', 0)
        self.clients = []

    async def asyncTearDown(self):
        for _, writer in self.clients:
            writer.close()
        await self.relay.close()

    async def connect(self, **request):
        reader, writer = await asyncio.open_connection('127.0.0.1', self.port)
        self.clients.append((reader, writer))
        writer.write(encode(dict(version=VERSION, **request)))
        await writer.drain()
        reply = await asyncio.wait_for(reader.readline(), 2)
        return reader, writer, json.loads(reply) if reply else None

    async def test_pairing_and_room_isolation_and_reserved_guest(self):
        _, _, room = await self.connect(op='create')
        hr, hw, welcome = await self.connect(op='connect', room=room['id'], role='host', token=room['token'])
        self.assertEqual(welcome['type'], 'welcome')
        _, _, listing = await self.connect(op='list')
        self.assertEqual(listing['rooms'][0]['id'], room['id'])
        gr, gw, _ = await self.connect(op='connect', room=room['id'], role='guest', token='a' * 32)
        self.assertEqual(json.loads(await hr.readline())['type'], 'peer_ready')
        self.assertEqual(json.loads(await gr.readline())['type'], 'peer_ready')
        _, _, other = await self.connect(op='create')
        ordr, _, _ = await self.connect(op='connect', room=other['id'], role='host', token=other['token'])
        state = dict(type='state', revision=7, board=[0] * 9)
        hw.write(encode(state))
        await hw.drain()
        self.assertEqual(json.loads(await asyncio.wait_for(gr.readline(), 2)), state)
        with self.assertRaises(asyncio.TimeoutError):
            await asyncio.wait_for(ordr.readline(), .1)
        gw.close()
        self.assertEqual(json.loads(await asyncio.wait_for(hr.readline(), 2))['type'], 'peer_down')
        _, _, rejected = await self.connect(op='connect', room=room['id'], role='guest', token='b' * 32)
        self.assertIsNone(rejected)
        _, _, restored = await self.connect(op='connect', room=room['id'], role='guest', token='a' * 32)
        self.assertEqual(restored['type'], 'welcome')

    async def test_bad_frames_and_room_limit_do_not_stop_listener(self):
        reader, writer = await asyncio.open_connection('127.0.0.1', self.port)
        self.clients.append((reader, writer))
        writer.write(b'[]\n')
        await writer.drain()
        self.assertEqual(await asyncio.wait_for(reader.read(), 2), b'')
        for _ in range(2):
            _, _, reply = await self.connect(op='create')
            self.assertEqual(reply['type'], 'created')
        _, _, reply = await self.connect(op='create')
        self.assertIsNone(reply)
        _, _, reply = await self.connect(op='list')
        self.assertEqual(reply['type'], 'rooms')
