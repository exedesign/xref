"""The single-file browser client served by the web bridge.

Vanilla JS/Canvas: no build tools. Renders the board snapshot, allows
dragging items, and sends move ops back over the WebSocket.
"""

CLIENT_HTML = r'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>XRef Board</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  html, body { margin: 0; height: 100%; background: #111; color: #eee;
               font-family: system-ui, sans-serif; overflow: hidden; }
  #bar { position: fixed; top: 0; left: 0; right: 0; padding: 6px 10px;
         background: rgba(30,30,34,.9); font-size: 13px; z-index: 2; }
  #bar b { color: #8fc3ff; }
  #tools { position: fixed; top: 28px; left: 0; right: 0; padding: 3px 8px;
           background: rgba(24,24,28,.92); font-size: 12px; z-index: 2;
           display: flex; gap: 4px; flex-wrap: wrap; align-items: center; }
  #tools button { background: #2c3140; color: #dde; border: 1px solid #3c4356;
                  border-radius: 4px; padding: 2px 8px; cursor: pointer;
                  font-size: 12px; }
  #tools button:hover { background: #3a4257; }
  #tools input[type=range] { width: 90px; }
  canvas { position: absolute; top: 62px; cursor: default; }
  img.cache { display: none; }
</style>
</head>
<body>
<div id="bar">XRef web board &mdash; <span id="status">connecting...</span></div>
<div id="tools">
  <button id="tb_flip_h" title="Yatay çevir">&#8644; Çevir</button>
  <button id="tb_raise" title="Öne getir">&#8679;</button>
  <button id="tb_lower" title="Arkaya gönder">&#8681;</button>
  <button id="tb_gray" title="Gri tonlama">&#9632; Gri</button>
  <button id="tb_norm_h" title="Yükseklikleri eşitle">=H</button>
  <button id="tb_norm_w" title="Genişlikleri eşitle">=W</button>
  <button id="tb_text" title="Metin ekle">+ Metin</button>
  <label title="Saydaml&#305;k">Saydam <input type="range" id="tb_opacity"
    min="10" max="100" value="100"></label>
  <button id="tb_del" title="Sil (Delete)">&#128465;</button>
</div>
<canvas id="c"></canvas>
<div id="imgcache"></div>
<script>
'use strict';
const hash = location.hash || '';
const code = hash.startsWith('#CODE') ? hash.slice(5) : '';
const statusEl0 = document.getElementById('status');
if (!code) {
  statusEl0.textContent =
      'oturum kodu eksik — XRef\'teki "Web Bağlantısı Oluştur" ' +
      'linkinin TAMAMINI (#CODE... dahil) açın';
  statusEl0.style.color = '#ff9f6b';
}
const wsProto = location.protocol === 'https:' ? 'wss' : 'ws';
let ws = null;
let wsRetries = 0;
function connectWs() {
  ws = new WebSocket(
      `${wsProto}://${location.host}/ws?code=${encodeURIComponent(code)}`);
  ws.onopen = onWsOpen;
  ws.onclose = (ev) => {
    statusEl.textContent = (ev.code === 1006)
        ? 'bağlantı koptu, yeniden deniyor...'
        : 'disconnected (' + ev.code + ')';
    statusEl.style.color = '#ff9f6b';
    // Auto-reconnect with backoff
    if (wsRetries < 12) {
      wsRetries++;
      setTimeout(connectWs, Math.min(1000 * wsRetries, 8000));
    }
  };
  ws.onerror = () => {
    statusEl.textContent = 'bağlantı hatası, yeniden deneniyor...';
    statusEl.style.color = '#ff6b6b';
  };
  ws.onmessage = onWsMessage;
  // If the socket never even opens, fall back to HTTP polling (some
  // browsers/networks block cross-origin WSS through the tunnel)
  setTimeout(() => {
    if (!wsLive && wsPoll === null) startPolling();
  }, 5000);
}

// HTTP polling fallback: fetches the snapshot every 3 seconds
let wsLive = false;
let wsPoll = null;
let pollETag = 0;
function startPolling() {
  wsPoll = setInterval(async () => {
    try {
      const r = await fetch(
          `/state?code=${encodeURIComponent(code)}&t=${Date.now()}`,
          {cache: 'no-store'});
      if (!r.ok) return;
      const text = await r.text();
      if (text && text !== lastSnapshotText) {
        lastSnapshotText = text;
        onWsMessage({data: text});
        statusEl.textContent = 'live (poll)';
      }
    } catch (e) { /* offline; retry next tick */ }
  }, 3000);
}
let lastSnapshotText = '';
if (code) {
  connectWs();
  // The tunnel URL changes when sharing restarts; an old page can
  // never reconnect - tell the user instead of retrying forever
  setTimeout(() => {
    if (statusEl.textContent === 'connecting...' ||
        statusEl.textContent === 'connected')
      statusEl.textContent =
          'sunucuya ulaşılamadı — XRef\'teki "İnternet Paylaşımı" ' +
          'linkini yeniden kopyalayıp yeni sekmede açın';
  }, 6000);
}

