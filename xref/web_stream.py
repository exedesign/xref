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

"""WebRTC screen mirroring of the board with remote input injection.

Instead of translating every desktop feature to a web equivalent, the
board view itself is streamed as H.264 video to browser clients and
mouse/keyboard events from the browser are injected into the real Qt
view as synthetic events - so the web side always sees exactly what the
desktop shows and every tool works unmodified.
"""

import json
import logging
import threading
import time

from PyQt6 import QtCore, QtGui, QtWidgets

logger = logging.getLogger(__name__)

try:
    from aiortc import RTCPeerConnection, RTCSessionDescription, \
        RTCConfiguration, VideoStreamTrack
    AIO_RTC = True
except ImportError:  # pragma: no cover - optional dependency
    AIO_RTC = False

try:
    from av import VideoFrame
    AV_OK = True
except ImportError:  # pragma: no cover
    AV_OK = False

#: Stream resolution cap (keeps encoder cost low)
STREAM_WIDTH = 1280
STREAM_HEIGHT = 800
#: Frames per second pushed into the encoder
STREAM_FPS = 15


class StreamCamera:
    """The web client's virtual camera over the board scene.

    The browser sends pan/zoom requests; the stream is rendered from
    the requested scene rectangle instead of the desktop's own view,
    so the host's viewport is never disturbed while the web user
    navigates freely.
    """

    def __init__(self, view):
        self.view = view
        # None: follow the desktop view; else a scene rect (x, y, w, h)
        self.rect = None

    def apply(self, msg):
        """Applies a camera op (pan/zoom/reset) from the browser."""

        try:
            self._apply(msg)
        except RuntimeError:
            pass

    def _apply(self, msg):
        op = msg.get('op')
        if op == 'reset':
            self.rect = None
            return
        base = self.current_rect()
        if base is None:
            return
        x0, y0, w, h = base
        cx, cy = x0 + w / 2, y0 + h / 2
        if op == 'zoom':
            factor = max(0.05, min(20.0, float(msg.get('factor', 1.2))))
            # The browser sends 0..1 video coordinates: map them into
            # the camera rect before zooming
            px = x0 + float(msg.get('x', 0.5)) * w
            py = y0 + float(msg.get('y', 0.5)) * h
            w = w / factor
            h = h / factor
            cx = px - (px - cx) / factor
            cy = py - (py - cy) / factor
        elif op == 'pan':
            dx = float(msg.get('dx', 0.0)) * w
            dy = float(msg.get('dy', 0.0)) * h
            cx += dx
            cy += dy
        self.rect = (cx - w / 2, cy - h / 2, w, h)

    def current_rect(self):
        """The scene rectangle the stream should show right now."""

        if self.rect is not None:
            return self.rect
        # follow the desktop viewport
        try:
            rect = self.view.mapToScene(
                self.view.viewport().rect()).boundingRect()
            if rect.width() > 1 and rect.height() > 1:
                return (rect.center().x(), rect.center().y(),
                        rect.width(), rect.height())
        except RuntimeError:
            pass
        return (0.0, 0.0, 800.0, 600.0)


class _GuiCaller(QtCore.QObject):
    """Runs callables on the GUI thread.

    Must be created on the GUI thread itself; creating a QObject with
    a parent from another thread is invalid.
    """

    def call(self, fn):
        self._fn = fn
        ok = QtCore.QMetaObject.invokeMethod(
            self, '_run',
            QtCore.Qt.ConnectionType.BlockingQueuedConnection)
        if not ok:
            # Dead lock / busy loop / shutting down: skip this call
            # instead of blocking the caller forever
            raise _FrameSkipped()

    @QtCore.pyqtSlot()
    def _run(self):
        try:
            self._fn()
        except Exception:  # noqa: BLE001 - one bad call must not kill
            pass


class _FrameSkipped(Exception):
    """The GUI thread could not run the call; skip and carry on."""


class _GuiBridge(QtCore.QObject):
    """A poll timer on the GUI thread that runs queued callables.

    Created lazily on the GUI thread from a QApplication.aboutToQuit-
    safe path: the first call happens while the GUI loop is alive, so
    a zero-interval timer drains the queue there.
    """

    def __init__(self):
        super().__init__()
        self._queue = []
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(0)
        self._timer.timeout.connect(self._drain)
        self._timer.start()

    def _drain(self):
        while self._queue:
            fn, done, failed = self._queue.pop(0)
            try:
                fn()
            except Exception:  # noqa: BLE001
                failed.append(True)
            done.set()

    def submit(self, fn, timeout):
        """Queues fn; returns True when it ran on the GUI thread."""

        done = threading.Event()
        failed = []
        self._queue.append((fn, done, failed))
        # Wake the GUI loop: a posted empty event triggers the timer
        QtCore.QCoreApplication.postEvent(self, QtCore.QEvent(
            QtCore.QEvent.Type.User))
        if done.wait(timeout=timeout):
            return not failed
        return None   # timed out; the call may still run later


_gui_bridge = None


