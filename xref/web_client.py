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
const params = new URLSearchParams(location.hash.slice(1));
const code = params.get('CODE') || '';
const wsProto = location.protocol === 'https:' ? 'wss' : 'ws';
const ws = new WebSocket(
    `${wsProto}://${location.host}/ws?code=${encodeURIComponent(code)}`);

const canvas = document.getElementById('c');
const ctx = canvas.getContext('2d');
const statusEl = document.getElementById('status');

let items = {};      // id -> item state
let images = {};     // dataURL -> Image
let links = [];
let view = {x: 0, y: 0, scale: 1};
let drag = null;
let pan = null;

function resize() {
  canvas.width = innerWidth;
  canvas.height = innerHeight - 28;
  draw();
}
addEventListener('resize', resize);

function itemRect(state) {
  const s = state.size || [200, 200];
  return {w: s[0] * (state.scale || 1), h: s[1] * (state.scale || 1)};
}

function draw() {
  ctx.fillStyle = '#111';
  ctx.fillRect(0, 0, canvas.width, canvas.height);
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
    const img = images[st.image] || images[id];
    if (img && img.complete) {
      ctx.drawImage(img, x, y, r.w, r.h);
    } else {
      ctx.fillStyle = (st.type === 'text') ? '#2a2a30' : '#345';
      ctx.fillRect(x, y, r.w, r.h);
      if (st.text) {
        ctx.fillStyle = '#eee';
        ctx.font = `${14 / view.scale}px sans-serif`;
        const lines = String(st.text).slice(0, 200).split('\n');
        lines.slice(0, 8).forEach((line, i) =>
          ctx.fillText(line, x + 6, y + 20 + i * 18, r.w - 12));
      }
    }
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
      const img = new Image();
      img.src = st.imageData;
      images[key] = img;
      img.onload = draw;
    }
  }
}

function send(ops) {
  if (ws.readyState === 1) ws.send(JSON.stringify({type: 'ops', ops}));
}

ws.onopen = () => statusEl.textContent = 'connected';
ws.onclose = () => statusEl.textContent = 'disconnected';
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
    loadImages();
    fitView();
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

resize();
if (!code) statusEl.textContent = 'no session code in the link';
</script>
</body>
</html>
'''