const canvas = document.getElementById('c');
const ctx = canvas.getContext('2d');
const statusEl = document.getElementById('status');
// Surface client errors in the status bar instead of failing silently
window.onerror = (m) => {
  statusEl.textContent = 'error: ' + m;
  statusEl.style.color = '#ff6b6b';
};

let items = {};      // id -> item state
let images = {};     // dataURL -> Image
let videos = {};     // dataURL -> <video> element
let thumbs = {};     // item id -> small preview Image
let links = [];
let view = {x: 0, y: 0, scale: 1};
let drag = null;
let pan = null;
let viewInitialised = false;
let selection = new Set();   // selected item ids
// Large assets stream in chunks; items show a download box meanwhile
let assetBuffers = {};   // sha -> {received, size, chunks: []}
let assetData = {};      // sha -> dataURL (complete)
let boardCanvas = {colour: '#111111', grid: {style: 'none', spacing: 50},
                   show_titles: false};

function resize() {
  canvas.width = innerWidth;
  canvas.height = innerHeight - 62;
  draw();
}
addEventListener('resize', resize);

function invertColour(hex) {
  const n = parseInt(hex.slice(1), 16);
  return {r: 255 - ((n >> 16) & 255), g: 255 - ((n >> 8) & 255),
          b: 255 - (n & 255)};
}

function itemRect(state) {
  const s = state.size || [200, 200];
  return {w: s[0] * (state.scale || 1), h: s[1] * (state.scale || 1)};
}