def run_on_gui_thread(fn, timeout=1.0):
    """Runs fn on the GUI thread.

    Raises ``_FrameSkipped`` when the GUI thread cannot service the
    call in time, so video callers can reuse the previous frame.
    """

    global _gui_bridge
    app = QtWidgets.QApplication.instance()
    if app is None:
        raise _FrameSkipped()
    if QtCore.QThread.currentThread() is app.thread():
        fn()
        return
    try:
        bridge_ok = (_gui_bridge is not None
                     and _gui_bridge.thread() is app.thread())
    except RuntimeError:
        bridge_ok = False
    if not bridge_ok:
        raise _FrameSkipped()   # bridge missing: init_gui_bridge first
    result = _gui_bridge.submit(fn, timeout)
    if result is None:
        raise _FrameSkipped()


def init_gui_bridge():
    """Creates the GUI bridge; call once from the GUI thread."""

    global _gui_bridge
    app = QtWidgets.QApplication.instance()
    if app is None:
        return
    if QtCore.QThread.currentThread() is app.thread():
        _gui_bridge = _GuiBridge()


class BoardVideoTrack(VideoStreamTrack):
    """Renders the board from the web client's virtual camera.

    When the camera follows the desktop (default) the widget is
    grabbed directly; once the web user pans/zooms, the scene is
    rendered from the requested rect into an offscreen pixmap, leaving
    the host's viewport untouched.

    Frames are paced to ``STREAM_FPS``: without pacing aiortc pulls
    frames as fast as the loop allows, starving the desktop GUI thread
    and heating the encoder for no visible gain.
    """

    def __init__(self, view, camera=None):
        super().__init__()
        self.view = view
        self.camera = camera
        self._last_hash = None
        self._last_image = None
        self._last_frame = None
        self._last_frame_time = None

    def _grab(self):
        result = {}

        def work():
            try:
                cam_rect = getattr(self.camera, 'rect', None) \
                    if self.camera is not None else None
                if cam_rect is None:
                    pixmap = self.view.grab()
                    image = pixmap.toImage()
                else:
                    x, y, w, h = cam_rect
                    source = QtCore.QRectF(x, y, w, h)
                    pixmap = QtGui.QPixmap(STREAM_WIDTH, STREAM_HEIGHT)
                    pixmap.fill(QtCore.Qt.GlobalColor.black)
                    painter = QtGui.QPainter(pixmap)
                    target = QtCore.QRectF(
                        0, 0, STREAM_WIDTH, STREAM_HEIGHT)
                    sx = target.width() / source.width()
                    sy = target.height() / source.height()
                    s = min(sx, sy)
                    fitted = QtCore.QRectF(
                        (target.width() - source.width() * s) / 2,
                        (target.height() - source.height() * s) / 2,
                        source.width() * s, source.height() * s)
                    self.view.scene.render(painter, fitted, source)
                    painter.end()
                    image = pixmap.toImage()
                if image.width() > STREAM_WIDTH:
                    image = image.scaled(
                        STREAM_WIDTH, STREAM_HEIGHT,
                        QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                        QtCore.Qt.TransformationMode.FastTransformation)
                image = image.convertToFormat(
                    QtGui.QImage.Format.Format_RGB888)
                result['image'] = image
            except RuntimeError:
                result['image'] = None

        run_on_gui_thread(work)
        return result.get('image')

    async def recv(self):
        # Pace to STREAM_FPS: aiortc's default clock would pull frames
        # as fast as the event loop spins (measured 45-50 fps), hogging
        # the GUI thread with grabs and the CPU with encoding
        import asyncio
        now = time.monotonic()
        min_interval = 1.0 / STREAM_FPS
        if self._last_frame_time is not None:
            elapsed = now - self._last_frame_time
            if elapsed < min_interval:
                await asyncio.sleep(min_interval - elapsed)
        self._last_frame_time = time.monotonic()

        pts, time_base = await self.next_timestamp()
        try:
            image = self._grab()
        except (RuntimeError, _FrameSkipped):
            image = None
        if image is None and self._last_image is not None:
            # reuse the last good frame; keeps the stream alive
            image = self._last_image
        if image is None:
            image = QtGui.QImage(4, 4, QtGui.QImage.Format.Format_RGB888)
            image.fill(0)
        key = image.cacheKey()
        if key != self._last_hash:
            self._last_hash = key
            self._last_image = image
            # Convert once per changed frame: QImage -> ndarray ->
            # VideoFrame is expensive and repeats identically when the
            # board did not change (idle board, paused interaction)
            import numpy as np
            h, w = image.height(), image.width()
            bpl = image.bytesPerLine()
            raw = image.constBits().asstring(bpl * h)
            if bpl == w * 3:
                arr = np.frombuffer(raw, dtype=np.uint8,
                                    count=h * w * 3).reshape(h, w, 3)
            else:
                # copy row by row to strip the scanline padding
                arr = np.zeros((h, w, 3), dtype=np.uint8)
                for y in range(h):
                    row = np.frombuffer(
                        raw[y * bpl:(y + 1) * bpl], dtype=np.uint8,
                        count=w * 3).reshape(w, 3)
                    arr[y] = row
            self._last_frame = VideoFrame.from_ndarray(
                arr, format='rgb24')
        frame = self._last_frame
        frame.pts = pts
        frame.time_base = time_base
        return frame


