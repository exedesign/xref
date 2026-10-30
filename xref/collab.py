
"""Shared whiteboard sessions between XRef installations.

Inspired by PowerToys' "Mouse Without Borders" (pairing separate
installations so they act as one workspace), but for the canvas instead
of the pointer: one XRef acts as the **host**, the others **join** it
and everyone edits the same board.

Pairing is done with a **session code** instead of an IP address:

* The host generates a random code (e.g. ``K7M4Q-9PXE2``) and shows it.
* The joiner types the code; the app finds the host on the local network
  via a UDP broadcast that contains only a PBKDF2 hash of the code.
* The TCP handshake authenticates *both* sides with an HMAC proof derived
  from the code, so the code itself is never sent over the network.
* After the handshake every message is encrypted and authenticated
  (SHAKE-256 keystream + HMAC-SHA256 tag), so the shared board is not
  readable on the wire.
* The host can additionally be asked to approve each new peer.

Protocol (newline-delimited JSON over TCP):

* ``hello``    - client proves it knows the code (HMAC proof, plaintext)
* ``welcome``  - host proves it knows the code as well
* ``denied``   - host refused the peer (wrong code or declined)
* sealed messages (encrypted + authenticated): ``snapshot``, ``ops``, ``bye``

Local changes are detected by periodically diffing the scene (250 ms), so
every code path (insert, move, transform, text edit, drawing, opacity,
video position, ...) participates without being wired up individually.
Conflicts resolve last-write-wins, which is appropriate for a shared mood
board.
"""

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import socket
import time
import uuid

from PyQt6 import QtCore, QtGui, QtNetwork

from xref.i18n import tr
from xref.config import XRefSettings
from xref.items import XRefDrawItem, XRefModelItem, XRefPdfItem, \
    XRefPixmapItem, XRefTextItem, XRefVideoItem, item_registry


logger = logging.getLogger(__name__)

DEFAULT_PORT = 48620
DISCOVERY_PORT = 48621
PROTOCOL_VERSION = 2
SYNC_INTERVAL_MS = 250

# Pairing code: 10 characters from an unambiguous alphabet (no 0/O/1/I),
# displayed as XXXXX-XXXXX
CODE_ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'
CODE_LENGTH = 10
PBKDF2_ITERATIONS = 120000
KDF_SALT = b'xref-collab-v2'
DISCOVERY_PREFIX = b'xref-discover|'
OFFER_PREFIX = b'xref-offer|'

MAX_PEERS = 16
# Host migration: the successor starts immediately, everyone else keeps
# trying to reconnect before considering taking over themselves
RECOVER_DELAY_MS = 900
RECOVER_RETRY_MS = 1200
RECOVER_ATTEMPTS = 10
# Media is shared in its *original* form. Small files travel inline with the
# item state, larger ones are streamed in chunks.
ASSET_INLINE_LIMIT = 4 * 1024 * 1024
ASSET_CHUNK_SIZE = 256 * 1024
MAX_ASSET_SIZE = 256 * 1024 * 1024
MAX_LINE_BYTES = 96 * 1024 * 1024
MAX_FAILED_ATTEMPTS = 5
FAILED_ATTEMPT_WINDOW = 600  # seconds


# -- Pairing code / crypto -------------------------------------------------

def normalize_code(code):
    """Normalises a user-entered session code.

    Spaces and dashes are dropped and look-alike characters are mapped to
    the ones used by the alphabet, so codes are easy to type.
    """

    if not code:
        return None
    cleaned = ''.join(ch for ch in str(code).upper() if ch.isalnum())
    cleaned = cleaned.replace('0', 'O').replace('1', 'I')
    return cleaned or None


def format_code(code):
    """Formats a code for display, e.g. ``K7M4Q-9PXE2``."""

    code = normalize_code(code)
    if not code:
        return ''
    if len(code) <= 5:
        return code
    return f'{code[:5]}-{code[5:]}'


def generate_code():
    """A fresh random pairing code."""

    return ''.join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))


def derive_keys(code, iterations=PBKDF2_ITERATIONS):
    """Derives the auth/encryption/MAC keys from the session code.

    The code is stretched with PBKDF2 so a network capture can't be used
    to brute-force it (the code itself is never transmitted).
    """

    code = normalize_code(code)
    if not code:
        return None
    master = hashlib.pbkdf2_hmac('sha256', code.encode('utf-8'), KDF_SALT,
                                 iterations, dklen=32)
    return {
        'auth': hmac.new(master, b'bee-auth', hashlib.sha256).digest(),
        'enc': hmac.new(master, b'bee-enc', hashlib.sha256).digest(),
        'mac': hmac.new(master, b'bee-mac', hashlib.sha256).digest(),
    }


def discovery_hash(keys):
    """The identifier broadcast for discovery (a one-way code hash)."""

    return hmac.new(keys['auth'], b'bee-discovery',
                    hashlib.sha256).hexdigest()[:32]


def _proof(keys, *parts):
    message = b'\x00'.join(
        part if isinstance(part, bytes) else str(part).encode('utf-8')
        for part in parts)
    return hmac.new(keys['auth'], message, hashlib.sha256).hexdigest()


def derive_session_keys(keys, client_nonce, server_nonce):
    """Binds the keys to one handshake (prevents replay of old frames)."""

    seed = f'{client_nonce}|{server_nonce}'.encode('utf-8')
    return {
        'enc': hmac.new(keys['enc'], seed, hashlib.sha256).digest(),
        'mac': hmac.new(keys['mac'], seed, hashlib.sha256).digest(),
        'auth': keys['auth'],
    }


def _xor_bytes(left, right):
    length = len(left)
    return (int.from_bytes(left, 'big')
            ^ int.from_bytes(right, 'big')).to_bytes(length, 'big')


def seal(keys, payload):
    """Encrypts and authenticates a message payload."""

    data = json.dumps(payload, separators=(',', ':')).encode('utf-8')
    nonce = os.urandom(16)
    stream = hashlib.shake_256(keys['enc'] + nonce).digest(len(data))
    cipher = _xor_bytes(data, stream)
    tag = hmac.new(keys['mac'], nonce + cipher, hashlib.sha256).digest()
    return {
        'n': nonce.hex(),
        'd': base64.b64encode(cipher).decode('ascii'),
        'm': tag.hex(),
    }


def unseal(keys, message):
    """Verifies and decrypts a sealed message; None if invalid."""

    if not isinstance(message, dict):
        return None
    try:
        nonce = bytes.fromhex(message['n'])
        cipher = base64.b64decode(message['d'])
        tag = bytes.fromhex(message['m'])
    except (KeyError, TypeError, ValueError):
        return None
    if len(nonce) != 16:
        return None
    expected = hmac.new(keys['mac'], nonce + cipher,
                        hashlib.sha256).digest()
    if not hmac.compare_digest(tag, expected):
        logger.info('Collaboration: rejected a message with a bad tag')
        return None
    stream = hashlib.shake_256(keys['enc'] + nonce).digest(len(cipher))
    data = _xor_bytes(cipher, stream)
    try:
        return json.loads(data.decode('utf-8'))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None

# -- Serialisation ---------------------------------------------------------

def _sha256(data):
    return hashlib.sha256(data).hexdigest()


def _png_bytes(image):
    """Encodes an image losslessly as PNG."""

    buffer = QtCore.QBuffer()
    buffer.open(QtCore.QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, 'PNG')
    return bytes(buffer.data())


def asset_cache_dir():
    """Where media received from peers is stored."""

    base = QtCore.QStandardPaths.writableLocation(
        QtCore.QStandardPaths.StandardLocation.AppLocalDataLocation)
    if not base:
        base = os.path.join(os.path.expanduser('~'), '.xref')
    path = os.path.join(base, 'shared_assets')
    try:
        os.makedirs(path, exist_ok=True)
    except OSError:
        return os.path.join(os.path.expanduser('~'), '.xref-assets')
    return path


