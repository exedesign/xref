"""Single-file browser client for the WebRTC board mirror.

Shows the desktop board as live video and sends mouse/keyboard input
back over a WebRTC data channel. The web side gets its own toolbar
(text tool, pen tool, camera zoom/fit); shortcuts and context menus
stay desktop-only. Each connected viewer gets a random guest name,
which the desktop shows as a remote-cursor label.
"""

STREAM_HTML = r'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>XRef Mirror</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  html, body { margin: 0; height: 100%; background: #000; color: #eee;
               font-family: system-ui, sans-serif; overflow: hidden; }
  #bar { position: fixed; top: 0; left: 0; right: 0; padding: 4px 8px;
         background: rgba(20,22,28,.94); font-size: 13px; z-index: 3;
         display: flex; align-items: center; gap: 8px; }
  #bar button { background: #2a3346; color: #eee; border: 1px solid #46536e;
                border-radius: 6px; padding: 4px 10px; font-size: 13px;
                cursor: pointer; }
  #bar button:hover { background: #38445c; }
  #bar button.active { background: #1f6feb; border-color: #3b82f6; }
  #status { margin-left: auto; opacity: .8; }
  #cursorTag { position: fixed; pointer-events: none; z-index: 5;
               background: rgba(31,111,235,.85); color: #fff;
               font-size: 12px; padding: 2px 7px; border-radius: 9px;
               display: none; transform: translate(10px, 12px); }
  #drop { position: fixed; inset: 0; display: none; z-index: 9;
          background: rgba(40,90,180,.25); border: 3px dashed #8fc3ff;
          font-size: 22px; color: #fff; align-items: center;
          justify-content: center; }
</style>
</head>
<body>
<div id="bar">
  <strong>XRef</strong>
  <button id="tb_select" class="active" title="Se&#231;im (varsay&#305;lan fare)">&#10148; Se&#231;</button>
  <button id="tb_text" title="Metin ekle">+ Metin</button>
  <button id="tb_draw" title="Kalem (masaüstünde çizim modu)">&#9998; Kalem</button>
  <button id="tb_zoom_in" title="Yakınlaştır">+</button>
  <button id="tb_zoom_out" title="Uzaklaştır">&minus;</button>
  <button id="tb_fit" title="Sahneye sığdır">&#9974; Sığdır</button>
  <button id="tb_full" title="Tarayıcıda tam ekran">&#x26F6; Tam ekran</button>
  <span id="status">bağlanıyor...</span>
</div>
<div id="vwrap" style="position:absolute; top:34px; width:100%;
     height:calc(100% - 34px); overflow:hidden;">
<video id="v" autoplay playsinline muted
       style="width:100%;height:100%;object-fit:contain;background:#000;
              display:block;"></video>
</div>
<div id="cursorTag"></div>
<div id="drop">Dosyayı bırakın &mdash; masaüstüne eklenecek</div>
<script>
'use strict';
const statusEl = document.getElementById('status');
const video = document.getElementById('v');
const tagEl = document.getElementById('cursorTag');
let dc = null;

// Random guest name shown to the desktop user
const GUESTS = ['Kartal', 'Şahin', 'Martı', 'Serçe', 'Baykuş', 'Kuzgun',
                'Tavşan', 'Tilki', 'Sincap', 'Kaplan', 'Panda', 'Ayı',
                'Yıldız', 'Bulut', 'Rüzgar', 'Deniz'];
const guestName = GUESTS[Math.floor(Math.random() * GUESTS.length)]
    + '-' + Math.floor(100 + Math.random() * 900);

// -- WebRTC setup -----------------------------------------------------
const pc = new RTCPeerConnection({iceServers: [
  {urls: 'stun:stun.l.google.com:19302'}]});