function draw() {
  ctx.fillStyle = boardCanvas.colour || '#111';
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  // Grid: same look as the desktop - constant on-screen spacing
  if (boardCanvas.grid && boardCanvas.grid.style !== 'none' && boardCanvas.grid.spacing >= 5) {
    const spacing = boardCanvas.grid.spacing;
    const grid = invertColour(boardCanvas.colour || '#111111');
    ctx.strokeStyle = `rgba(${grid.r},${grid.g},${grid.b},0.16)`;
    ctx.lineWidth = 1;
    if (boardCanvas.grid.style === 'dots') {
      ctx.fillStyle = `rgba(${grid.r},${grid.g},${grid.b},0.35)`;
      for (let y = 0; y < canvas.height; y += spacing) {
        for (let x = 0; x < canvas.width; x += spacing) {
          ctx.fillRect(x, y, 2, 2);
        }
      }
    } else {
      ctx.beginPath();
      for (let x = 0; x < canvas.width; x += spacing) {
        ctx.moveTo(x + 0.5, 0); ctx.lineTo(x + 0.5, canvas.height);
      }
      for (let y = 0; y < canvas.height; y += spacing) {
        ctx.moveTo(0, y + 0.5); ctx.lineTo(canvas.width, y + 0.5);
      }
      ctx.stroke();
    }
  }
  ctx.save();
  ctx.translate(view.x, view.y);
  ctx.scale(view.scale, view.scale);
  // links
  ctx.strokeStyle = 'rgba(255,255,255,.4)';
  ctx.lineWidth = 1.5 / view.scale;
  for (const [s, t] of links) {
    const a = items[s], b = items[t];
    if (!a || !b) continue;
    const ra = itemRect(a), rb = itemRect(b);
    const ax = (a.x || 0) + ra.w / 2, ay = (a.y || 0) + ra.h / 2;
    const bx = (b.x || 0) + rb.w / 2, by = (b.y || 0) + rb.h / 2;
    ctx.beginPath(); ctx.moveTo(ax, ay); ctx.lineTo(bx, by); ctx.stroke();
  }
  // items
  for (const id in items) {
    const st = items[id];
    const r = itemRect(st);
    const x = st.x || 0, y = st.y || 0;
    const img = images[st.image] || images[id] ||
                videos[st.image] || videos[id] ||
                thumbs[id];
    const isVideoEl = img && img.tagName === 'VIDEO' &&
                      img.readyState >= 2;
    const sha = st.asset && st.asset.sha;
    const buf = sha ? assetBuffers[sha] : null;
    // Media types the browser cannot render inline: show a labelled
    // box with a download button instead of streaming the file
    const kind = (st.asset && st.asset.kind) || st.type;
    const boxKind = (kind === 'video' && !isVideoEl)
        ? 'video' : (kind === 'pdf') ? 'PDF'
        : (kind === 'model') ? '3D' : null;
    ctx.save();
    // Same geometry as the desktop: rotation and flip included
    ctx.translate(x + r.w / 2, y + r.h / 2);
    if (st.rotation) ctx.rotate(st.rotation * Math.PI / 180);
    if (st.flip === -1) ctx.scale(-1, 1);
    ctx.globalAlpha = (st.opacity === undefined) ? 1 : st.opacity;
    ctx.translate(-r.w / 2, -r.h / 2);
    if (buf) {
      // Download placeholder with a progress bar, like the desktop view
      ctx.fillStyle = '#14141a';
      ctx.fillRect(0, 0, r.w, r.h);
      const pct = Math.min(99, Math.floor(buf.received / buf.size * 100));
      ctx.fillStyle = '#4682d2';
      ctx.fillRect(0, 0, r.w * pct / 100, r.h);
      ctx.fillStyle = '#ebebeb';
      ctx.font = `bold ${18 / view.scale}px sans-serif`;
      ctx.textAlign = 'center';
      ctx.fillText(pct + '%', r.w / 2, r.h / 2 + 6 / view.scale);
      ctx.textAlign = 'left';
    } else if (isVideoEl) {
      try { ctx.drawImage(img, 0, 0, r.w, r.h); } catch (e) {}
    } else if (img && img.complete && img.naturalWidth > 0) {
      ctx.drawImage(img, 0, 0, r.w, r.h);
    } else if (boxKind && sha && !assetData[sha]) {
      // Labelled placeholder for non-image media
      ctx.fillStyle = '#1c2030';
      ctx.fillRect(0, 0, r.w, r.h);
      ctx.strokeStyle = '#3a4260';
      ctx.lineWidth = 2 / view.scale;
      ctx.strokeRect(0, 0, r.w, r.h);
      ctx.fillStyle = '#9fb4e8';
      ctx.font = `bold ${16 / view.scale}px sans-serif`;
      ctx.textAlign = 'center';
      ctx.fillText(boxKind + ' medyası', r.w / 2, r.h / 2 - 14 / view.scale);
      const mb = ((st.asset.size || 0) / 1048576).toFixed(1);
      ctx.font = `${11 / view.scale}px sans-serif`;
      ctx.fillStyle = '#8a93ad';
      ctx.fillText(mb + ' MB — indirmek için tıklayın',
                   r.w / 2, r.h / 2 + 10 / view.scale);
      ctx.textAlign = 'left';
    } else {
      ctx.fillStyle = (st.type === 'text') ? '#2a2a30' : '#345';
      ctx.fillRect(0, 0, r.w, r.h);
      if (st.text) {
        ctx.fillStyle = '#eee';
        ctx.font = `${14 / view.scale}px sans-serif`;
        const lines = String(st.text).slice(0, 200).split('\n');
        lines.slice(0, 8).forEach((line, i) =>
          ctx.fillText(line, 6, 20 + i * 18, r.w - 12));
      }
    }
    // Media title band, matching the desktop label
    if (boardCanvas.show_titles && st.filename) {
      const name = st.filename.split(/[\\/]/).pop();
      const h = 18 / view.scale;
      ctx.fillStyle = 'rgba(0,0,0,0.55)';
      ctx.fillRect(0, r.h, r.w, h);
      ctx.fillStyle = '#ebebeb';
      ctx.font = `${9 / view.scale}px sans-serif`;
      ctx.fillText(name, 4 / view.scale, r.h + h * 0.7);
    }
    ctx.restore();
    // Resize handle at the bottom-right corner
    if (r.w > 8 && r.h > 8) {
      const hs = 7 / view.scale;
      ctx.fillStyle = '#8fc3ff';
      ctx.fillRect(x + r.w - hs, y + r.h - hs, hs, hs);
      ctx.strokeStyle = '#0d1626';
      ctx.lineWidth = 1 / view.scale;
      ctx.strokeRect(x + r.w - hs, y + r.h - hs, hs, hs);
    }
    // Rotate handle above the top edge
    {
      const hs = 7 / view.scale;
      const cx = x + r.w / 2, cy = y - 24 / view.scale;
      ctx.beginPath();
      ctx.arc(cx, cy, hs, 0, Math.PI * 2);
      ctx.fillStyle = '#a8e6a0';
      ctx.fill();
      ctx.strokeStyle = '#0d1626';
      ctx.lineWidth = 1 / view.scale;
      ctx.stroke();
      // stem to the item
      ctx.beginPath();
      ctx.moveTo(cx, y);
      ctx.lineTo(cx, cy + hs);
      ctx.strokeStyle = 'rgba(168,230,160,.6)';
      ctx.stroke();
    }
    if (drag && drag.id === id) {
      ctx.strokeStyle = '#8fc3ff';
      ctx.lineWidth = 2 / view.scale;
      ctx.strokeRect(x, y, r.w, r.h);
    } else if (selection.has(id)) {
      ctx.strokeStyle = '#a8e6a0';
      ctx.lineWidth = 1.5 / view.scale;
      ctx.strokeRect(x, y, r.w, r.h);
    }
  }
  // rubberband
  if (drag && drag.mode === 'band') {
    ctx.strokeStyle = '#8fc3ff';
    ctx.lineWidth = 1 / view.scale;
    ctx.fillStyle = 'rgba(143,195,255,.1)';
    const bx = Math.min(drag.x0, drag.x1), by = Math.min(drag.y0, drag.y1);
    const bw = Math.abs(drag.x1 - drag.x0), bh = Math.abs(drag.y1 - drag.y0);
    ctx.fillRect(bx, by, bw, bh);
    ctx.strokeRect(bx, by, bw, bh);
  }
  ctx.restore();
}