class StreamInputHandler(QtCore.QObject):
    """Turns browser input events into real Qt events on the view.

    Browser clients send scaled coordinates (0..1) plus event data over
    the WebRTC data channel; these are replayed on the Qt thread as
    ordinary mouse/wheel/key events on the board viewport. The host's
    physical cursor is never moved.
    """

    def __init__(self, view, camera=None):
        super().__init__()
        self.view = view
        self.camera = camera
        self._buttons = {}
        # Remote-cursor overlay shown on the desktop for web guests
        self.guest_labels = {}

    def _map(self, nx, ny):
        """Maps normalized video coords to widget coords.

        While the web camera follows the desktop the mapping is direct.
        Once the camera moved over the scene, the point is converted
        into scene coordinates through the camera rect and then into
        the widget's own coordinate system.
        """

        vp = self.view.viewport()
        size = vp.size()
        cam_rect = getattr(self.camera, 'rect', None) \
            if self.camera is not None else None
        if cam_rect is None:
            return QtCore.QPointF(nx * size.width(),
                                  ny * size.height())
        x, y, w, h = cam_rect
        # The stream renders the camera rect letterboxed; approximate
        # the letterbox the same way the track does
        sx = STREAM_WIDTH / w
        sy = STREAM_HEIGHT / h
        s = min(sx, sy)
        fw, fh = w * s, h * s
        # normalized position inside the fitted area
        fx = (nx * STREAM_WIDTH - (STREAM_WIDTH - fw) / 2) / fw
        fy = (ny * STREAM_HEIGHT - (STREAM_HEIGHT - fh) / 2) / fh
        scene_x = x + fx * w
        scene_y = y + fy * h
        widget = self.view.mapFromScene(
            QtCore.QPointF(scene_x, scene_y))
        return QtCore.QPointF(widget)

    def handle(self, msg):
        try:
            self._dispatch(msg)
        except RuntimeError:
            pass  # widget gone

    @staticmethod
    def _qt_modifiers(msg):
        """Browser modifier keys (shift/ctrl/alt) as a Qt flag."""

        mods = QtCore.Qt.KeyboardModifier.NoModifier
        if msg.get('shift'):
            mods |= QtCore.Qt.KeyboardModifier.ShiftModifier
        if msg.get('ctrl'):
            mods |= QtCore.Qt.KeyboardModifier.ControlModifier
        if msg.get('alt'):
            mods |= QtCore.Qt.KeyboardModifier.AltModifier
        return mods

    def _dispatch(self, msg):
        kind = msg.get('kind')
        pos = self._map(msg.get('x', 0), msg.get('y', 0))
        qt_pos = QtCore.QPoint(int(pos.x()), int(pos.y()))
        vp = self.view.viewport()
        mods = self._qt_modifiers(msg)
        guest = msg.get('_guest')
        if kind == 'mouse_move':
            buttons = self._buttons.get('last') or \
                QtCore.Qt.MouseButton.NoButton
            event = QtGui.QMouseEvent(
                QtCore.QEvent.Type.MouseMove, QtCore.QPointF(qt_pos),
                vp.mapToGlobal(QtCore.QPointF(qt_pos)),
                buttons, buttons, mods)
            QtWidgets.QApplication.sendEvent(vp, event)
        elif kind == 'mouse_press':
            button = self._qt_button(msg.get('button', 0))
            self._buttons[msg.get('id')] = button
            self._buttons['last'] = button
            # A web guest starting a stroke: their draw item will be
            # tagged as theirs (delete permission)
            if guest and getattr(self.view.scene, 'draw_mode', False):
                self.view.scene.web_drawer = guest
            event = QtGui.QMouseEvent(
                QtCore.QEvent.Type.MouseButtonPress, QtCore.QPointF(qt_pos),
                vp.mapToGlobal(QtCore.QPointF(qt_pos)), button, button, mods)
            QtWidgets.QApplication.sendEvent(vp, event)
        elif kind == 'mouse_release':
            button = self._buttons.pop(msg.get('id'), None) or \
                self._qt_button(msg.get('button', 0))
            self._buttons.pop('last', None)
            # The stroke is finished; clear the web drawer context
            if guest:
                self.view.scene.web_drawer = None
            event = QtGui.QMouseEvent(
                QtCore.QEvent.Type.MouseButtonRelease,
                QtCore.QPointF(qt_pos), vp.mapToGlobal(QtCore.QPointF(qt_pos)),
                button, QtCore.Qt.MouseButton.NoButton, mods)
            QtWidgets.QApplication.sendEvent(vp, event)
        elif kind == 'wheel':
            delta = int(msg.get('delta', 0))
            event = QtGui.QWheelEvent(
                QtCore.QPointF(qt_pos), vp.mapToGlobal(QtCore.QPointF(qt_pos)),
                QtCore.QPoint(0, delta), QtCore.QPoint(0, delta),
                QtCore.Qt.MouseButton.NoButton, mods,
                QtCore.Qt.ScrollPhase.NoScrollPhase, False)
            QtWidgets.QApplication.sendEvent(vp, event)
        elif kind == 'key':
            # Ctrl-combos (Ctrl+Z, ...) are desktop-only by design
            if msg.get('ctrl') or msg.get('meta'):
                return
            key, text = self._qt_key(msg)
            if key is not None:
                if key == QtCore.Qt.Key.Key_Escape:
                    self._cancel_web_text_edit()
                    return
                if key in (QtCore.Qt.Key.Key_Delete,
                           QtCore.Qt.Key.Key_Backspace) \
                        and self._focus_editor() is None:
                    if not self._guest_may_delete(
                            msg.get('_guest')):
                        return
                    # Delete is a QAction shortcut (window level), so
                    # call the action directly instead of sending a
                    # key event that no one would process
                    self._delete_selection()
                    return
                event = QtGui.QKeyEvent(
                    QtCore.QEvent.Type.KeyPress, key, mods, text)
                # Text editing routes through the scene (focus item);
                # everything else - Delete on the selection included -
                # is handled by the view
                if self._focus_editor() is not None:
                    QtWidgets.QApplication.sendEvent(
                        self.view.scene, event)
                else:
                    QtWidgets.QApplication.sendEvent(self.view, event)
        elif kind == 'keyup':
            # Releases are dropped: text items would repeat the edit
            if msg.get('ctrl') or msg.get('meta'):
                return
            pass

    def _delete_selection(self):
        """Deletes the current selection via the desktop's action."""

        def run():
            try:
                self.view.on_action_delete_items()
            except (AttributeError, RuntimeError) as e:
                logger.info(f'Web delete failed: {e}')

        try:
            run_on_gui_thread(run)
        except _FrameSkipped:
            pass

    def _guest_may_delete(self, guest):
        """Whether the guest may delete the current selection.

        Web guests can only remove items they created themselves
        (uploaded media, their text items). Everything else - the
        host's media, items of other guests - is read-only for them.
        While editing their own text item, Backspace must keep
        working, so an open edit owned by the guest is always allowed.
        """

        try:
            edit_item = getattr(self.view.scene, 'edit_item', None)
            if (edit_item is not None
                    and getattr(edit_item, '_owner', None) == guest):
                return True
            selection = self.view.scene.selectedItems(user_only=True)
            if not selection:
                return False  # nothing selected: key is a no-op anyway
            return all(getattr(item, '_owner', None) == guest
                       for item in selection)
        except (AttributeError, RuntimeError):
            return False

    def _cancel_web_text_edit(self):
        """Cancels a web-started text edit and removes the empty item.

        Web text items are born from a click (not from existing
        content), so cancelling must not leave the placeholder behind.
        """

        def run():
            item = getattr(self.view.scene, 'edit_item', None)
            if item is None:
                return
            try:
                item.exit_edit_mode(commit=False)
                if not item.toPlainText().strip():
                    self.view.scene.removeItem(item)
            except RuntimeError:
                pass

        try:
            run_on_gui_thread(run)
        except _FrameSkipped:
            pass

    def _focus_editor(self):
        """The text item currently in edit mode, if any."""

        try:
            item = self.view.scene.edit_item
            if item is not None and item.edit_mode:
                return item
        except (AttributeError, RuntimeError):
            pass
        return None

    @staticmethod
    def _qt_button(browser_button):
        return {
            0: QtCore.Qt.MouseButton.LeftButton,
            1: QtCore.Qt.MouseButton.MiddleButton,
            2: QtCore.Qt.MouseButton.RightButton,
        }.get(browser_button, QtCore.Qt.MouseButton.LeftButton)

    @staticmethod
    def _qt_key(msg):
        """(Qt key, text) for a browser key message.

        Modifier flags arrive separately (shift/ctrl/alt), so the raw
        key name is mapped on its own; printable characters keep their
        text so text input works on the board.
        """

        name = msg.get('key', '')
        mapping = {
            'Delete': QtCore.Qt.Key.Key_Delete,
            'Backspace': QtCore.Qt.Key.Key_Backspace,
            'Return': QtCore.Qt.Key.Key_Return,
            'Enter': QtCore.Qt.Key.Key_Return,
            'Escape': QtCore.Qt.Key.Key_Escape,
            'Left': QtCore.Qt.Key.Key_Left,
            'Right': QtCore.Qt.Key.Key_Right,
            'Up': QtCore.Qt.Key.Key_Up,
            'Down': QtCore.Qt.Key.Key_Down,
            'Tab': QtCore.Qt.Key.Key_Tab,
            'Home': QtCore.Qt.Key.Key_Home,
            'End': QtCore.Qt.Key.Key_End,
            'PageUp': QtCore.Qt.Key.Key_PageUp,
            'PageDown': QtCore.Qt.Key.Key_PageDown,
            'Shift': QtCore.Qt.Key.Key_Shift,
            'Control': QtCore.Qt.Key.Key_Control,
            'Alt': QtCore.Qt.Key.Key_Alt,
            ' ': QtCore.Qt.Key.Key_Space,
        }
        key = mapping.get(name)
        text = msg.get('text', '') or ''
        if key is not None:
            return key, (text if len(text) <= 1 else '')
        if len(name) == 1:
            from PyQt6.QtGui import QKeySequence
            seq = QKeySequence(name)
            if seq.count():
                return seq[0].key(), name
            return None, text
        return None, text


