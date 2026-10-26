"""Native Ping/Pong liveness is independent of browser JavaScript timers."""
import asyncio
import importlib.util
import unittest
from unittest import mock

from tests.test_http import uvicorn
from uvicorn.server import ServerState
from wsproto import events


class MusicProtocolTest(unittest.IsolatedAsyncioTestCase):
    def protocol(self):
        self.assertIsNotNone(importlib.util.find_spec('studio.ws_protocol'), 'native music liveness protocol is implemented')
        from studio.ws_protocol import MusicWebSocketProtocol
        async def app(scope, receive, send):
            pass
        protocol = MusicWebSocketProtocol(uvicorn.Config(app, log_level='critical'), ServerState(), {})
        protocol.transport = mock.Mock()
        protocol.transport.is_closing.return_value = False
        protocol.conn = mock.Mock()
        protocol.conn.send.return_value = b'frame'
        protocol.connections.add(protocol)
        return protocol

    async def test_matched_pong_only_and_original_handler_dispatch(self):
        p = self.protocol()
        request = asyncio.create_task(p.ping(.2))
        await asyncio.sleep(0)
        ping = p.conn.send.call_args.args[0]
        self.assertIsInstance(ping, events.Ping)
        self.assertGreaterEqual(len(ping.payload), 16)
        handlers = ['handle_connect', 'handle_text', 'handle_bytes', 'handle_close', 'handle_ping']
        for handler in handlers:
            setattr(p, handler, mock.Mock())
        messages = [events.Request(host='duck', target='/ws'), events.TextMessage(data='hello'),
                    events.BytesMessage(data=b'bytes'), events.CloseConnection(code=1000),
                    events.Ping(payload=b'client'), events.Pong(payload=b'wrong')]
        p.conn.events.return_value = iter(messages)
        p.handle_events()
        for handler, event in zip(handlers, messages):
            getattr(p, handler).assert_called_once_with(event)
        self.assertFalse(request.done(), 'an unrelated Pong cannot renew the music connection')
        p.conn.events.return_value = iter([events.Pong(payload=ping.payload)])
        p.handle_events()
        self.assertTrue(await request)
        self.assertIsNone(p._pong)

    async def test_missing_pong_times_out_and_replay_cannot_renew_next_ping(self):
        p = self.protocol()
        self.assertFalse(await p.ping(.01))
        old = p.conn.send.call_args.args[0].payload
        request = asyncio.create_task(p.ping(.02))
        await asyncio.sleep(0)
        self.assertNotEqual(p.conn.send.call_args.args[0].payload, old)
        p.conn.events.return_value = iter([events.Pong(payload=old)])
        p.handle_events()
        self.assertFalse(await request)
        self.assertIsNone(p._pong)

    async def test_connection_loss_and_shutdown_finish_pending_ping(self):
        for event in ('connection_lost', 'shutdown'):
            with self.subTest(event=event):
                p = self.protocol()
                request = asyncio.create_task(p.ping(5.))
                await asyncio.sleep(0)
                if event == 'connection_lost':
                    p.connection_lost(None)
                else:
                    p.handshake_complete = True
                    p.shutdown()
                self.assertFalse(await asyncio.wait_for(request, .1))
                self.assertIsNone(p._pong)

    async def test_write_backpressure_is_included_in_the_bounded_probe(self):
        p = self.protocol()
        p.writable.clear()
        self.assertFalse(await p.ping(.01))
        p.conn.send.assert_not_called()