function loadImages() {
  for (const id in items) {
    const st = items[id];
    const key = st.image || id;
    if (st.imageData && !images[key]) {
      const isVideo = (st.type === 'video') ||
          (st.asset && st.asset.meta &&
           String(st.asset.meta.mime || '').startsWith('video/'));
      if (isVideo) {
        const v = document.createElement('video');
        v.src = st.imageData;
        v.muted = true; v.loop = true;
        v.addEventListener('canplay', () => { v.play(); draw(); });
        v.addEventListener('error', () => draw());
        videos[key] = v;
        document.getElementById('imgcache').appendChild(v);
      } else {
        const img = new Image();
        img.src = st.imageData;
        images[key] = img;
        img.onload = draw;
      }
    }
  }
}

function loadThumbs() {
  for (const id in items) {
    const st = items[id];
    const asset = st.asset || {};
    if (asset.thumb && !thumbs[id]) {
      const img = new Image();
      img.src = `data:${asset.thumb_mime || 'image/jpeg'};base64,${asset.thumb}`;
      thumbs[id] = img;
      img.onload = draw;
    }
  }
}

function tick() {
  let hasVideo = false;
  for (const k in videos) hasVideo = true;
  if (hasVideo) draw();
  requestAnimationFrame(tick);
}
requestAnimationFrame(tick);

// Keep the canvas (colour/grid/titles) in sync with the desktop by
// asking for a fresh snapshot periodically; deferred while dragging so
// a refresh never deletes an item mid-drag
let pendingSnapshot = null;
setInterval(() => {
  if (!ws || ws.readyState !== 1) return;
  if (drag || pan) { pendingSnapshot = true; return; }
  ws.send(JSON.stringify({type: 'refresh'}));
}, 3000);

function send(ops) {
  if (ws && ws.readyState === 1) ws.send(JSON.stringify({type: 'ops', ops}));
}

function onWsOpen() {
  wsRetries = 0;
  wsLive = true;
  statusEl.style.color = '';
  statusEl.textContent = 'connected';
  // If no snapshot arrives, surface it instead of hanging silently
  setTimeout(() => {
    if (statusEl.textContent === 'connected')
      statusEl.textContent =
          'connected ama pano verisi gelmedi (sunucu hata logluyor)';
  }, 5000);
}
function onWsMessage(ev) {
  let msg;
  try { msg = JSON.parse(ev.data); } catch (e) { return; }
  if (msg.type === 'snapshot') {
    items = {};
    for (const entry of msg.items || []) {
      const st = entry.item || {};
      const full = Object.assign({}, st, {
        x: entry.item.x, y: entry.item.y});
      items[entry.id] = full;
      const asset = st.asset || {};
      if (asset.inline) {
        const meta = asset.meta || {};
        const mime = meta.mime || 'image/png';
        full.imageData = `data:${mime};base64,${asset.inline}`;
      }
    }
    links = (msg.links || []).map(l => [l[0], l[1]]);
    if (msg.canvas) {
      boardCanvas = msg.canvas;
      document.body.style.background = boardCanvas.colour || '#111';
    }
    loadImages();
    loadThumbs();
    if (!viewInitialised) {
      // The web view is independent: the host's pan/zoom is not
      // mirrored, so both sides can navigate freely
      fitView();
      viewInitialised = true;
    }
    draw();
    statusEl.textContent = 'live';
  } else if (msg.type === 'ops') {
    for (const op of msg.ops || []) {
      if (op.op === 'add') items[op.id] = Object.assign({}, op.item);
      else if (op.op === 'update') {
        if (items[op.id]) Object.assign(items[op.id], op.item);
      } else if (op.op === 'remove') delete items[op.id];
      else if (op.op === 'link') links.push([op.source, op.target]);
      else if (op.op === 'unlink') links = links.filter(
          l => !(l[0] === op.source && l[1] === op.target));
    }
    loadImages();
    loadThumbs();
    draw();
  } else if (msg.type === 'asset_begin') {
    assetBuffers[msg.sha] = {received: 0, size: msg.size || 1,
                             chunks: [], meta: msg.meta || {}};
    draw();
  } else if (msg.type === 'asset_chunk') {
    const buf = assetBuffers[msg.sha];
    if (buf) {
      buf.chunks.push(msg.data);
      buf.received += atob(msg.data).length;
      draw();
    }
  } else if (msg.type === 'asset_end') {
    const buf = assetBuffers[msg.sha];
    if (buf) {
      const bin = buf.chunks.map(c => atob(c)).join('');
      const mime = (buf.meta.mime) || 'application/octet-stream';
      const dataURL = `data:${mime};base64,${btoa(bin)}`;
      const isVideo = mime.startsWith('video/') ||
          String(buf.meta.kind || '') === 'video';
      let media;
      if (isVideo) {
        media = document.createElement('video');
        media.src = dataURL;
        media.muted = true; media.loop = true;
        media.addEventListener('canplay', () => { media.play(); draw(); });
        media.addEventListener('error', () => draw());
        document.getElementById('imgcache').appendChild(media);
      } else {
        media = new Image();
        media.src = dataURL;
        media.onload = draw;
      }
      // attach to the items that referenced this sha
      for (const iid in items) {
        if (items[iid].asset && items[iid].asset.sha === msg.sha) {
          items[iid].image = msg.sha;
          if (isVideo) videos[msg.sha] = media;
          else images[msg.sha] = media;
        }
      }
      assetData[msg.sha] = dataURL;
      delete assetBuffers[msg.sha];
      draw();
    }
  } else if (msg.type === 'error') {
    statusEl.textContent = 'error: ' + (msg.message || '');
  }
};