def item_asset_bytes(item):
    """The original bytes of an item's media, or None.

    The original file is preferred so that every machine receives exactly
    what was imported. Images without a source file (pasted, edited) are
    sent as lossless PNG of their full pixels; crop/grayscale are shared
    as flags and re-applied on the receiving side.
    """

    if item.TYPE == XRefPixmapItem.TYPE:
        original = getattr(item, 'original_bytes', None)
        if original:
            return original
        filename = getattr(item, 'filename', None)
        if filename and os.path.isfile(filename):
            try:
                with open(filename, 'rb') as f:
                    return f.read()
            except OSError:
                pass
        image = item.pixmap().toImage()
        if image.isNull():
            return None
        return _png_bytes(image)
    if item.TYPE == XRefModelItem.TYPE:
        return item.model_to_bytes() or None
    if item.TYPE == XRefModelItem.TYPE:
        item.model_from_bytes(data)
        item.release_mesh()
        item.update()
        return True
    if item.TYPE == XRefPdfItem.TYPE:
        return item.pdf_to_bytes() or None
    if item.TYPE == XRefVideoItem.TYPE:
        if item.has_source_file():
            try:
                with open(item.video_path, 'rb') as f:
                    return f.read()
            except OSError:
                return None
        return getattr(item, 'video_bytes', None)
    return None


def _asset_meta(data, name, kind):
    return {
        'sha': _sha256(data),
        'size': len(data),
        'name': name or (f'{kind}.bin'),
        'kind': kind,
    }


def store_asset(sha, data, name):
    """Stores media in the local asset cache and returns its path."""

    path = find_cached_asset(sha)
    if path:
        return path
    extension = os.path.splitext(name or '')[1].lower()
    if not extension or len(extension) > 6:
        extension = ''
    path = os.path.join(asset_cache_dir(), sha + extension)
    try:
        with open(path, 'wb') as f:
            f.write(data)
    except OSError as e:
        logger.info(f'Collaboration: could not store media: {e}')
        return None
    return path


def find_cached_asset(sha):
    """The cached file for an asset hash, or None."""

    if not sha:
        return None
    folder = asset_cache_dir()
    try:
        for entry in os.listdir(folder):
            if entry.startswith(sha):
                return os.path.join(folder, entry)
    except OSError:
        pass
    return None


def _state_media_bytes(state, kind):
    """Media bytes contained in (or already cached for) an item state."""

    asset = state.get('asset') or {}
    inline = asset.get('inline')
    if inline:
        try:
            return base64.b64decode(inline)
        except (ValueError, TypeError):
            return None
    sha = asset.get('sha')
    if not sha:
        return None
    path = find_cached_asset(sha)
    if path:
        try:
            with open(path, 'rb') as f:
                return f.read()
        except OSError:
            return None
    return None


def item_state(item, include_image=True):
    """The shareable state of an item."""

    state = {
        'type': getattr(item, 'TYPE', 'error'),
        'x': item.pos().x(),
        'y': item.pos().y(),
        'z': item.zValue(),
        'scale': item.scale(),
        'rotation': item.rotation(),
        'flip': item.flip(),
        'opacity': item.opacity(),
    }
    if item.TYPE == XRefPixmapItem.TYPE:
        state['filename'] = item.filename
        size = item.pixmap().size()
        state['size'] = [size.width(), size.height()]
        state['grayscale'] = bool(getattr(item, 'grayscale', False))
        crop = getattr(item, 'crop', None)
        if crop is not None:
            state['crop'] = [crop.x(), crop.y(), crop.width(),
                             crop.height()]
        if include_image:
            data = item_asset_bytes(item)
            if data:
                state['asset'] = _asset_meta(data, item.filename, 'image')
                if len(data) <= ASSET_INLINE_LIMIT:
                    state['asset']['inline'] = base64.b64encode(
                        data).decode('ascii')
    elif item.TYPE == XRefModelItem.TYPE:
        state['filename'] = item.filename
        state['size'] = list(item.size())
        yaw, pitch, zoom = item.current_view()
        state['yaw'] = round(yaw, 2)
        state['pitch'] = round(pitch, 2)
        state['zoom'] = round(zoom, 4)
        if include_image:
            data = item_asset_bytes(item)
            if data:
                state['asset'] = _asset_meta(
                    data, item.filename, 'model')
                if len(data) <= ASSET_INLINE_LIMIT:
                    state['asset']['inline'] = base64.b64encode(
                        data).decode('ascii')
    elif item.TYPE == XRefPdfItem.TYPE:
        state['filename'] = item.filename
        state['size'] = list(item.size())
        state['pages'] = item.pages
        if include_image:
            # The page is only shared with the initial state, so peers
            # can browse independently afterwards
            state['page'] = int(item.current_page)
            data = item_asset_bytes(item)
            if data:
                state['asset'] = _asset_meta(data, item.filename, 'pdf')
                if len(data) <= ASSET_INLINE_LIMIT:
                    state['asset']['inline'] = base64.b64encode(
                        data).decode('ascii')
    elif item.TYPE == XRefVideoItem.TYPE:
        state['filename'] = item.filename
        state['size'] = list(item.size)
        state['duration'] = item.duration
        state['position'] = int(item._current_position)
        state['volume'] = round(item.volume, 3)
        state['muted'] = item.is_muted
        if include_image:
            data = item_asset_bytes(item)
            if data:
                state['asset'] = _asset_meta(data, item.filename, 'video')
                if len(data) <= ASSET_INLINE_LIMIT:
                    state['asset']['inline'] = base64.b64encode(
                        data).decode('ascii')
    elif item.TYPE == XRefTextItem.TYPE:
        state['text'] = item.toPlainText()
        width = item.textWidth()
        if width and width > 0:
            state['text_width'] = width
    elif item.TYPE == XRefDrawItem.TYPE:
        state['data'] = item.get_extra_save_data()
    else:
        state['text'] = getattr(item, 'toPlainText', lambda: '')()
    return state


def _apply_geometry(item, state):
    item.setPos(state.get('x', 0), state.get('y', 0))
    item.setZValue(state.get('z', 0))
    if state.get('scale'):
        item.setScale(state['scale'])
    item.setRotation(state.get('rotation', 0))
    item.setOpacity(state.get('opacity', 1))
    if state.get('flip', 1) == -1 and item.flip() != -1:
        item.do_flip()


