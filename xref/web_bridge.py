#!/usr/bin/env python3

# This file is part of XRef.
#
# XRef is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# XRef is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with XRef.  If not, see <https://www.gnu.org/licenses/>.

"""Web sharing bridge: an aiohttp server that mirrors a collab session.

Peers without XRef can join a shared board with a browser: the host
serves a single-file HTML client and bridges the existing JSON
``snapshot``/``ops`` protocol to a WebSocket, so desktop users and
browser users edit the same board together.
"""

import asyncio
import base64
import json
import logging

from PyQt6 import QtCore

logger = logging.getLogger(__name__)

try:
    from aiohttp import web
    AIOHTTP_AVAILABLE = True
except ImportError:  # pragma: no cover - optional dependency
    AIOHTTP_AVAILABLE = False


class WebBridge(QtCore.QObject):
    """Bridges a CollabSession to browser clients over WebSocket."""

    #: Emitted on the Qt thread with a JSON payload from a web client
    web_message = QtCore.pyqtSignal(dict)

    def __init__(self, collab_session, code):
        super().__init__()
        self.session = collab_session
        self.code = code
        self.clients = set()
        self.runner = None
        self.port = None
        self._loop = None
        # Precomputed on the Qt thread; the server thread only reads these
        self.snapshot_json = '{}'
        self.pending_assets = []

    # -- Lifecycle ----------------------------------------------------------

    def start(self, port=0):
        """Starts the HTTP server. Returns the chosen port or None."""

        if not AIOHTTP_AVAILABLE:
            logger.info('Web sharing needs the aiohttp package')
            return None
        try:
            loop = asyncio.new_event_loop()
        except OSError:
            return None
        self._loop = loop

        result = {'port': None}

        def run_server():
            asyncio.set_event_loop(loop)
            app = web.Application()
            app.router.add_get('/', self._handle_index)
            app.router.add_get('/ws', self._handle_ws)
            app.router.add_get('/state', self._handle_state)
            self.runner = web.AppRunner(app)
            loop.run_until_complete(self.runner.setup())
            site = web.TCPSite(self.runner, '0.0.0.0', port)
            loop.run_until_complete(site.start())
            result['port'] = site._server.sockets[0].getsockname()[1]
            loop.run_forever()

        import threading
        self._thread = threading.Thread(target=run_server, daemon=True)
        self._thread.start()
        # Give the server a moment to bind
        import time
        for _ in range(50):
            if result['port']:
                break
            time.sleep(0.02)
        self.port = result['port']
        if self.port:
            self.web_message.connect(self._on_client_message)
            # Prime the cache right away (start() runs on the Qt thread)
            self.refresh_cache()
            # Keep the snapshot and pending assets fresh from the Qt
            # thread; the server thread must never touch the scene
            self._refresh_timer = QtCore.QTimer()
            self._refresh_timer.timeout.connect(self.refresh_cache)
            self._refresh_timer.start(5000)
        return self.port

    def refresh_cache(self):
        """Recomputes snapshot/asset data (runs on the Qt thread).

        Thumbnails are cached per pixmap, so only the first pass is
        expensive; subsequent refreshes are cheap dictionary lookups.
        """

        try:
            snapshot = self.session.web_snapshot()
            text = json.dumps(snapshot, separators=(',', ':'))
            assets = self.session.web_pending_assets()
            self.snapshot_json = text
            self.pending_assets = assets
        except RuntimeError:  # scene already gone
            pass
        except Exception as e:  # noqa: BLE001 - keep old snapshot
            logger.warning(
                f'Web snapshot refresh failed: '
                f'{type(e).__name__}: {e}')

    def stop(self):
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._loop.stop)
        self._loop = None
        self.clients.clear()
        self.port = None

    # -- Server handlers ------------------------------------------------------

    async def _handle_index(self, request):
        from xref.web_client import CLIENT_HTML
        return web.Response(
            text=CLIENT_HTML, content_type='text/html',
            headers={'Cache-Control': 'no-store, no-cache, must-revalidate',
                     'Pragma': 'no-cache'})

    async def _handle_state(self, request):
        """The precomputed snapshot for HTTP polling fallback clients."""

        if request.query.get('code', '') != self.code:
            return web.json_response(
                {'type': 'error', 'message': 'wrong session code'},
                status=403)
        return web.Response(text=self.snapshot_json or '{}',
                            content_type='application/json',
                            headers={'Cache-Control': 'no-store'})

    async def _handle_ws(self, request):
        ws = web.WebSocketResponse(max_msg_size=64 * 1024 * 1024)
        await ws.prepare(request)
        code = request.query.get('code', '')
        if code != self.code:
            await ws.send_json({'type': 'error',
                                'message': 'wrong session code'})
            await ws.close()
            return ws
        self.clients.add(ws)
        try:
            # Snapshot and assets are precomputed on the Qt thread
            try:
                await ws.send_str(self.snapshot_json or '{}')
                for data, name, kind in self.pending_assets:
                    await self._stream_asset(ws, data, name, kind)
            except (ConnectionResetError, ConnectionError, RuntimeError):
                return ws
            async for msg in ws:
                if msg.type.name == 'TEXT':
                    try:
                        payload = json.loads(msg.data)
                    except ValueError:
                        continue
                    if payload.get('type') == 'refresh':
                        # Serve the precomputed snapshot (Qt thread keeps
                        # it fresh via a timer)
                        try:
                            await ws.send_str(self.snapshot_json or '{}')
                        except (ConnectionResetError, ConnectionError,
                                RuntimeError):
                            break
                        continue
                    # Hand the op to the Qt thread via a signal
                    self.web_message.emit(payload)
                elif msg.type.name in ('CLOSE', 'ERROR'):
                    break
        finally:
            self.clients.discard(ws)
        return ws

    async def _stream_asset(self, ws, data, name, kind):
        """Sends one large asset to a browser in chunks, with progress."""

        import base64 as _b64
        from xref.collab import ASSET_CHUNK_SIZE, _asset_meta, _sha256
        sha = _sha256(data)
        meta = _asset_meta(data, name, kind)
        await ws.send_str(json.dumps(
            {'type': 'asset_begin', 'sha': sha,
             'size': len(data), 'meta': meta}))
        for offset in range(0, len(data), ASSET_CHUNK_SIZE):
            chunk = data[offset:offset + ASSET_CHUNK_SIZE]
            await ws.send_str(json.dumps(
                {'type': 'asset_chunk', 'sha': sha,
                 'data': _b64.b64encode(chunk).decode('ascii')}))
            # Yield to the event loop so handshake/ops keep flowing
            await asyncio.sleep(0)
        await ws.send_str(json.dumps(
            {'type': 'asset_end', 'sha': sha, 'meta': meta}))

    def _on_client_message(self, payload):
        """Applies a web client's ops (runs on the Qt thread)."""

        self.session.apply_web_message(payload)

    # -- Sending to clients ------------------------------------------------------

    def broadcast(self, payload):
        """Sends a JSON payload to all connected browsers."""

        if not self.clients or self._loop is None:
            return
        data = json.dumps(payload, separators=(',', ':'))
        self._loop.call_soon_threadsafe(
            lambda: asyncio.ensure_future(self._broadcast_async(data)))

    async def _broadcast_async(self, data):
        dead = []
        for ws in list(self.clients):
            try:
                await ws.send_str(data)
            except Exception:  # noqa: BLE001 - disconnected client
                dead.append(ws)
        for ws in dead:
            self.clients.discard(ws)