function fitView() {
  let minX = 1e9, minY = 1e9, maxX = -1e9, maxY = -1e9;
  for (const id in items) {
    const st = items[id], r = itemRect(st);
    minX = Math.min(minX, st.x || 0);
    minY = Math.min(minY, st.y || 0);
    maxX = Math.max(maxX, (st.x || 0) + r.w);
    maxY = Math.max(maxY, (st.y || 0) + r.h);
  }
  if (minX > maxX) { minX = 0; minY = 0; maxX = 100; maxY = 100; }
  const w = maxX - minX, h = maxY - minY;
  const scale = Math.min(canvas.width / (w + 100),
                         canvas.height / (h + 100), 2);
  view = {scale: scale,
          x: (canvas.width - w * scale) / 2 - minX * scale,
          y: (canvas.height - h * scale) / 2 - minY * scale};
}

function scenePos(ev) {
  const rect = canvas.getBoundingClientRect();
  return {x: (ev.clientX - rect.left - view.x) / view.scale,
          y: (ev.clientY - rect.top - view.y) / view.scale};
}

function hitTest(p) {
  let hit = null;
  for (const id in items) {
    const st = items[id], r = itemRect(st);
    if (p.x >= (st.x || 0) && p.x <= (st.x || 0) + r.w &&
        p.y >= (st.y || 0) && p.y <= (st.y || 0) + r.h) hit = id;
  }
  return hit;
}