pc.ontrack = (ev) => { video.srcObject = ev.streams[0]; };
pc.onconnectionstatechange = () => {
  statusEl.textContent = pc.connectionState === 'connected'
      ? `${guestName} · canlı` : pc.connectionState;
};
dc = pc.createDataChannel('input');
pc.addTransceiver('video', {direction: 'recvonly'});
dc.onopen = () => {
  statusEl.textContent = `${guestName} · veri kanalı hazır`;
  send({kind: 'hello', name: guestName});
};
dc.onmessage = (ev) => {
  try {
    const m = JSON.parse(ev.data);
    if (m.kind === 'progress' && m.size)
      statusEl.textContent = 'yükleniyor ' +
          Math.floor(m.received / m.size * 100) + '%';
    if (m.kind === 'text_edit') {
      typing = m.active;
      document.getElementById('tb_text').textContent =
          typing ? 'Yazıyor... (Enter)' : '+ Metin';
    }
  } catch (e) {}
};

async function connect() {
  const offer = await pc.createOffer();
  await pc.setLocalDescription(offer);
  const resp = await fetch('/offer', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({sdp: offer.sdp, type: offer.type})});
  const answer = await resp.json();
  await pc.setRemoteDescription(answer);
}
connect().catch(e => statusEl.textContent = 'hata: ' + e.message);

// -- Toolbar ------------------------------------------------------------
function send(obj) {
  if (dc && dc.readyState === 'open') dc.send(JSON.stringify(obj));
}
// Buttons must not keep keyboard focus: after a toolbar click the
// next keystroke would re-trigger the button (Space/Enter)
for (const b of document.querySelectorAll('#bar button'))
  b.addEventListener('mouseup', () => b.blur());
// Single tool state: 'select' (default pointer behaviour), 'text',
// or 'draw'. Switching to select leaves any special mode.
let activeTool = 'select';
const toolBtns = {select: document.getElementById('tb_select'),
                  text: document.getElementById('tb_text'),
                  draw: document.getElementById('tb_draw')};
function setTool(tool) {
  // Leaving a mode cleanly
  if (tool !== activeTool && typing) {
    // Cancel an open text edit when switching away
    send({kind: 'key', key: 'Escape', text: ''});
    typing = false;
    document.getElementById('tb_text').textContent = '+ Metin';
  }
  if (activeTool === 'draw' && tool !== 'draw') {
    // Turn the desktop pen mode off
    send({kind: 'action', action: 'toggle_draw'});
    toolBtns.draw.classList.remove('active');
  }
  activeTool = tool;
  for (const [name, btn] of Object.entries(toolBtns))
    btn.classList.toggle('active', name === tool);
}
// Buttons must not keep keyboard focus: after a toolbar click the
// next keystroke would re-trigger the button (Space/Enter)
for (const b of document.querySelectorAll('#bar button'))
  b.addEventListener('mouseup', () => b.blur());
toolBtns.draw.onclick = () => {
  if (activeTool === 'draw') { setTool('select'); return; }
  setTool('draw');
  send({kind: 'action', action: 'toggle_draw'});
};
let typing = false;
toolBtns.text.onclick = () => {
  if (activeTool === 'text') { setTool('select'); return; }
  setTool('text');
  typing = false;
};
video.addEventListener('click', (ev) => {
  if (activeTool !== 'text' || typing) return;
  const p = norm(ev);
  // Server creates an empty text item there and puts it into edit
  // mode; keystrokes then flow through the normal key events
  send({kind: 'start_text', x: p.x, y: p.y});
  typing = true;
  document.getElementById('tb_text').textContent = 'Yazıyor... (Enter)';
});
video.addEventListener('dblclick', (ev) => {
  ev.preventDefault();
  if (activeTool !== 'select' || typing) return;
  const p = norm(ev);
  send({kind: 'edit_text', x: p.x, y: p.y});
});
function typingKey(ev) {
  if (!typing) return;
  if (ev.key === 'Enter' || ev.key === 'Escape') {
    typing = false;
    document.getElementById('tb_text').textContent = '+ Metin';
    setTool('select');
  }
}
// Camera zoom (web camera only; desktop viewport untouched)
document.getElementById('tb_zoom_in').onclick = () =>
    send({kind: 'camera', op: 'zoom', factor: 1.25, x: 0.5, y: 0.5});