def create_item_from_state(state):
    """Creates a scene item from a state dictionary."""

    itype = state.get('type')
    if itype == XRefPixmapItem.TYPE:
        data = _state_media_bytes(state, 'image')
        image = QtGui.QImage()
        if data:
            image.loadFromData(data)
        item = XRefPixmapItem(image, state.get('filename'))
        if data:
            item.original_bytes = data
    elif itype == XRefVideoItem.TYPE:
        size = state.get('size')
        asset = state.get('asset') or {}
        cached = find_cached_asset(asset.get('sha'))
        if cached is None:
            data = _state_media_bytes(state, 'video')
            if data:
                cached = store_asset(asset.get('sha'),
                                     data, state.get('filename'))
        video_path = cached or state.get('video_path')
        item = XRefVideoItem(
            video_path=video_path,
            filename=state.get('filename'),
            size=tuple(size) if size else None,
            duration=state.get('duration', -1))
        try:
            item._current_position = int(state.get('position', 0))
            item._display_position = item._current_position
            item._volume = float(state.get('volume', 1.0))
            item._muted = bool(state.get('muted', False))
        except (TypeError, ValueError):
            pass
    elif itype == XRefModelItem.TYPE:
        size = state.get('size')
        item = XRefModelItem(
            filename=state.get('filename'),
            size=tuple(size) if size else None,
            yaw=float(state.get('yaw') or 30),
            pitch=float(state.get('pitch') or 20),
            zoom=float(state.get('zoom') or 1.0))
        data = _state_media_bytes(state, 'model')
        if data:
            item.model_from_bytes(data)
        item.setOpacity(state.get('opacity', 1))
    elif itype == XRefPdfItem.TYPE:
        size = state.get('size')
        item = XRefPdfItem(
            filename=state.get('filename'),
            size=tuple(size) if size else None,
            pages=int(state.get('pages') or 0),
            page=int(state.get('page') or 0))
        data = _state_media_bytes(state, 'pdf')
        if data:
            item.pdf_from_bytes(data)
        item.setOpacity(state.get('opacity', 1))
    elif itype == XRefTextItem.TYPE:
        item = XRefTextItem(state.get('text', ''),
                           text_width=state.get('text_width'))
    elif itype == XRefDrawItem.TYPE:
        item = XRefDrawItem.create_from_data(data=state.get('data', {}))
    else:
        cls = item_registry.get(itype)
        if cls is None:
            logger.info(f'Cannot create item of unknown type {itype}')
            return None
        item = cls.create_from_data(data=state)
    item._collab_state = dict(state)
    _apply_media_flags(item, state)
    _apply_geometry(item, state)
    return item


def _apply_media_flags(item, state):
    """Applies crop/grayscale (shared as flags, not baked into pixels)."""

    if item.TYPE != XRefPixmapItem.TYPE:
        return
    crop = state.get('crop')
    if crop and len(crop) == 4:
        item.crop = QtCore.QRectF(*crop)
    if 'grayscale' in state:
        item.grayscale = bool(state['grayscale'])


def update_item_from_state(item, state):
    """Applies a changed state to an existing item."""

    _apply_geometry(item, state)
    if item.TYPE == XRefTextItem.TYPE:
        text = state.get('text', '')
        if item.toPlainText() != text:
            item.setPlainText(text)
        width = state.get('text_width')
        if width and item.textWidth() != width:
            item.setTextWidth(width)
    elif item.TYPE == XRefDrawItem.TYPE:
        data = state.get('data') or {}
        points = [QtCore.QPointF(x, y) for x, y in data.get('points', [])]
        if [list(p) for p in item.points] != [[p.x(), p.y()] for p in points]:
            item._points = points
            color = data.get('stroke_color')
            if color:
                item.set_stroke_color(QtGui.QColor(*color))
            if data.get('stroke_width'):
                item.set_stroke_width(data['stroke_width'])
            item._rebuild_path()
    elif item.TYPE == XRefPixmapItem.TYPE:
        item._collab_state = dict(state)
        _apply_media_flags(item, state)
        size = state.get('size')
        if size and len(size) == 2:
            current = item.pixmap().size()
            if [current.width(), current.height()] != list(size):
                data = _state_media_bytes(state, 'image')
                if data:
                    apply_asset_to_item(item, data)
    elif item.TYPE == XRefVideoItem.TYPE:
        position = state.get('position')
        if position is not None and int(position) != item._current_position:
            item.set_position(int(position))


def apply_asset_to_item(item, data, path=None):
    """Installs received media into an item (original bytes)."""

    if not data:
        return False
    if item.TYPE == XRefPixmapItem.TYPE:
        item.pixmap_from_bytes(data)
        item.original_bytes = data
        state = getattr(item, '_collab_state', None)
        if state:
            _apply_media_flags(item, state)
        item.update()
        return True
    if item.TYPE == XRefPdfItem.TYPE:
        item.pdf_from_bytes(data)
        item.release_document()
        item.set_page(item.current_page)
        item.update()
        return True
    if item.TYPE == XRefVideoItem.TYPE:
        if path is None:
            path = os.path.join(asset_cache_dir(), _sha256(data))
        if not os.path.isfile(path):
            try:
                with open(path, 'wb') as f:
                    f.write(data)
            except OSError as e:
                logger.info(f'Could not cache shared video: {e}')
                return False
        item.video_path = path
        item.video_bytes = None
        item.release_player()
        item._load_preview()
        item.update()
        return True
    return False


def _diff_state(state):
    """State without the (expensive) image payload, used for diffs."""

    return {key: value for key, value in state.items() if key != 'image'}