class BoardStreamServer:
    """Serves a mirroring page and negotiates WebRTC sessions.

    Runs its own asyncio loop in a thread (like the web bridge). The
    video itself flows peer-to-peer; only the initial session setup
    (SDP) goes through the websocket/tunnel.
    """

    def __init__(self, view):
        self.view = view
        self.port = None
        self._loop = None
        self._pcs = set()
        self._files = {}
        self._guest_names = {}  # datachannel -> guest name
        self.camera = StreamCamera(view)
        self.handler = StreamInputHandler(view, self.camera)
        # When constructed on the GUI thread (normal case) the shared
        # bridge is ready immediately
        init_gui_bridge()

    def available(self):
        return AIO_RTC and AV_OK

    def start(self, port=0):
        if not self.available():
            return None
        import asyncio
        from aiohttp import web

        # The GUI bridge must be born on the GUI thread; start() is
        # called from there (CollabSession.start_web_sharing runs on Qt)
        init_gui_bridge()

        loop = asyncio.new_event_loop()
        self._loop = loop
        result = {'port': None}
        server = self

        async def index(request):
            from xref.stream_client import STREAM_HTML
            return web.Response(
                text=STREAM_HTML, content_type='text/html',
                headers={'Cache-Control': 'no-store'})

        async def offer(request):
            params = await request.json()
            offer = RTCSessionDescription(
                sdp=params['sdp'], type=params['type'])
            pc = RTCPeerConnection(
                RTCConfiguration(iceServers=[]))
            server._pcs.add(pc)

            @pc.on('datachannel')
            def on_datachannel(channel):
                @channel.on('message')
                def on_message(message):
                    if not isinstance(message, str):
                        # binary frames are file payload chunks
                        server._binary_chunk(channel, message)
                        return
                    try:
                        msg = json.loads(message)
                    except ValueError:
                        return
                    if msg.get('kind') == 'file':
                        try:
                            server._receive_file(channel, msg)
                        except Exception:  # noqa: BLE001 - keep channel
                            logger.exception('Web file message failed')
                        return
                    if msg.get('kind') == 'camera':
                        # web pan/zoom: moves the virtual camera only;
                        # a busy GUI loop just drops this camera op
                        try:
                            run_on_gui_thread(
                                lambda m=msg: server.camera.apply(m))
                        except _FrameSkipped:
                            pass
                        except Exception:  # noqa: BLE001
                            logger.exception('Camera op failed')
                        return
                    if msg.get('kind') == 'hello':
                        server._guest_joined(channel,
                                             msg.get('name') or 'Misafir')
                        return
                    # Tag every message with its sender first: item
                    # creation paths (text, uploads) need the owner to
                    # stamp the created items
                    msg['_guest'] = server._guest_names.get(channel)
                    if msg.get('kind') == 'insert_text':
                        server._insert_text(msg)
                        return
                    if msg.get('kind') == 'start_text':
                        server._start_text(msg)
                        return
                    if msg.get('kind') == 'action':
                        server._run_action(msg.get('action'))
                        return
                    if msg.get('kind') == 'cursor':
                        server._guest_cursor(channel, msg)
                        return
                    try:
                        server._post_input(msg)
                    except _FrameSkipped:
                        pass
                    except Exception:  # noqa: BLE001 - never kill DC
                        logger.exception('Web input failed')

            @pc.on('connectionstatechange')
            async def on_state():
                if pc.connectionState in ('failed', 'closed'):
                    server._pcs.discard(pc)
                    server._guest_left(channel)
                    await pc.close()

            # Apply the browser's offer first, then attach the video
            # track to the (now existing) video transceiver
            await pc.setRemoteDescription(offer)
            video_ok = False
            for t in pc.getTransceivers():
                if t.kind == 'video':
                    t.sender.replaceTrack(
                        BoardVideoTrack(server.view, server.camera))
                    try:
                        t.direction = 'sendonly'
                    except Exception:  # noqa: BLE001
                        pass
                    video_ok = True
                    break
            if not video_ok:
                pc.addTrack(
                    BoardVideoTrack(server.view, server.camera))
            answer = await pc.createAnswer()
            await pc.setLocalDescription(answer)
            # wait briefly for ICE candidates
            await _gather_complete(pc)
            return web.json_response(
                {'sdp': pc.localDescription.sdp,
                 'type': pc.localDescription.type})

        def run():
            asyncio.set_event_loop(loop)
            app = web.Application()
            app.router.add_get('/', index)
            app.router.add_post('/offer', offer)
            from aiohttp import web_runner
            runner = web_runner.AppRunner(app)
            loop.run_until_complete(runner.setup())
            site = web_runner.TCPSite(runner, '0.0.0.0', port)
            loop.run_until_complete(site.start())
            result['port'] = site._server.sockets[0].getsockname()[1]
            loop.run_forever()

        threading.Thread(target=run, daemon=True).start()
        for _ in range(100):
            if result['port']:
                break
            time.sleep(0.02)
        self.port = result['port']
        return self.port

    def _post_input(self, msg):
        """Hands an input message to the GUI thread.

        A busy GUI loop only means this input event is dropped - the
        connection must survive either way.
        """

        try:
            run_on_gui_thread(lambda: self.handler.handle(msg))
        except _FrameSkipped:
            pass

    # -- Web guests: names, actions, remote cursor -------------------------

    GUEST_COLORS = ['#e11d48', '#7c3aed', '#0891b2', '#65a30d',
                    '#d97706', '#db2777', '#2563eb', '#059669']

    def _guest_joined(self, channel, name):
        """Registers a web guest and shows their name on the desktop."""

        self._guest_names[channel] = name
        color = self.GUEST_COLORS[len(self.handler.guest_labels)
                                  % len(self.GUEST_COLORS)]
        logger.info(f'Web guest joined: {name}')

        def run():
            label = QtWidgets.QLabel(self.view)
            label.setText(name)
            label.setStyleSheet(
                f'background: {color}; color: white; font-size: 12px;'
                'padding: 2px 8px; border-radius: 9px;')
            label.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            label.hide()
            self.handler.guest_labels[channel] = (label, name)

        try:
            run_on_gui_thread(run)
        except _FrameSkipped:
            pass

    def _guest_left(self, channel):
        """Removes a departing guest's cursor label."""

        self._guest_names.pop(channel, None)
        entry = self.handler.guest_labels.pop(channel, None)
        if entry is None:
            return
        label = entry[0]

        def run():
            try:
                label.hide()
                label.deleteLater()
            except RuntimeError:
                pass

        try:
            run_on_gui_thread(run)
        except _FrameSkipped:
            pass

    def _guest_cursor(self, channel, msg):
        """Moves a guest's name label to their pointer position."""

        entry = self.handler.guest_labels.get(channel)
        if entry is None:
            return
        label = entry[0]
        pos = self.handler._map(msg.get('x', 0.5), msg.get('y', 0.5))
        visible = bool(msg.get('inside', True))

        def run():
            try:
                if visible:
                    label.move(QtCore.QPoint(int(pos.x()) + 12,
                                             int(pos.y()) + 14))
                    label.show()
                    label.raise_()
                else:
                    label.hide()
            except RuntimeError:
                pass

        try:
            run_on_gui_thread(run)
        except _FrameSkipped:
            pass

    def _insert_text(self, msg):
        """Inserts a text item at the web user's chosen position."""

        text = (msg.get('text') or '').strip()
        if not text:
            return
        pos = self.handler._map(msg.get('x', 0.5), msg.get('y', 0.5))
        owner = msg.get('_guest')

        def run():
            item = self.view.do_insert_text(text, QtCore.QPoint(
                int(pos.x()), int(pos.y())))
            if item is not None:
                # Ownership: only the creating guest may delete it
                item._owner = owner

        try:
            run_on_gui_thread(run)
        except _FrameSkipped:
            pass

    def _start_text(self, msg):
        """Creates an empty text item in edit mode at the clicked spot.

        The web user then types directly on the board: keystrokes
        arrive as ordinary key events and land in the editing item,
        exactly like typing on the desktop.
        """

        pos = self.handler._map(msg.get('x', 0.5), msg.get('y', 0.5))
        owner = msg.get('_guest')

        def run():
            from xref.items import XRefTextItem
            # A space keeps QGraphicsTextItem from falling back to its
            # "Text" placeholder; the first real keystroke replaces it
            item = XRefTextItem(' ')
            # Ownership: only the creating guest may delete this item
            item._owner = owner
            self.view.scene.addItem(item)
            item.setScale(1 / self.view.get_scale())
            scene_pos = self.view.mapToScene(
                QtCore.QPoint(int(pos.x()), int(pos.y())))
            item.setPos(scene_pos)
            item.setSelected(True)
            item.enter_edit_mode()
            # The scene routes key events to its focus item; make the
            # new editor that focus item so web typing lands in it
            self.view.scene.setFocusItem(item)
            # Select the placeholder so the first typed char clears it
            cursor = item.textCursor()
            cursor.select(QtGui.QTextCursor.SelectionType.Document)
            item.setTextCursor(cursor)
            logger.info('Web guest started typing a text item')

        try:
            run_on_gui_thread(run)
        except _FrameSkipped:
            pass

    def _edit_text(self, msg, channel):
        """Enters edit mode only when the web double-click hits text."""

        pos = self.handler._map(msg.get('x', 0.5), msg.get('y', 0.5))
        result = {'active': False}

        def run():
            from xref.items import XRefTextItem
            point = QtCore.QPoint(int(pos.x()), int(pos.y()))
            item = self.view.itemAt(point)
            if not isinstance(item, XRefTextItem):
                return
            if not item.edit_mode:
                item.enter_edit_mode()
            self.view.scene.setFocusItem(item)
            cursor = item.textCursor()
            cursor.movePosition(
                QtGui.QTextCursor.MoveOperation.End)
            item.setTextCursor(cursor)
            result['active'] = True

        try:
            run_on_gui_thread(run)
        except _FrameSkipped:
            return
        channel.send(json.dumps({
            'kind': 'text_edit', 'active': result['active']}))

    def _run_action(self, name):
        """Runs a desktop action requested from the web toolbar."""

        def run():
            callback = getattr(self.view, f'on_action_{name}', None)
            if callback is not None:
                callback()
                logger.info(f'Web guest ran action {name}')

        try:
            run_on_gui_thread(run)
        except _FrameSkipped:
            pass

    def _receive_file(self, channel, msg):
        """Assembles a browser-dropped file and injects a drop event.

        While the bytes travel, a placeholder item in the media's
        aspect ratio (square when unknown) shows the upload percentage
        on the board at the drop position.
        """

        import tempfile
        import os

        sha = msg.get('id') or str(time.time())
        state = self._files.setdefault(sha, {
            'name': msg.get('name') or 'upload.bin',
            'chunks': [], 'received': 0, 'size': msg.get('size') or 0,
            'channel': channel,
            'owner': self._guest_names.get(channel),
            'x': msg.get('x', 0.5), 'y': msg.get('y', 0.5)})
        if not msg.get('done') and not state.get('placeholder'):
            self._start_placeholder(state, msg)
        logger.info(f'Web upload {sha[:8]}: start {state["name"]} '
                    f'{state["size"]} bytes')
        if msg.get('done'):
            state['done'] = True
            self._end_placeholder(state)
            data = b''.join(state['chunks'])
            directory = os.path.join(tempfile.gettempdir(), 'xref_uploads')
            os.makedirs(directory, exist_ok=True)
            path = os.path.join(directory, os.path.basename(state['name']))
            try:
                with open(path, 'wb') as f:
                    f.write(data)
            except OSError as e:
                logger.info(f'Web upload failed: {e}')
                self._end_placeholder(state)
                del self._files[sha]
                return
            del self._files[sha]
            self._end_placeholder(state)
            logger.info(f'Web upload {sha[:8]}: complete '
                        f'{len(data)} bytes -> {path}')
            channel.send(json.dumps(
                {'kind': 'progress', 'id': sha, 'received': len(data),
                 'size': len(data)}))
            self._inject_drop(path, state['x'], state['y'],
                              owner=state.get('owner'))

    # -- Upload placeholder ------------------------------------------------

    PLACEHOLDER_MAX = 300  # scene units for the longest side

    def _start_placeholder(self, state, msg):
        """Adds a board item showing upload progress at the drop spot.

        The placeholder matches the media's aspect ratio when the
        browser could measure it (w/h in the start message); unknown
        media fall back to a square. It is removed when the upload
        finishes or fails.
        """

        try:
            w = max(1, int(msg.get('w') or 0))
            h = max(1, int(msg.get('h') or 0))
        except (TypeError, ValueError):
            w = h = 0
        if w and h:
            longest = max(w, h)
            w = w * self.PLACEHOLDER_MAX / longest
            h = h * self.PLACEHOLDER_MAX / longest
        else:
            w = h = self.PLACEHOLDER_MAX * 0.6

        def run():
            if state.get('done'):
                return  # upload already finished; no orphan placeholder
            from xref.items import XRefPixmapItem
            image = QtGui.QImage(int(w), int(h),
                                 QtGui.QImage.Format.Format_ARGB32)
            image.fill(QtCore.Qt.GlobalColor.transparent)
            item = XRefPixmapItem(image)
            scene_pos = self._drop_scene_pos(state['x'], state['y'])
            item.setPos(scene_pos.x() - w / 2, scene_pos.y() - h / 2)
            item.set_download_progress(0)
            self.view.scene.addItem(item)
            state['placeholder'] = item

        try:
            run_on_gui_thread(run)
        except _FrameSkipped:
            pass

    def _update_placeholder(self, state):
        """Pushes the current byte count into the placeholder item.

        Throttled: the data channel thread stays free while chunks
        stream in, and the GUI thread only redraws on whole-percent
        changes (every chunk would block both via the GUI bridge).
        """

        item = state.get('placeholder')
        if item is None:
            return
        total = state.get('size') or 0
        percent = (min(99, int(state['received'] * 100 / total))
                   if total > 0 else 0)
        if percent == getattr(item, '_shown_percent', None):
            return
        item._shown_percent = percent

        def run():
            try:
                item.set_download_progress(percent)
            except RuntimeError:  # item deleted meanwhile
                state['placeholder'] = None

        try:
            run_on_gui_thread(run)
        except _FrameSkipped:
            pass

    def _end_placeholder(self, state):
        """Removes the placeholder (upload finished or failed)."""

        item = state.pop('placeholder', None)
        if item is None:
            return

        def run():
            try:
                scene = item.scene()
                if scene is not None:
                    scene.removeItem(item)
            except RuntimeError:
                pass

        try:
            run_on_gui_thread(run)
        except _FrameSkipped:
            pass

    def _drop_scene_pos(self, nx, ny):
        """Scene position for normalized video coordinates."""

        try:
            size = self.view.viewport().size()
            point = QtCore.QPoint(int(nx * size.width()),
                                  int(ny * size.height()))
            return self.view.mapToScene(point)
        except RuntimeError:
            return QtCore.QPointF(0, 0)

    def _binary_chunk(self, channel, payload):
        """Binary frame: ``<upload-id>|<bytes>`` for the given upload."""

        data = bytes(payload)
        sep = data.find(b'|')
        if sep <= 0:
            return
        sha = data[:sep].decode('ascii', 'replace')
        state = self._files.get(sha)
        if state is None:
            return
        state['chunks'].append(data[sep + 1:])
        state['received'] += len(data) - sep - 1
        self._update_placeholder(state)

    def _inject_drop(self, path, nx, ny, owner=None):
        """Delivers an uploaded file to the board as a real drop.

        Media loading is asynchronous (ThreadedIO), so the inserted
        items cannot be diffed at drop time. Instead a pending-tag
        lookup runs shortly after: any new item whose filename matches
        the uploaded file gets the guest's ownership tag.
        """

        def run():
            try:
                size = self.view.viewport().size()
                point = QtCore.QPoint(int(nx * size.width()),
                                      int(ny * size.height()))
                data = QtCore.QMimeData()
                url = QtCore.QUrl.fromLocalFile(path)
                data.setUrls([url])
                event = QtGui.QDropEvent(
                    QtCore.QPointF(point), QtCore.Qt.DropAction.CopyAction,
                    data, QtCore.Qt.MouseButton.LeftButton,
                    QtCore.Qt.KeyboardModifier.NoModifier)
                delivered = QtWidgets.QApplication.sendEvent(
                    self.view, event)
                if not delivered:
                    # QGraphicsView can swallow drops sent to the widget;
                    # call the handler directly instead
                    try:
                        self.view.dropEvent(event)
                    except Exception as e:  # noqa: BLE001
                        logger.info(f'Direct drop failed: {e}')
            except RuntimeError:
                pass
            if owner:
                self._tag_pending_owner(path, owner)

        run_on_gui_thread(run)

    def _tag_pending_owner(self, path, owner, attempts=0):
        """Tags async-loaded media from an upload with the uploader.

        ``do_insert_images`` loads in a thread and adds items to the
        scene moments later; retry until they show up. Large videos
        can take a while, so the window spans ~15s. Every media type
        carries the uploaded file's base name in ``filename`` (image,
        video, pdf, model), so the match is type-independent and
        multiple items from one upload are all tagged.
        """

        import os
        name = os.path.basename(path)

        def check():
            tagged = 0
            try:
                for item in self.view.scene.items():
                    if (hasattr(item, 'save_id')
                            and getattr(item, 'filename', None)
                            and os.path.basename(
                                str(item.filename)) == name
                            and getattr(item, '_owner', None) is None):
                        item._owner = owner
                        tagged += 1
            except RuntimeError:
                return
            if tagged:
                logger.info(f'Tagged {tagged} item(s) "{name}" '
                            f'as {owner}\'s media')
                return
            if attempts < 150:  # ~15s; big videos decode slowly
                QtCore.QTimer.singleShot(
                    100, lambda: self._tag_pending_owner(
                        path, owner, attempts + 1))

        # First call hops to the GUI thread; retries stay there via
        # QTimer (no nested bridge round-trips)
        try:
            app = QtWidgets.QApplication.instance()
        except RuntimeError:
            return
        if app is None:
            return
        if (QtCore.QThread.currentThread() is app.thread()):
            check()
        else:
            try:
                run_on_gui_thread(check)
            except _FrameSkipped:
                pass

    def stop(self):
        import asyncio
        for pc in list(self._pcs):
            try:
                asyncio.run_coroutine_threadsafe(
                    pc.close(), self._loop) if self._loop else None
            except Exception:  # noqa: BLE001
                pass
        self._pcs.clear()
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._loop.stop)
        self._loop = None
        self.port = None


async def _gather_complete(pc, timeout=2.0):
    """Waits until ICE gathering finishes (or times out)."""

    import asyncio
    if pc.iceGatheringState == 'complete':
        return
    done = asyncio.Event()

    @pc.on('icegatheringstatechange')
    def _on():
        if pc.iceGatheringState == 'complete':
            done.set()

    try:
        await asyncio.wait_for(done.wait(), timeout)
    except asyncio.TimeoutError:
        pass
