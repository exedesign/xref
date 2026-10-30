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
  canvas { position: absolute; top: 28px; cursor: default; }
  img.cache { display: none; }
</style>
</head>
<body>
<div id="bar">XRef web board &mdash; <span id="status">connecting...</span></div>
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
const ws = new WebSocket(
    `${wsProto}://${location.host}/ws?code=${encodeURIComponent(code)}`);

const canvas = document.getElementById('c');
const ctx = canvas.getContext('2d');
const statusEl = document.getElementById('status');

let items = {};      // id -> item state
let images = {};     // dataURL -> Image
let videos = {};     // dataURL -> <video> element
let links = [];
let view = {x: 0, y: 0, scale: 1};
let drag = null;
let pan = null;
// Large assets stream in chunks; items show a download box meanwhile
let assetBuffers = {};   // sha -> {received, size, chunks: []}
let assetData = {};      // sha -> dataURL (complete)
let boardCanvas = {colour: '#111111', grid: {style: 'none', spacing: 50},
                   show_titles: false};

function resize() {
  canvas.width = innerWidth;
  canvas.height = innerHeight - 28;
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
                videos[st.image] || videos[id];
    const isVideoEl = img && img.tagName === 'VIDEO' &&
                      img.readyState >= 2;
    const sha = st.asset && st.asset.sha;
    const buf = sha ? assetBuffers[sha] : null;
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
    if (drag && drag.id === id) {
      ctx.strokeStyle = '#8fc3ff';
      ctx.lineWidth = 2 / view.scale;
      ctx.strokeRect(x, y, r.w, r.h);
    }
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

function tick() {
  let hasVideo = false;
  for (const k in videos) hasVideo = true;
  if (hasVideo) draw();
  requestAnimationFrame(tick);
}
requestAnimationFrame(tick);

function send(ops) {
  if (ws.readyState === 1) ws.send(JSON.stringify({type: 'ops', ops}));
}

ws.onopen = () => statusEl.textContent = 'connected';
ws.onclose = () => {
  statusEl.textContent = code
      ? 'disconnected (bağlantı koptu — sayfayı yenileyin)'
      : 'oturum kodu eksik — tam linki açın (#CODE... dahil)';
};
ws.onerror = () => statusEl.textContent = 'error';
ws.onmessage = (ev) => {
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
    if (msg.view && msg.view.scale > 0) {
      // Mirror the desktop's pan/zoom instead of fitting our own view
      applyView(msg.view);
    } else {
      fitView();
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

function applyView(v) {
  const scale = v.scale;
  view = {scale: scale,
          x: canvas.width / 2 - v.cx * scale,
          y: canvas.height / 2 - v.cy * scale};
}

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

canvas.addEventListener('mousedown', (ev) => {
  const p = scenePos(ev);
  if (ev.button === 1 || ev.shiftKey) { pan = {x: ev.clientX, y: ev.clientY}; return; }
  const id = hitTest(p);
  if (id) {
    const st = items[id];
    drag = {id, offX: p.x - (st.x || 0), offY: p.y - (st.y || 0),
            startX: st.x || 0, startY: st.y || 0};
  }
});
canvas.addEventListener('mousemove', (ev) => {
  if (pan) {
    view.x += ev.clientX - pan.x;
    view.y += ev.clientY - pan.y;
    pan = {x: ev.clientX, y: ev.clientY};
    draw();
  } else if (drag) {
    const p = scenePos(ev);
    items[drag.id].x = p.x - drag.offX;
    items[drag.id].y = p.y - drag.offY;
    draw();
  } else {
    canvas.style.cursor = hitTest(scenePos(ev)) ? 'move' : 'default';
  }
});
canvas.addEventListener('mouseup', () => {
  if (drag) {
    const st = items[drag.id];
    if (Math.abs((st.x || 0) - drag.startX) > 1 ||
        Math.abs((st.y || 0) - drag.startY) > 1) {
      send([{op: 'update', id: drag.id,
             item: {x: st.x, y: st.y}}]);
    }
    drag = null;
    draw();
  }
  pan = null;
});
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

async function addFile(file, pos) {
  const buf = await file.arrayBuffer();
  const bytes = new Uint8Array(buf);
  let bin = '';
  const CHUNK = 0x8000;
  for (let i = 0; i < bytes.length; i += CHUNK) {
    bin += String.fromCharCode.apply(null, bytes.subarray(i, i + CHUNK));
  }
  const data = btoa(bin);
  const isImage = /^image\//.test(file.type);
  const isVideo = /^video\//.test(file.type);
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
  const id = guid();
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