// Live sync while dragging: throttled position/scale updates so the
// other side follows the movement in real time
let lastLiveSent = 0;
function liveSync() {
  if (!drag || !items[drag.id]) return;
  const now = Date.now();
  if (now - lastLiveSent < 80) return;   // ~12 updates/second
  lastLiveSent = now;
  const st = items[drag.id];
  const patch = {};
  if (drag.mode === 'scale') {
    patch.scale = st.scale || 1;
    patch.x = st.x; patch.y = st.y;
  } else if (drag.mode === 'rotate') {
    patch.rotation = st.rotation || 0;
  } else {
    patch.x = st.x; patch.y = st.y;
  }
  const ops = [{op: 'update', id: drag.id, item: patch}];
  for (const g of drag.group || []) {
    const gs = items[g.id];
    if (gs) ops.push({op: 'update', id: g.id, item: {x: gs.x, y: gs.y}});
  }
  send(ops);
}
canvas.addEventListener('mousemove', (ev) => {
  if (pan) {
    view.x += ev.clientX - pan.x;
    view.y += ev.clientY - pan.y;
    pan = {x: ev.clientX, y: ev.clientY};
    draw();
  } else if (drag) {
    const p = scenePos(ev);
    if (drag.mode === 'band') {
      drag.x1 = p.x; drag.y1 = p.y;
      draw();
      return;
    }
    const st = drag.id ? items[drag.id] : null;
    if (!st) { drag = null; }
    else if (drag.mode === 'scale') {
      // Resize around the item's top-left anchor
      const base = itemBaseSize(st);
      const dx = p.x - (st.x || 0), dy = p.y - (st.y || 0);
      const factor = Math.max(0.05, Math.min(
          20, Math.max(Math.abs(dx) / base.w, Math.abs(dy) / base.h)));
      st.scale = factor;
    } else if (drag.mode === 'rotate') {
      // Rotate around the item's centre to point at the cursor
      const r = itemRect(st);
      const cx = (st.x || 0) + r.w / 2, cy = (st.y || 0) + r.h / 2;
      st.rotation = Math.atan2(p.y - cy, p.x - cx) * 180 / Math.PI + 90;
    } else {
      st.x = p.x - drag.offX;
      st.y = p.y - drag.offY;
      // move the rest of the selection along
      for (const g of drag.group || []) {
        const gs = items[g.id];
        if (gs) { gs.x = p.x - g.offX; gs.y = p.y - g.offY; }
      }
    }
    liveSync();
    draw();
  } else {
    canvas.style.cursor = cursorFor(scenePos(ev));
  }
});
function itemBaseSize(st) {
  const s = st.size || [200, 200];
  return {w: s[0] || 200, h: s[1] || 200};
}
function cursorFor(p) {
  if (resizeHandleAt(p)) return 'nwse-resize';
  if (rotateHandleAt(p)) return 'grab';
  return hitTest(p) ? 'move' : 'default';
}
function resizeHandleAt(p) {
  for (const id in items) {
    const st = items[id];
    const r = itemRect(st);
    const hx = (st.x || 0) + r.w, hy = (st.y || 0) + r.h;
    const rad = 10 / view.scale;
    if (Math.abs(p.x - hx) < rad && Math.abs(p.y - hy) < rad) return id;
  }
  return null;
}
function rotateHandleAt(p) {
  // A round handle above the top edge; drag to rotate
  for (const id in items) {
    const st = items[id];
    const r = itemRect(st);
    const cx = (st.x || 0) + r.w / 2;
    const cy = (st.y || 0) - 24 / view.scale;
    const rad = 10 / view.scale;
    if (Math.abs(p.x - cx) < rad && Math.abs(p.y - cy) < rad) return id;
  }
  return null;
}
canvas.addEventListener('mousedown', (ev) => {
  const p = scenePos(ev);
  if (ev.button === 1 || ev.shiftKey) { pan = {x: ev.clientX, y: ev.clientY}; return; }
  const rid = resizeHandleAt(p);
  if (rid && items[rid]) {
    drag = {id: rid, mode: 'scale',
            startX: items[rid].x || 0, startY: items[rid].y || 0,
            startScale: items[rid].scale || 1};
    return;
  }
  const aid = rotateHandleAt(p);
  if (aid && items[aid]) {
    drag = {id: aid, mode: 'rotate'};
    return;
  }
  const id = hitTest(p);
  if (id) {
    if (ev.ctrlKey) {
      // toggle membership in a multi-selection
      if (selection.has(id)) selection.delete(id);
      else selection.add(id);
      draw();
      return;
    }
    if (!selection.has(id)) { selection.clear(); selection.add(id); }
    const st = items[id];
    const kind = (st.asset && st.asset.kind) || st.type;
    const needsDownload = (kind === 'pdf' || kind === 'model' ||
                           kind === 'video') &&
                          st.asset && st.asset.sha &&
                          !assetData[st.asset.sha];
    if (needsDownload && selection.size === 1) {
      // Clicking a non-image placeholder starts its download
      if (ws && ws.readyState === 1) {
        ws.send(JSON.stringify(
            {type: 'asset_request', sha: st.asset.sha}));
        statusEl.textContent = 'indiriliyor: ' +
            (st.filename || '').split(/[\\/]/).pop();
      }
      return;
    }
    // Move the whole selection; offsets relative to each item
    drag = {id: id, mode: 'move',
            offX: p.x - (st.x || 0), offY: p.y - (st.y || 0),
            startX: st.x || 0, startY: st.y || 0,
            group: [...selection].filter(
                (sid) => sid !== id).map((sid) => ({
                    id: sid,
                    offX: p.x - (items[sid].x || 0),
                    offY: p.y - (items[sid].y || 0)}))};
  } else {
    // Empty space: start a rubberband selection
    selection.clear();
    drag = {mode: 'band', x0: p.x, y0: p.y, x1: p.x, y1: p.y};
    draw();
  }
});
canvas.addEventListener('mouseup', () => {
  if (drag && drag.mode === 'band') {
    // Select everything inside the rubberband
    const x0 = Math.min(drag.x0, drag.x1), x1 = Math.max(drag.x0, drag.x1);
    const y0 = Math.min(drag.y0, drag.y1), y1 = Math.max(drag.y0, drag.y1);
    selection.clear();
    for (const id in items) {
      const st = items[id], r = itemRect(st);
      const ix = st.x || 0, iy = st.y || 0;
      if (ix < x1 && ix + r.w > x0 && iy < y1 && iy + r.h > y0)
        selection.add(id);
    }
    drag = null;
    draw();
    return;
  }
  if (drag) {
    const st = items[drag.id];
    if (st) {
      if (drag.mode === 'scale') {
        send([{op: 'update', id: drag.id,
               item: {scale: st.scale || 1}}]);
      } else if (drag.mode === 'rotate') {
        send([{op: 'update', id: drag.id,
               item: {rotation: st.rotation || 0}}]);
      } else {
        const ops = [];
        if (Math.abs((st.x || 0) - drag.startX) > 1 ||
            Math.abs((st.y || 0) - drag.startY) > 1)
          ops.push({op: 'update', id: drag.id,
                    item: {x: st.x, y: st.y}});
        for (const g of drag.group || []) {
          const gs = items[g.id];
          if (gs) ops.push({op: 'update', id: g.id,
                            item: {x: gs.x, y: gs.y}});
        }
        if (ops.length) send(ops);
      }
    }
    drag = null;
    // Catch up on a snapshot that was deferred during the drag
    if (pendingSnapshot && ws && ws.readyState === 1) {
      pendingSnapshot = false;
      ws.send(JSON.stringify({type: 'refresh'}));
    }
    draw();
  }
  pan = null;
});
// Delete removes the selected items on both sides
addEventListener('keydown', (ev) => {
  if (ev.key !== 'Delete' && ev.key !== 'Backspace') return;
  if (!selection.size) return;
  ev.preventDefault();
  const ops = [...selection].map(id => ({op: 'remove', id: id}));
  for (const id of selection) delete items[id];
  selection.clear();
  send(ops);
  draw();
});