document.getElementById('tb_zoom_out').onclick = () =>
    send({kind: 'camera', op: 'zoom', factor: 1 / 1.25, x: 0.5, y: 0.5});
document.getElementById('tb_fit').onclick = () =>
    send({kind: 'camera', op: 'reset'});
// Browser fullscreen (not the desktop's fullscreen)
document.getElementById('tb_full').onclick = () => {
  if (document.fullscreenElement) document.exitFullscreen();
  else document.documentElement.requestFullscreen();
};

// -- Input forwarding ---------------------------------------------------
function norm(ev) {
  const r = video.getBoundingClientRect();
  const vw = video.videoWidth || 1, vh = video.videoHeight || 1;
  const scale = Math.min(r.width / vw, r.height / vh);
  const ox = (r.width - vw * scale) / 2, oy = (r.height - vh * scale) / 2;
  const x = (ev.clientX - r.left - ox) / (vw * scale);
  const y = (ev.clientY - r.top - oy) / (vh * scale);
  return {x: Math.max(0, Math.min(1, x)),
          y: Math.max(0, Math.min(1, y))};
}
let lastMove = 0;
video.addEventListener('wheel', (ev) => {
  ev.preventDefault();
  const p = norm(ev);
  const factor = ev.deltaY < 0 ? 1.2 : 1 / 1.2;
  send({kind: 'camera', op: 'zoom', factor: factor,
        x: p.x, y: p.y});
}, {passive: false});
let camPan = null;
video.addEventListener('mousedown', (ev) => {
  if (ev.button === 1) { camPan = {x: ev.clientX, y: ev.clientY};
                         ev.preventDefault(); return; }
  if (ev.button === 2) { ev.preventDefault(); return; }  // no ctx menu
  const p = norm(ev);
  send({kind: 'mouse_press', button: ev.button, x: p.x, y: p.y,
        id: 1, shift: ev.shiftKey, ctrl: ev.ctrlKey, alt: ev.altKey});
  ev.preventDefault();
});
video.addEventListener('mousemove', (ev) => {
  // Keep the guest's cursor label glued to the pointer
  tagEl.style.display = 'block';
  tagEl.style.left = ev.clientX + 'px';
  tagEl.style.top = ev.clientY + 'px';
  if (camPan) {
    const r = video.parentElement.getBoundingClientRect();
    const dx = -(ev.clientX - camPan.x) / r.width;
    const dy = -(ev.clientY - camPan.y) / r.height;
    send({kind: 'camera', op: 'pan', dx: dx, dy: dy});
    camPan = {x: ev.clientX, y: ev.clientY};
    return;
  }
  const now = performance.now();
  const p = norm(ev);
  // Report pointer position so the desktop shows this guest's label
  send({kind: 'cursor', x: p.x, y: p.y, inside: true});
  if (now - lastMove < 16) return;
  lastMove = now;
  send({kind: 'mouse_move', x: p.x, y: p.y,
        shift: ev.shiftKey, ctrl: ev.ctrlKey, alt: ev.altKey});
});
video.addEventListener('mouseleave', () => {
  tagEl.style.display = 'none';
  send({kind: 'cursor', x: 0.5, y: 0.5, inside: false});
});
video.addEventListener('mouseup', (ev) => {
  if (ev.button === 1 && camPan) { camPan = null; return; }
  if (ev.button === 2) return;
  const p = norm(ev);
  send({kind: 'mouse_release', button: ev.button, x: p.x, y: p.y,
        id: 1, shift: ev.shiftKey, ctrl: ev.ctrlKey, alt: ev.altKey});
});
video.addEventListener('contextmenu', (ev) => ev.preventDefault());
// Keyboard: plain keys only. Ctrl-combos (like Ctrl+Z) stay desktop
// features and are deliberately not forwarded.
addEventListener('keydown', (ev) => {
  if (ev.ctrlKey || ev.metaKey) { ev.preventDefault(); return; }
  // While typing on the board the keyboard belongs to the board:
  // stop Tab/F6/arrows from walking off into the toolbar buttons
  const focusIsButton = document.activeElement
      && document.activeElement.tagName === 'BUTTON';
  if (typing && (ev.key === 'Tab' || ev.key === 'F6' || focusIsButton)) {
    document.activeElement.blur();
    ev.preventDefault();
  }
  // Never let Tab reach the toolbar (it would trap focus there)
  if (ev.key === 'Tab') { ev.preventDefault(); }
  typingKey(ev);
  if (['Delete', 'Backspace', 'Escape'].includes(ev.key))
    ev.preventDefault();
  send({kind: 'key', key: ev.key, text: ev.key,
        shift: ev.shiftKey, ctrl: false, alt: ev.altKey});
});
addEventListener('keyup', (ev) => {
  if (ev.ctrlKey || ev.metaKey) return;
  send({kind: 'keyup', key: ev.key, text: ev.key,
        shift: ev.shiftKey, ctrl: false, alt: ev.altKey});
});