class CollabSession(QtCore.QObject):
    """Shares one scene with other XRef installations.

    Pairing happens with a short session **code**: the joiner types the
    code shown by the host, the app finds the host on the local network
    (UDP broadcast of a one-way code hash) and then authenticates both
    sides with HMAC proofs. The code is never sent over the wire and all
    board data afterwards is encrypted and authenticated.
    """

    status_changed = QtCore.pyqtSignal(str)
    peers_changed = QtCore.pyqtSignal(int)
    board_replaced = QtCore.pyqtSignal()
    #: Emitted when this peer took over sharing after the host went away
    became_host = QtCore.pyqtSignal()

    def __init__(self, scene, name='XRef user', parent=None):
        super().__init__(parent)
        self.scene = scene
        self.name = name or 'XRef user'
        self.peer_id = uuid.uuid4().hex[:8]
        self.is_host = False
        self.code = None
        self.session_code = None
        self.server = None
        self.discovery = None
        self.socket = None
        self.peers = {}
        self.port = None
        self.status = 'Not sharing'
        self.last_error = ''
        # Optional callable(name, address) -> bool; when set, the host has
        # to approve every new peer
        self.approval_callback = None
        self._keys = None
        self._session_keys = None
        self._client_nonce = None
        self._handshake_done = False
        self._handshake_error = ''
        self._buffers = {}
        self._applying = False
        self._known = {}
        self._links = set()
        self._got_snapshot = False
        self._failed = {}
        # Media transfer (original bytes)
        self._asset_buffers = {}
        self._asset_meta = {}
        self._pending_assets = {}
        # Host migration
        self._handover_order = []
        self._session_ended = False
        self._recover_timer = None
        self._recover_rank = 0
        self._recover_attempts = 0
        self._sent_assets = set()
        self._discovery_timer = None
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(SYNC_INTERVAL_MS)
        self._timer.timeout.connect(self.sync)

    # -- State -------------------------------------------------------------

    def is_active(self):
        return self.is_host or self.socket is not None

    def peer_count(self):
        if self.is_host:
            return sum(1 for info in self.peers.values()
                       if info.get('keys'))
        return 1 if self.socket is not None and self._handshake_done else 0

    def _set_status(self, status):
        self.status = status
        logger.info(f'Collaboration: {status}')
        self.status_changed.emit(status)

    def _collab_id(self, item):
        cid = getattr(item, 'collab_id', None)
        if not cid:
            cid = uuid.uuid4().hex
            item.collab_id = cid
        return cid

    def _items_by_id(self):
        return {self._collab_id(item): item
                for item in self.scene.items_for_save()}

    def _collect_state(self, include_image=True):
        items = {}
        for cid, item in self._items_by_id().items():
            items[cid] = item_state(item, include_image=include_image)
        links = set()
        for source, target in self.scene.active_links():
            links.add((self._collab_id(source), self._collab_id(target)))
        return items, links

    # -- Hosting -----------------------------------------------------------

    def host(self, port=None, code=None):
        """Starts sharing the board; returns the session code or None."""

        if self.is_active():
            self.leave()
        self.last_error = ''
        keys = derive_keys(code) if code else None
        if keys is None:
            code = generate_code()
            keys = derive_keys(code)
        self.code = normalize_code(code)
        self.session_code = format_code(self.code)
        self._keys = keys

        server = QtNetwork.QTcpServer(self)
        if port is None:
            listening = server.listen(
                QtNetwork.QHostAddress(
                    QtNetwork.QHostAddress.SpecialAddress.AnyIPv4),
                DEFAULT_PORT)
            if not listening:
                # Port probably in use; any free port will do because the
                # joiner learns it during discovery
                listening = server.listen(
                    QtNetwork.QHostAddress(
                        QtNetwork.QHostAddress.SpecialAddress.AnyIPv4), 0)
        else:
            listening = server.listen(
                QtNetwork.QHostAddress(
                    QtNetwork.QHostAddress.SpecialAddress.AnyIPv4), port)
        if not listening:
            self.last_error = tr('Could not start sharing: {error}',
                                 error=server.errorString())
            self._set_status(self.last_error)
            server.deleteLater()
            self._keys = None
            return None
        server.newConnection.connect(self._on_new_connection)
        self.server = server
        self.is_host = True
        self.port = server.serverPort()

        self._start_discovery()
        items, links = self._collect_state(include_image=False)
        self._known = {cid: _diff_state(state)
                       for cid, state in items.items()}
        self._links = links
        self._timer.start()
        self._set_status(self._host_status())
        return self.session_code

    def _announce_handover(self):
        """Tells every peer who takes over if the host disappears."""

        if not self.is_host:
            return
        order = [info.get('id') for info in self.peers.values()
                 if info.get('id')]
        self._broadcast({'type': 'handover', 'order': order})

    def _host_status(self):
        peers = self.peer_count()
        if not peers:
            return tr('Sharing · code {code} · waiting for peers',
                      code=self.session_code)
        return tr('Sharing · code {code} · {count} peer(s)',
                  code=self.session_code, count=peers)

    def _start_discovery(self):
        """Listens for discovery requests from joiners (UDP)."""

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(('', DISCOVERY_PORT))
            sock.setblocking(False)
        except OSError as e:
            logger.info(f'Collaboration: discovery unavailable ({e}); '
                        'peers on other machines may not find the board')
            self.discovery = None
            return
        self.discovery = sock
        self._discovery_timer = QtCore.QTimer(self)
        self._discovery_timer.setInterval(100)
        self._discovery_timer.timeout.connect(self._poll_discovery)
        self._discovery_timer.start()

    def _poll_discovery(self):
        """Answers discovery requests that carry the right code hash."""

        sock = self.discovery
        if sock is None or self._keys is None:
            return
        expected = discovery_hash(self._keys).encode('ascii')
        for _ in range(16):
            try:
                data, sender = sock.recvfrom(2048)
            except (BlockingIOError, OSError):
                return
            data = data.strip()
            if not data.startswith(DISCOVERY_PREFIX):
                continue
            if not hmac.compare_digest(data[len(DISCOVERY_PREFIX):],
                                       expected):
                # Wrong code: stay silent so codes can't be probed
                continue
            reply = (OFFER_PREFIX + expected + b'|'
                     + str(self.port).encode('ascii'))
            try:
                sock.sendto(reply, sender)
            except OSError:
                continue

    def _on_new_connection(self):
        sock = self.server.nextPendingConnection()
        if sock is None:
            return
        if len(self.peers) >= MAX_PEERS:
            logger.info('Collaboration: too many peers, refusing connection')
            sock.disconnectFromHost()
            sock.deleteLater()
            return
        self.peers[sock] = {'id': None, 'name': 'peer', 'keys': None}
        self._buffers[sock] = b''
        sock.readyRead.connect(lambda s=sock: self._on_ready_read(s))
        sock.disconnected.connect(lambda s=sock: self._on_disconnected(s))
        sock.errorOccurred.connect(
            lambda err, s=sock: self._on_socket_error(s, err))

    # -- Media transfer ----------------------------------------------------

    def _send_asset_to(self, sock, data, name, kind):
        """Sends a media file in chunks (original bytes)."""

        if not data or len(data) > MAX_ASSET_SIZE:
            return False
        sha = _sha256(data)
        meta = _asset_meta(data, name, kind)
        self._send(sock, {'type': 'asset_begin', **meta})
        seq = 0
        for offset in range(0, len(data), ASSET_CHUNK_SIZE):
            chunk = data[offset:offset + ASSET_CHUNK_SIZE]
            self._send(sock, {
                'type': 'asset_chunk',
                'sha': sha,
                'seq': seq,
                'data': base64.b64encode(chunk).decode('ascii'),
            })
            seq += 1
        self._send(sock, {'type': 'asset_end', 'sha': sha})
        logger.debug(f'Collaboration: sent asset {sha[:12]} '
                     f'({len(data)} bytes, {seq} chunks)')
        return True

    def _broadcast_asset(self, data, name, kind, exclude=None):
        if not data or len(data) <= ASSET_INLINE_LIMIT:
            return
        # Browsers receive the same chunked transfer with progress
        bridge = getattr(self, 'web_bridge', None)
        if bridge is not None:
            self._send_asset_to_web(bridge, data, name, kind)
        if self.is_host:
            for sock in list(self.peers):
                if sock is not exclude and self._keys_for(sock) is not None:
                    self._send_asset_to(sock, data, name, kind)
        elif self.socket is not None:
            self._send_asset_to(self.socket, data, name, kind)

    def _send_asset_to_web(self, bridge, data, name, kind):
        """Streams a large asset to the browser clients, with progress."""

        import base64 as _b64
        sha = _sha256(data)
        meta = _asset_meta(data, name, kind)
        bridge.broadcast({'type': 'asset_begin', 'sha': sha,
                          'size': len(data), 'meta': meta})
        for offset in range(0, len(data), ASSET_CHUNK_SIZE):
            chunk = data[offset:offset + ASSET_CHUNK_SIZE]
            bridge.broadcast({'type': 'asset_chunk', 'sha': sha,
                              'data': _b64.b64encode(chunk).decode('ascii')})
        bridge.broadcast({'type': 'asset_end', 'sha': sha, 'meta': meta})

    def _send_item_assets(self, items, sock=None):
        """Sends media that was too large to travel inline.

        Every machine ends up with the same original bytes; an asset is
        only transferred once per session, however often it is used.
        """

        for item in items:
            data = item_asset_bytes(item)
            if not data or len(data) <= ASSET_INLINE_LIMIT:
                continue
            sha = _sha256(data)
            kind = 'video' if item.TYPE == XRefVideoItem.TYPE else 'image'
            if sock is not None:
                self._send_asset_to(sock, data, item.filename, kind)
                continue
            if sha in self._sent_assets:
                continue
            self._sent_assets.add(sha)
            self._broadcast_asset(data, item.filename, kind)

    def _request_asset(self, sha):
        if sha and self.socket is not None:
            self._send(self.socket, {'type': 'asset_request', 'sha': sha})

    # -- Receiving media ---------------------------------------------------

    def _clear_asset_progress(self, sha):
        """Removes the download placeholder from the waiting items."""

        for item in self._pending_assets.get(sha, []):
            try:
                item.set_download_progress(None)
            except RuntimeError:
                pass

    def _store_asset(self, sha, data, name):
        return store_asset(sha, data, name)

    def _apply_asset(self, sha, data, path):
        items = self._pending_assets.pop(sha, [])
        for item in items:
            try:
                if item.scene() is self.scene:
                    apply_asset_to_item(item, data, path)
            except RuntimeError:  # item already deleted
                continue
        if items:
            logger.info(f'Collaboration: media applied to {len(items)} item(s)')

    def _handle_asset(self, sock, payload):
        mtype = payload.get('type')
        sha = payload.get('sha')
        if not sha:
            return
        if mtype == 'asset_begin':
            try:
                size = int(payload.get('size') or 0)
            except (TypeError, ValueError):
                size = 0
            if size > MAX_ASSET_SIZE:
                logger.info('Collaboration: refusing an oversized asset')
                return
            self._asset_buffers[sha] = bytearray()
            self._asset_meta[sha] = payload
            # Show a download placeholder on every item waiting for this
            for item in self._pending_assets.get(sha, []):
                item.set_download_progress(0)
            return
        if mtype == 'asset_chunk':
            buffer = self._asset_buffers.get(sha)
            if buffer is None:
                return
            try:
                buffer.extend(base64.b64decode(payload.get('data') or ''))
            except (ValueError, TypeError):
                self._asset_buffers.pop(sha, None)
                self._clear_asset_progress(sha)
                return
            meta = self._asset_meta.get(sha, {})
            try:
                total = int(meta.get('size') or 0)
            except (TypeError, ValueError):
                total = 0
            if total > 0:
                percent = min(99, int(len(buffer) * 100 / total))
                for item in self._pending_assets.get(sha, []):
                    item.set_download_progress(percent)
            return
        if mtype == 'asset_end':
            buffer = self._asset_buffers.pop(sha, None)
            meta = self._asset_meta.pop(sha, {})
            self._clear_asset_progress(sha)
            if buffer is None:
                return
            data = bytes(buffer)
            if _sha256(data) != sha:
                logger.info('Collaboration: checksum mismatch, media dropped')
                return
            path = self._store_asset(sha, data, meta.get('name'))
            self._apply_asset(sha, data, path)
            return
        if mtype == 'asset_request':
            path = find_cached_asset(sha)
            if not path:
                return
            try:
                with open(path, 'rb') as f:
                    data = f.read()
            except OSError:
                return
            self._send_asset_to(sock, data, os.path.basename(path),
                                'video' if path.lower().endswith(
                                    ('.mp4', '.mov', '.webm', '.mkv', '.avi')
                                ) else 'image')

    def _register_pending_asset(self, item, state):
        """Remembers items whose media still has to arrive."""

        asset = state.get('asset') or {}
        sha = asset.get('sha')
        if not sha or asset.get('inline'):
            return
        if find_cached_asset(sha):
            return
        self._pending_assets.setdefault(sha, []).append(item)
        self._request_asset(sha)

    def _send_snapshot(self, sock):
        items, links = self._collect_state(include_image=True)
        self._send(sock, {
            'type': 'snapshot',
            'items': [{'id': cid, 'item': state}
                      for cid, state in items.items()],
            'links': [list(link) for link in links],
        })
        # Media that is too large for the inline limit follows in chunks
        self._send_item_assets(self.scene.items_for_save(), sock=sock)

    def _on_disconnected(self, sock):
        info = self.peers.pop(sock, None)
        self._buffers.pop(sock, None)
        if info and info.get('keys'):
            logger.info(f'Collaboration peer left: {info.get("name")}')
        try:
            sock.deleteLater()
        except (AttributeError, RuntimeError):
            pass
        self.peers_changed.emit(self.peer_count())
        if self.is_host:
            self._set_status(self._host_status())

    def _on_socket_error(self, sock, error):
        logger.info(f'Collaboration socket error: {error}')

    # -- Joining -----------------------------------------------------------

    def join(self, code, timeout_ms=8000):
        """Finds and joins the board that belongs to ``code``."""

        if self.is_active():
            self.leave()
        self.last_error = ''
        self._got_snapshot = False
        self._handshake_done = False
        self._handshake_error = ''
        keys = derive_keys(code)
        if keys is None:
            self.last_error = tr('Please enter the session code.')
            self._set_status(self.last_error)
            return False
        self.code = normalize_code(code)
        self.session_code = format_code(self.code)
        self._keys = keys
        self._set_status(tr('Looking for the shared board...'))

        offer = self._discover_host(keys, timeout_ms)
        if offer is None:
            self.last_error = tr(
                'No board found with this code. Check the code and that '
                'both devices are on the same network.')
            self._set_status(self.last_error)
            self._keys = None
            return False
        host, port = offer
        return self._connect_authenticated(host, port, keys, timeout_ms)

    def _discover_host(self, keys, timeout_ms):
        """Broadcasts the (hashed) code and waits for the host's answer."""

        token = discovery_hash(keys).encode('ascii')
        message = DISCOVERY_PREFIX + token
        addresses = ['255.255.255.255', '127.0.0.1']
        addresses += [address for address in _broadcast_addresses()
                      if address not in addresses]
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.settimeout(0.15)
            elapsed = QtCore.QElapsedTimer()
            elapsed.start()
            while elapsed.elapsed() < timeout_ms:
                for address in addresses:
                    try:
                        sock.sendto(message, (address, DISCOVERY_PORT))
                    except OSError:
                        continue
                QtCore.QCoreApplication.processEvents()
                try:
                    data, sender = sock.recvfrom(2048)
                except (socket.timeout, OSError):
                    continue
                data = data.strip()
                if not data.startswith(OFFER_PREFIX):
                    continue
                parts = data[len(OFFER_PREFIX):].split(b'|')
                if len(parts) < 2:
                    continue
                if not hmac.compare_digest(parts[0], token):
                    continue
                try:
                    port = int(parts[1])
                except ValueError:
                    continue
                return sender[0], port
            return None
        finally:
            sock.close()

    def _connect_authenticated(self, host, port, keys, timeout_ms):
        sock = QtNetwork.QTcpSocket(self)
        self.socket = sock
        self._buffers[sock] = b''
        sock.readyRead.connect(lambda s=sock: self._on_ready_read(s))
        sock.disconnected.connect(self._on_client_disconnected)
        sock.errorOccurred.connect(self._on_client_error)
        sock.connectToHost(host, int(port))
        if not sock.waitForConnected(timeout_ms):
            self.last_error = tr('Could not connect to the board: {error}',
                                 error=sock.errorString())
            self._set_status(self.last_error)
            self.socket = None
            sock.deleteLater()
            self._keys = None
            return False

        self._client_nonce = secrets.token_hex(16)
        self._send_plain(sock, {
            'type': 'hello',
            'v': PROTOCOL_VERSION,
            'peer_id': self.peer_id,
            'name': self.name,
            'nonce': self._client_nonce,
            'proof': _proof(keys, 'hello', self._client_nonce,
                            self.peer_id),
        })

        elapsed = QtCore.QElapsedTimer()
        elapsed.start()
        while (not self._handshake_done and self.socket is not None
                and elapsed.elapsed() < timeout_ms):
            QtCore.QCoreApplication.processEvents()
            sock.waitForReadyRead(60)
            self._drain(sock)

        if not self._handshake_done:
            reason = self._handshake_error or tr('no answer from the host')
            self.last_error = tr('Could not join the board: {reason}',
                                 reason=tr(reason))
            self._set_status(self.last_error)
            if self.socket is not None:
                self.socket.deleteLater()
                self.socket = None
            self._keys = None
            return False

        # Wait for the board itself, so the caller never sees a half-set-up
        # session and local edits can't race with the initial snapshot
        elapsed.restart()
        while (not self._got_snapshot and self.socket is not None
                and elapsed.elapsed() < timeout_ms):
            QtCore.QCoreApplication.processEvents()
            sock.waitForReadyRead(60)
            self._drain(sock)
        if not self._got_snapshot:
            self.last_error = tr('Could not join the board: no board data')
            self._set_status(self.last_error)
            if self.socket is not None:
                self.socket.deleteLater()
                self.socket = None
            self._keys = None
            self._session_keys = None
            self._handshake_done = False
            return False
        return True

    def _on_client_disconnected(self):
        self._handshake_done = False
        lost_host = (not self.is_host and self.socket is not None
                     and not self._session_ended)
        if self.socket is not None:
            self.socket.deleteLater()
            self.socket = None
        self._timer.stop()
        self._session_keys = None
        if self.is_host:
            self._set_status(self._host_status())
            return
        self.peers_changed.emit(0)
        if lost_host:
            self._on_host_lost()
        else:
            self._set_status(tr('Disconnected'))

    def _on_host_lost(self):
        """The host went away without ending the session: recover."""

        rank = 0
        if self.peer_id in self._handover_order:
            rank = self._handover_order.index(self.peer_id)
        self._recover_rank = rank
        self._recover_attempts = 0
        self._set_status(tr('Host connection lost, recovering...'))
        if self._recover_timer is not None:
            self._recover_timer.stop()
            self._recover_timer.deleteLater()
        self._recover_timer = QtCore.QTimer(self)
        self._recover_timer.setSingleShot(True)
        # Rank 0 tries first; the others wait in case it is gone as well
        self._recover_timer.timeout.connect(self._try_recover)
        self._recover_timer.start(RECOVER_DELAY_MS + rank * 1200)

    def _try_recover(self):
        self._recover_timer = None
        if self.is_active() or self._session_ended or not self.code:
            return

        if self._recover_rank == 0:
            # The host designated us as its successor: take over right
            # away, so the other peers have something to reconnect to
            if self._become_host():
                return
        elif self.join(self.code, timeout_ms=1500):
            self._recover_attempts = 0
            self._set_status(tr('Reconnected to the shared board'))
            return

        self._recover_attempts += 1
        if self._recover_attempts < RECOVER_ATTEMPTS:
            self._recover_timer = QtCore.QTimer(self)
            self._recover_timer.setSingleShot(True)
            self._recover_timer.timeout.connect(self._try_recover)
            self._recover_timer.start(RECOVER_RETRY_MS)
            return

        if self._recover_rank <= 2 and self._become_host():
            return
        self._recover_attempts = 0
        self._set_status(tr('Shared board connection lost'))

    def _become_host(self):
        """Continues the session as the new host (board is up to date)."""

        if self.host(port=0, code=self.code):
            self._recover_attempts = 0
            self._set_status(tr('Taking over sharing '
                                '(you are the new host)'))
            self.became_host.emit()
            return True
        return False

    def _on_client_error(self, error):
        SocketError = QtNetwork.QAbstractSocket.SocketError
        ignored = {SocketError.SocketTimeoutError,
                   getattr(SocketError, 'NetworkTimeoutError', None),
                   getattr(SocketError, 'TemporaryError', None)}
        if error in ignored:
            # waitForReadyRead() poll timeouts are not real errors
            return
        logger.info(f'Collaboration connection error: {error}')
        if (self.socket is not None and not self.is_host
                and not self._handshake_done):
            self.last_error = tr('Connection error: {error}',
                                 error=self.socket.errorString())

    # -- Leaving -----------------------------------------------------------

    def leave(self, announce=True):
        """Stops sharing/leaves. A host announces it, so peers don't
        take over a session that was ended on purpose."""

        self.stop_web_sharing()
        self._timer.stop()
        if self._recover_timer is not None:
            self._recover_timer.stop()
            self._recover_timer = None
        if self.is_host and announce:
            for peer in list(self.peers):
                if self.peers.get(peer, {}).get('keys'):
                    self._send(peer, {'type': 'end',
                                      'peer_id': self.peer_id})
        sock = self.socket
        if sock is not None:
            self.socket = None
            self._send(sock, {'type': 'bye', 'peer_id': self.peer_id})
            try:
                sock.flush()
                sock.disconnectFromHost()
                sock.deleteLater()
            except RuntimeError:  # already deleted
                pass
        for peer in [s for s in list(self.peers) if s is not None]:
            if self.peers.get(peer, {}).get('keys'):
                self._send(peer, {'type': 'bye', 'peer_id': self.peer_id})
            try:
                peer.flush()
                peer.disconnectFromHost()
                peer.deleteLater()
            except RuntimeError:
                pass
        self.peers = {}
        self._buffers = {}
        if self._discovery_timer is not None:
            self._discovery_timer.stop()
            self._discovery_timer.deleteLater()
            self._discovery_timer = None
        if self.discovery is not None:
            try:
                self.discovery.close()
            except OSError:
                pass
            self.discovery = None
        if self.server is not None:
            self.server.close()
            self.server.deleteLater()
            self.server = None
        self.is_host = False
        self.port = None
        self._keys = None
        self._session_keys = None
        self._known = {}
        self._links = set()
        self._got_snapshot = False
        self._handshake_done = False
        self.code = None
        self.session_code = None
        self._handover_order = []
        self._session_ended = False
        self._asset_buffers = {}
        self._asset_meta = {}
        self._pending_assets = {}
        self._sent_assets = set()
        self._set_status(tr('Not sharing'))
        self.peers_changed.emit(0)

    # -- Transport ---------------------------------------------------------

    def _keys_for(self, sock):
        if sock is not None and sock is self.socket:
            return self._session_keys
        info = self.peers.get(sock)
        return info.get('keys') if info else None

    @staticmethod
    def _write(sock, message):
        try:
            sock.write((json.dumps(message, separators=(',', ':'))
                        + '\n').encode('utf-8'))
            sock.flush()
            return True
        except (RuntimeError, OSError) as e:
            logger.info(f'Collaboration send failed: {e}')
            return False

    def _send_plain(self, sock, message):
        if sock is not None:
            self._write(sock, message)

    def _send(self, sock, payload):
        """Sends a payload, encrypted when the handshake is done."""

        if sock is None:
            return
        keys = self._keys_for(sock)
        if keys is None:
            if sock is self.socket:
                self._send_plain(sock, payload)
            return
        message = {'type': 'sealed'}
        message.update(seal(keys, payload))
        self._write(sock, message)

    def _broadcast(self, payload, exclude=None):
        if self.is_host:
            for sock in list(self.peers):
                if sock is not exclude and self._keys_for(sock) is not None:
                    self._send(sock, payload)
        elif self.socket is not None:
            self._send(self.socket, payload)
        # Mirror desktop traffic to the browser clients
        bridge = getattr(self, 'web_bridge', None)
        if bridge is not None and payload.get('type') == 'ops':
            # Keep the cached snapshot for newly connecting browsers
            self._web_cache = self.web_snapshot()
            bridge.broadcast(payload)

    def _on_ready_read(self, sock):
        if sock is None:
            return
        try:
            data = bytes(sock.readAll())
        except RuntimeError:
            return
        if not data:
            return
        buffer = self._buffers.get(sock, b'') + data
        if len(buffer) > MAX_LINE_BYTES:
            logger.info('Collaboration: oversized message, dropping peer')
            self._drop_socket(sock)
            return
        while b'\n' in buffer:
            line, buffer = buffer.split(b'\n', 1)
            line = line.strip()
            if line:
                self._handle_line(sock, line)
        self._buffers[sock] = buffer

    def _drain(self, sock):
        """Processes everything currently buffered on a socket."""

        self._on_ready_read(sock)

    def _drop_socket(self, sock):
        self.peers.pop(sock, None)
        self._buffers.pop(sock, None)
        try:
            sock.disconnectFromHost()
            sock.deleteLater()
        except (RuntimeError, AttributeError):
            pass
        self.peers_changed.emit(self.peer_count())

    # -- Protocol ----------------------------------------------------------

    def _handle_line(self, sock, line):
        try:
            message = json.loads(line)
        except (json.JSONDecodeError, UnicodeDecodeError):
            logger.info('Collaboration: invalid message ignored')
            return
        if not isinstance(message, dict):
            return
        mtype = message.get('type')
        if mtype == 'sealed':
            keys = self._keys_for(sock)
            if keys is None:
                logger.info('Collaboration: message before handshake')
                return
            payload = unseal(keys, message)
            if payload is None:
                self._drop_socket(sock)
                return
            self._handle_payload(sock, payload)
            return
        if mtype in ('hello', 'welcome', 'denied'):
            self._handle_handshake(sock, message)
            return
        logger.info(f'Collaboration: unencrypted message {mtype!r} ignored')

    def _handle_handshake(self, sock, message):
        mtype = message.get('type')
        if mtype == 'hello' and self.is_host:
            self._accept_hello(sock, message)
            return
        if mtype == 'welcome' and self.socket is sock:
            self._accept_welcome(message)
            return
        if mtype == 'denied' and self.socket is sock:
            self._handshake_error = str(message.get('reason') or 'denied')
            logger.info(f'Collaboration: host denied the connection '
                        f'({self._handshake_error})')

    def _accept_hello(self, sock, message):
        address = ''
        try:
            address = sock.peerAddress().toString()
        except RuntimeError:
            pass
        if self._is_locked_out(address):
            self._send_plain(sock, {'type': 'denied',
                                    'reason': 'too many attempts'})
            self._drop_socket(sock)
            return
        if message.get('v') != PROTOCOL_VERSION:
            self._send_plain(sock, {'type': 'denied',
                                    'reason': 'version mismatch'})
            self._drop_socket(sock)
            return
        client_nonce = str(message.get('nonce') or '')
        peer_id = str(message.get('peer_id') or '')
        proof = str(message.get('proof') or '')
        expected = _proof(self._keys, 'hello', client_nonce, peer_id)
        if not client_nonce or not hmac.compare_digest(proof, expected):
            self._record_failure(address)
            self._send_plain(sock, {'type': 'denied',
                                    'reason': 'wrong session code'})
            logger.info('Collaboration: rejected a peer with a wrong code')
            self._drop_socket(sock)
            return
        name = str(message.get('name') or 'peer')[:64]
        if self.approval_callback is not None:
            try:
                allowed = bool(self.approval_callback(name, address))
            except Exception:  # noqa: BLE001 - never break the handshake
                allowed = False
            if not allowed:
                self._send_plain(sock, {'type': 'denied',
                                        'reason': 'declined by the host'})
                self._drop_socket(sock)
                return
        server_nonce = secrets.token_hex(16)
        keys = derive_session_keys(self._keys, client_nonce, server_nonce)
        info = self.peers.get(sock) or {}
        info.update({'id': peer_id, 'name': name, 'keys': keys,
                     'address': address})
        self.peers[sock] = info
        self._send_plain(sock, {
            'type': 'welcome',
            'v': PROTOCOL_VERSION,
            'peer_id': self.peer_id,
            'name': self.name,
            'nonce': server_nonce,
            'proof': _proof(self._keys, 'welcome', client_nonce,
                            server_nonce, self.peer_id),
        })
        self._send_snapshot(sock)
        self.peers_changed.emit(self.peer_count())
        self._set_status(self._host_status())
        self._announce_handover()

    def _accept_welcome(self, message):
        keys = self._keys
        if keys is None or not self._client_nonce:
            return
        server_nonce = str(message.get('nonce') or '')
        proof = str(message.get('proof') or '')
        expected = _proof(keys, 'welcome', self._client_nonce,
                          server_nonce, str(message.get('peer_id') or ''))
        if not server_nonce or not hmac.compare_digest(proof, expected):
            self._handshake_error = 'the host could not be verified'
            logger.info('Collaboration: host failed authentication')
            self._drop_socket(self.socket)
            return
        self._session_keys = derive_session_keys(
            keys, self._client_nonce, server_nonce)
        self._handshake_done = True
        self._set_status(
            tr('Connected to {name} · code {code}',
               name=message.get('name', 'host'),
               code=self.session_code))
        self.peers_changed.emit(1)

    def _is_locked_out(self, address):
        stamps = self._failed.get(address)
        if not stamps:
            return False
        now = time.time()
        self._failed[address] = [s for s in stamps
                                 if now - s < FAILED_ATTEMPT_WINDOW]
        return len(self._failed[address]) >= MAX_FAILED_ATTEMPTS

    def _record_failure(self, address):
        self._failed.setdefault(address, []).append(time.time())

    def _handle_payload(self, sock, payload):
        mtype = payload.get('type')
        if mtype == 'snapshot':
            self._apply_snapshot(payload)
        elif mtype == 'ops':
            origin = payload.get('origin')
            if origin == self.peer_id:
                return
            if self.is_host:
                # Relay to the other peers (sealed per peer)
                self._broadcast(payload, exclude=sock)
            self._apply_ops(payload.get('ops', []))
        elif mtype in ('asset_begin', 'asset_chunk', 'asset_end',
                       'asset_request'):
            if self.is_host and mtype != 'asset_request':
                # The host is the hub: pass media on to the other peers
                self._broadcast(payload, exclude=sock)
            self._handle_asset(sock, payload)
        elif mtype == 'handover':
            self._handover_order = list(payload.get('order') or [])
            logger.debug(f'Collaboration: handover order '
                         f'{self._handover_order}')
        elif mtype == 'end':
            # The host stopped sharing on purpose: no takeover
            self._session_ended = True
            self._set_status(tr('The host ended the shared session'))
        elif mtype == 'bye':
            logger.info('Collaboration: peer said goodbye')
            self._drop_socket(sock)

    def _apply_snapshot(self, message):
        self._applying = True
        self._got_snapshot = True
        try:
            self.scene.clear()
            by_id = {}
            for entry in message.get('items', []):
                item = create_item_from_state(entry.get('item', {}))
                if item is None:
                    continue
                item.collab_id = entry['id']
                self.scene.addItem(item)
                by_id[entry['id']] = item
                self._register_pending_asset(item, entry.get('item', {}))
            self._known = {}
            self._links = set()
            for entry in message.get('items', []):
                self._known[entry['id']] = _diff_state(entry.get('item', {}))
            for source_id, target_id in message.get('links', []):
                source = by_id.get(source_id)
                target = by_id.get(target_id)
                if source is not None and target is not None:
                    self.scene.add_link(source, target)
                    self._links.add((source_id, target_id))
        finally:
            self._applying = False
        if not self.is_host:
            # Now it is safe to send local changes
            self._timer.start()
        self.board_replaced.emit()
        self.scene.update()

    def _apply_ops(self, ops):
        if not ops:
            return
        self._applying = True
        try:
            by_id = self._items_by_id()
            for op in ops:
                kind = op.get('op')
                state = op.get('item') or {}
                cid = op.get('id')
                if kind == 'add':
                    existing = by_id.get(cid)
                    if existing is None:
                        item = create_item_from_state(state)
                        if item is None:
                            continue
                        item.collab_id = cid
                        self.scene.addItem(item)
                        by_id[cid] = item
                        self._register_pending_asset(item, state)
                    self._known[cid] = _diff_state(state)
                elif kind == 'update':
                    item = by_id.get(cid)
                    if item is not None:
                        update_item_from_state(item, state)
                    self._known[cid] = _diff_state(state)
                elif kind == 'remove':
                    item = by_id.pop(cid, None)
                    if item is not None:
                        self.scene.removeItem(item)
                    self._known.pop(cid, None)
                elif kind in ('link', 'unlink'):
                    source = by_id.get(op.get('source'))
                    target = by_id.get(op.get('target'))
                    if source is None or target is None:
                        continue
                    if kind == 'link':
                        self.scene.add_link(source, target)
                        self._links.add((op['source'], op['target']))
                    else:
                        self.scene.remove_link(source, target)
                        self._links.discard((op['source'], op['target']))
        finally:
            self._applying = False
        self.scene.update()

    # -- Diffing -----------------------------------------------------------

    # -- Web bridge -------------------------------------------------------

    def start_web_sharing(self, public=False):
        """Serves the board to browsers.

        Returns the shareable link (with the session code), or None when
        the optional aiohttp package is missing. With ``public=True`` an
        ssh tunnel (localhost.run) exposes the board on the internet; the
        URL then carries the session code, which keeps the board private.
        """

        if not self.is_active():
            return None
        from xref.web_bridge import WebBridge, AIOHTTP_AVAILABLE
        if not AIOHTTP_AVAILABLE:
            return None
        if getattr(self, 'web_bridge', None) is not None:
            return self.public_web_link() if getattr(
                self, 'web_tunnel', None) else self.web_link()
        self.web_bridge = WebBridge(self, self.session_code)
        # Precompute the snapshot on this (Qt) thread
        self._web_cache = self.web_snapshot()
        port = self.web_bridge.start()
        if not port:
            self.web_bridge = None
            return None
        logger.info(f'Web sharing on port {port}')
        if public:
            from xref.tunnel import SshTunnel
            self.web_tunnel = SshTunnel(port)
            url = self.web_tunnel.start()
            if url:
                return f'{url}/#CODE{self.session_code}'
            # Tunnel failed: fall back to the local link
            self.web_tunnel = None
        return self.web_link()

    def web_link(self):
        """The shareable browser link for this session."""

        bridge = getattr(self, 'web_bridge', None)
        if bridge is None or not bridge.port:
            return None
        import socket
        try:
            host = socket.gethostbyname(socket.gethostname())
        except OSError:
            host = '127.0.0.1'
        return f'http://{host}:{bridge.port}/#CODE{self.session_code}'

    def public_web_link(self):
        """The tunnelled internet link, when a tunnel is open."""

        tunnel = getattr(self, 'web_tunnel', None)
        if tunnel is not None and tunnel.url:
            return f'{tunnel.url}/#CODE{self.session_code}'
        return None

    def stop_web_sharing(self):
        bridge = getattr(self, 'web_bridge', None)
        if bridge is not None:
            bridge.stop()
            self.web_bridge = None
        tunnel = getattr(self, 'web_tunnel', None)
        if tunnel is not None:
            tunnel.stop()
            self.web_tunnel = None

    def web_snapshot(self):
        """The current board as one payload for browser clients."""

        snapshot = self._cached_web_snapshot()
        self._web_cache = snapshot
        return snapshot

    def _view_state(self):
        """The host's current pan/zoom, mirrored by browser clients."""

        for view in self.scene.views():
            try:
                transform = view.transform()
                centre = view.mapToScene(view.viewport().rect().center())
                return {'scale': transform.m11(),
                        'rot': transform.m21() != 0 or
                               transform.m12() != 0,
                        'cx': centre.x(), 'cy': centre.y()}
            except RuntimeError:  # noqa: BLE001 - view already gone
                continue
        return None

    def _cached_web_snapshot(self):
        items, links = self._collect_state(include_image=True)
        return {
            'type': 'snapshot',
            'items': [{'id': cid, 'item': state}
                      for cid, state in items.items()],
            'links': [list(link) for link in links],
            'canvas': self._canvas_state(),
            'view': self._view_state(),
        }

    def _canvas_state(self):
        """Canvas settings the browser mirrors (colour, grid, titles)."""

        settings = XRefSettings()
        try:
            style = settings.valueOrDefault('View/grid_style')
            spacing = int(settings.valueOrDefault('View/grid_spacing'))
        except Exception:  # noqa: BLE001 - settings not ready
            style, spacing = 'none', 50
        try:
            titles = bool(settings.valueOrDefault(
                'Items/show_media_titles'))
        except Exception:  # noqa: BLE001
            titles = False
        colour = '#000000'
        views = self.scene.views()
        if views:
            qcolor = views[0].backgroundBrush().color()
            colour = qcolor.name()
        return {'grid': {'style': style, 'spacing': spacing},
                'colour': colour,
                'show_titles': titles}

    def web_pending_assets(self):
        """Large assets a newly connecting browser still needs.

        Runs on the Qt thread (called from the web bridge). Returns
        ``(data, name, kind)`` tuples for every distinct asset over the
        inline limit, so a browser that connects later sees the same
        board as the desktop.
        """

        from xref.collab import ASSET_INLINE_LIMIT  # pragma: no cover
        result = []
        seen = set()
        try:
            board_items = self.scene.items_for_save()
        except RuntimeError:  # scene already gone
            return result
        for item in board_items:
            try:
                data = item_asset_bytes(item)
            except Exception:  # noqa: BLE001 - unreadable media
                continue
            if not data or len(data) <= ASSET_INLINE_LIMIT:
                continue
            sha = _sha256(data)
            if sha in seen:
                continue
            seen.add(sha)
            if item.TYPE == XRefVideoItem.TYPE:
                kind = 'video'
            elif item.TYPE == XRefModelItem.TYPE:
                kind = 'model'
            elif item.TYPE == XRefPdfItem.TYPE:
                kind = 'pdf'
            else:
                kind = 'image'
            result.append((data, item.filename, kind))
        return result

    def apply_web_message(self, payload):
        """Applies ops from a browser client and relays them."""

        if not isinstance(payload, dict):
            return
        if payload.get('type') != 'ops':
            return
        ops = payload.get('ops') or []
        self._apply_ops(ops)
        # Relay to the desktop peers
        self._broadcast({'type': 'ops', 'origin': 'web',
                         'ops': ops})
        # And back to the other browsers
        bridge = getattr(self, 'web_bridge', None)
        if bridge is not None:
            bridge.broadcast(payload)

    def sync(self):
        """Sends local changes to the peers."""

        if self._applying or not self.is_active():
            return
        if not self.is_host and not self._handshake_done:
            return
        items, links = self._collect_state(include_image=False)
        by_id = self._items_by_id()
        ops = []
        new_items = []
        for cid, state in items.items():
            if cid not in self._known:
                full = item_state(by_id[cid], include_image=True)
                ops.append({'op': 'add', 'id': cid, 'item': full})
                new_items.append(by_id[cid])
            elif self._known[cid] != state:
                ops.append({'op': 'update', 'id': cid,
                            'item': _diff_state(state)})
        for cid in list(self._known):
            if cid not in items:
                ops.append({'op': 'remove', 'id': cid})
        for link in links - self._links:
            ops.append({'op': 'link', 'source': link[0],
                        'target': link[1]})
        for link in self._links - links:
            ops.append({'op': 'unlink', 'source': link[0],
                        'target': link[1]})
        self._known = {cid: _diff_state(state)
                       for cid, state in items.items()}
        self._links = set(links)
        if ops:
            self._broadcast({'type': 'ops', 'origin': self.peer_id,
                             'ops': ops})
            if new_items:
                self._send_item_assets(new_items)


def _broadcast_addresses():
    """The broadcast addresses of all IPv4 interfaces."""

    addresses = []
    for interface in QtNetwork.QNetworkInterface.allInterfaces():
        for entry in interface.addressEntries():
            if entry.ip().protocol() != QtNetwork.QAbstractSocket.\
                    NetworkLayerProtocol.IPv4Protocol:
                continue
            broadcast = entry.broadcast()
            if broadcast.isNull():
                continue
            text = broadcast.toString()
            if text and text not in addresses:
                addresses.append(text)
    return addresses