// -- Toolbar: desktop-equivalent transforms on the web selection ------
function eachSel(fn) {
  const ops = [];
  for (const id of selection) {
    const st = items[id];
    if (!st) continue;
    const patch = fn(st);
    if (patch) ops.push({op: 'update', id: id, item: patch});
  }
  if (ops.length) { send(ops); draw(); }
}
document.getElementById('tb_flip_h').onclick = () =>
    eachSel(st => { st.flip = (st.flip || 1) * -1; return {flip: st.flip}; });
document.getElementById('tb_raise').onclick = () =>
    eachSel(st => { st.z = (st.z || 0) + 0.001; return {z: st.z}; });
document.getElementById('tb_lower').onclick = () =>
    eachSel(st => { st.z = (st.z || 0) - 0.001; return {z: st.z}; });
document.getElementById('tb_gray').onclick = () =>
    eachSel(st => { st.grayscale = !st.grayscale;
                   return {grayscale: st.grayscale}; });
document.getElementById('tb_norm_h').onclick = () => {
  // scale every selected item to the same on-screen height
  let target = null;
  for (const id of selection) {
    const st = items[id];
    if (!st) continue;
    const h = itemRect(st).h;
    if (target === null || h > target) target = h;
  }
  if (target === null) return;
  eachSel(st => {
    const h = itemRect(st).h || 1;
    st.scale = (st.scale || 1) * target / h;
    return {scale: st.scale};
  });
};
document.getElementById('tb_norm_w').onclick = () => {
  let target = null;
  for (const id of selection) {
    const st = items[id];
    if (!st) continue;
    const w = itemRect(st).w;
    if (target === null || w > target) target = w;
  }
  if (target === null) return;
  eachSel(st => {
    const w = itemRect(st).w || 1;
    st.scale = (st.scale || 1) * target / w;
    return {scale: st.scale};
  });
};
document.getElementById('tb_opacity').oninput = (ev) => {
  const o = ev.target.value / 100;
  eachSel(st => { st.opacity = o; return {opacity: o}; });
};
document.getElementById('tb_del').onclick = () => {
  if (!selection.size) return;
  const ops = [...selection].map(id => ({op: 'remove', id: id}));
  for (const id of selection) delete items[id];
  selection.clear();
  send(ops);
  draw();
};
document.getElementById('tb_text').onclick = () => {
  const text = prompt('Metin:');
  if (!text) return;
  const id = guid();
  const state = {type: 'text', x: (view.x < 0 ? -view.x : 100) / view.scale,
                 y: 100 / view.scale, text: text,
                 z: 0, scale: 1, rotation: 0, flip: 1, opacity: 1};
  items[id] = state;
  send([{op: 'add', id: id, item: state}]);
  draw();
};
canvas.addEventListener('wheel', (ev) => {
  ev.preventDefault();
  const factor = ev.deltaY < 0 ? 1.12 : 0.9;
  const rect = canvas.getBoundingClientRect();
  const mx = ev.clientX - rect.left, my = ev.clientY - rect.top;
  view.x = mx - (mx - view.x) * factor;
  view.y = my - (my - view.y) * factor;
  view.scale *= factor;
  draw();
}, {passive: false});