// -- File drop: transfer over the data channel --------------------------
const dropEl = document.getElementById('drop');
addEventListener('dragover', (ev) => { ev.preventDefault();
  dropEl.style.display = 'flex'; });
addEventListener('dragleave', (ev) => {
  if (!ev.relatedTarget) dropEl.style.display = 'none'; });

async function mediaPixelSize(file) {
  try {
    if (file.type.startsWith('image/')) {
      const url = URL.createObjectURL(file);
      try {
        const bmp = await createImageBitmap(url);
        return {w: bmp.width, h: bmp.height};
      } finally { URL.revokeObjectURL(url); }
    }
    if (file.type.startsWith('video/')) {
      const url = URL.createObjectURL(file);
      try {
        const meta = await new Promise((res, rej) => {
          const v = document.createElement('video');
          v.preload = 'metadata';
          v.onloadedmetadata = () => res(v);
          v.onerror = () => rej(new Error('meta'));
          v.src = url;
        });
        return {w: meta.videoWidth, h: meta.videoHeight};
      } finally { URL.revokeObjectURL(url); }
    }
  } catch (e) {}
  return null;
}

addEventListener('drop', async (ev) => {
  ev.preventDefault();
  dropEl.style.display = 'none';
  if (!dc || dc.readyState !== 'open') return;
  const p = norm(ev);
  for (const file of ev.dataTransfer.files) {
    const id = 'f' + Date.now() + Math.random().toString(36).slice(2, 7);
    const buf = new Uint8Array(await file.arrayBuffer());
    const dims = await mediaPixelSize(file);
    send({kind: 'file', id: id, name: file.name, size: buf.length,
          x: p.x, y: p.y, w: dims ? dims.w : 0, h: dims ? dims.h : 0});
    const CHUNK = 16000;
    const enc = new TextEncoder();
    const prefix = enc.encode(id + '|');
    function dcSendBuffered() {
      return dc.bufferedAmount || 0;
    }
    for (let off = 0; off < buf.length; off += CHUNK) {
      while (dcSendBuffered() > 4 * 1024 * 1024)
        await new Promise(r => setTimeout(r, 20));
      const part = buf.subarray(off, off + CHUNK);
      const frame = new Uint8Array(prefix.length + part.length);
      frame.set(prefix, 0);
      frame.set(part, prefix.length);
      dc.send(frame);
    }
    send({kind: 'file', id: id, done: true, x: p.x, y: p.y});
    statusEl.textContent = `${guestName} · canlı`;
  }
});
</script>
</body>
</html>
'''