// -- Drag & drop media from the desktop ---------------------------------
canvas.addEventListener('dragover', (ev) => { ev.preventDefault(); });
canvas.addEventListener('drop', async (ev) => {
  ev.preventDefault();
  const files = [...(ev.dataTransfer.files || [])];
  if (!files.length) return;
  const p = scenePos(ev);
  for (const file of files) {
    await addFile(file, p);
  }
});

function guid() {
  return 'web' + Math.random().toString(16).slice(2) +
      Date.now().toString(16);
}

const WEB_DROP_INLINE_LIMIT = 1024 * 1024;   // 1 MB

async function addFile(file, pos) {
  const isImage = /^image\//.test(file.type);
  const isVideo = /^video\//.test(file.type);
  const isPdf = file.type === 'application/pdf';
  const buf = await file.arrayBuffer();
  const bytes = new Uint8Array(buf);
  const id = guid();

  async function sha256Hex() {
    try {
      const h = await crypto.subtle.digest('SHA-256', bytes);
      return Array.from(new Uint8Array(h)).map(
          b => b.toString(16).padStart(2, '0')).join('');
    } catch (e) { return null; }
  }

  if ((isImage || isVideo || isPdf) && bytes.length > WEB_DROP_INLINE_LIMIT) {
    // Large file: add a placeholder item first, then stream the bytes
    // in chunks so the connection stays responsive throughout
    const sha = await sha256Hex() || ('f' + id);
    const kind = isVideo ? 'video' : (isPdf ? 'pdf' : 'image');
    const state = {
      type: isImage ? 'pixmap' : (isVideo ? 'video' : 'pdf'),
      x: pos.x, y: pos.y, filename: file.name,
      size: [400, 300],
      asset: {sha: sha, size: bytes.length, kind: kind,
              name: file.name, meta: {mime: file.type, name: file.name,
                                      kind: kind}},
    };
    items[id] = state;
    send([{op: 'add', id: id, item: state}]);
    draw();
    statusEl.textContent = 'yükleniyor: ' + file.name + ' (0%)';
    // stream in 256 KB chunks
    const CHUNK = 262144;
    const b64chunk = (arr) => {
      let bin = '';
      for (let i = 0; i < arr.length; i += 0x8000)
        bin += String.fromCharCode.apply(null, arr.subarray(i, i + 0x8000));
      return btoa(bin);
    };
    ws.send(JSON.stringify({type: 'web_asset_begin', sha: sha,
                            size: bytes.length,
                            meta: {mime: file.type, name: file.name,
                                   kind: kind}}));
    for (let off = 0; off < bytes.length; off += CHUNK) {
      ws.send(JSON.stringify({type: 'web_asset_chunk', sha: sha,
                              data: b64chunk(bytes.subarray(off, off + CHUNK))}));
      const pct = Math.floor((off + CHUNK) / bytes.length * 100);
      statusEl.textContent = 'yükleniyor: ' + file.name +
          ' (' + Math.min(100, pct) + '%)';
    }
    ws.send(JSON.stringify({type: 'web_asset_end', sha: sha,
                            meta: {mime: file.type, name: file.name,
                                   kind: kind}}));
    statusEl.textContent = 'live';
    return;
  }

  let bin = '';
  const CHUNK = 0x8000;
  for (let i = 0; i < bytes.length; i += CHUNK) {
    bin += String.fromCharCode.apply(null, bytes.subarray(i, i + CHUNK));
  }
  const data = btoa(bin);
  const state = {
    type: isImage ? 'pixmap' : (isVideo ? 'video' : 'text'),
    x: pos.x, y: pos.y,
    filename: file.name,
  };
  if (isImage) {
    state.asset = {inline: data, meta: {mime: file.type,
                                        name: file.name, kind: 'image'}};
    state.size = [400, 300];
  } else if (isVideo) {
    state.asset = {inline: data, meta: {mime: file.type,
                                        name: file.name, kind: 'video'}};
    state.size = [400, 300];
  } else {
    const text = await file.text();
    state.text = text.slice(0, 10000);
  }
  items[id] = state;
  if (state.asset && state.asset.inline) {
    const img = new Image();
    img.src = `data:${state.asset.meta.mime};base64:${data}`;
    images[id] = img;
    img.onload = draw;
  }
  send([{op: 'add', id: id, item: state}]);
  draw();
}

resize();
if (!code) statusEl.textContent = 'no session code in the link';
</script>
</body>
</html>
'''
