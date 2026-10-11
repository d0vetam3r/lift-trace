import { getSpeed, getGameGeometry } from './engine.js';

export const NOTE_COLORS = ['#fc817e', '#e8edf5', '#71b2ff', '#e8edf5', '#71b2ff', '#e8edf5', '#71b2ff', '#e8edf5'];
// Canonical directions are physical rotation viewed from above the turntable.
// Hue and luminance both differ, without making either direction disappear.
export const SCRATCH_COLORS = Object.freeze({ clockwise: '#ffb4aa', counterclockwise: '#e45470' });

function scratchArrow(ctx, x, y, radius, direction, alpha) {
  // Mirror the circular path, not the meaning, when the controller changes side.
  // Canvas angles increase clockwise because its y axis points down.
  const clockwise = direction > 0;
  const start = clockwise ? .4 * Math.PI : .6 * Math.PI;
  const end = clockwise ? 2 * Math.PI : -Math.PI;
  const tipX = x + Math.cos(end) * radius, tipY = y + Math.sin(end) * radius;
  const tangentX = -Math.sin(end) * direction, tangentY = Math.cos(end) * direction;
  const wing = radius * .55;
  ctx.beginPath();
  ctx.arc(x, y, radius, start, end, !clockwise);
  ctx.moveTo(tipX - tangentX * wing - tangentY * wing, tipY - tangentY * wing + tangentX * wing);
  ctx.lineTo(tipX, tipY);
  ctx.lineTo(tipX - tangentX * wing + tangentY * wing, tipY - tangentY * wing - tangentX * wing);
  ctx.globalAlpha = alpha;
  ctx.lineCap = 'round'; ctx.lineJoin = 'round';
  ctx.strokeStyle = '#16141b'; ctx.lineWidth = Math.min(4, radius * .7); ctx.stroke();
  ctx.strokeStyle = '#fff8f4'; ctx.lineWidth = Math.min(1.8, radius * .32); ctx.stroke();
}

export function laneGeometry(settings) {
  const black = settings.blackKeyRatio ?? 1;
  const weights = [settings.scratchWidth, 1, black, 1, black, 1, black, 1];
  const unit = settings.width / weights.reduce((sum, weight) => sum + weight, 0);
  const order = settings.side === '2P' ? [1, 2, 3, 4, 5, 6, 7, 0] : [0, 1, 2, 3, 4, 5, 6, 7];
  const geometry = [];
  let x = 0;
  for (const lane of order) {
    const width = weights[lane] * unit;
    geometry[lane] = { x, width };
    x += width;
  }
  return geometry;
}

export function resizeCanvas(canvas, width, height) {
  const ratio = Math.min(window.devicePixelRatio || 1, 2);
  const pixelWidth = Math.round(width * ratio), pixelHeight = Math.round(height * ratio);
  if (canvas.width !== pixelWidth || canvas.height !== pixelHeight) {
    canvas.width = pixelWidth; canvas.height = pixelHeight;
  }
  // Match the rounded backing buffer exactly, including fractional device scale.
  const ctx = canvas.getContext('2d'); ctx.setTransform(pixelWidth / width, 0, 0, pixelHeight / height, 0, 0);
  return ctx;
}

function note(ctx, lane, head, tail, settings, direction = 0, alpha = 1) {
  const geometry = laneGeometry(settings)[lane];
  const x = geometry.x + 3, width = Math.max(1, geometry.width - 6);
  const color = lane === 0 && direction
    ? SCRATCH_COLORS[direction > 0 ? 'clockwise' : 'counterclockwise'] : NOTE_COLORS[lane];
  ctx.save(); ctx.fillStyle = color;
  ctx.globalAlpha = settings.trailOpacity * alpha;
  ctx.fillRect(x, tail, width, Math.max(0, head - tail));
  ctx.globalAlpha = alpha;
  ctx.fillRect(x, head - settings.noteHeight / 2, width, settings.noteHeight);
  ctx.globalAlpha = .75 * alpha;
  ctx.fillRect(x, tail, width, Math.min(2, settings.noteHeight));
  if (lane === 0 && direction) {
    // Short inputs still have a direction marker. Long inputs keep it near the
    // trailing end so it remains visible while the turntable keeps rotating.
    // The arrowhead reaches 1.55 radii and its outline another .35 radii.
    // Fit the complete marker inside this lane even at minimum supported width.
    const radius = Math.min(7, (geometry.width - 2) / 3.8);
    const y = tail + Math.min(24, Math.max(0, head - tail) / 2);
    scratchArrow(ctx, x + width / 2, y, radius, direction, alpha);
  }
  ctx.restore();
}

export function drawOverlay(ctx, engine, settings, now, offset = 0) {
  // A zero-LIFT auto output uses a 1px canvas only because browser sources need
  // a positive size. There is no region to paint, even for guides or a background.
  if (settings.heightMode === 'auto' && settings.liftNumber === 0) return;
  ctx.save(); ctx.translate(0, offset); ctx.beginPath(); ctx.rect(0, 0, settings.width, settings.overlayHeight); ctx.clip();
  if (settings.background !== 'transparent') { ctx.fillStyle = '#000000'; ctx.fillRect(0, 0, settings.width, settings.overlayHeight); }
  if (settings.showGuides) {
    ctx.strokeStyle = 'rgba(137,154,176,.22)'; ctx.lineWidth = 1;
    for (const g of laneGeometry(settings)) { ctx.beginPath(); ctx.moveTo(g.x + .5, 0); ctx.lineTo(g.x + .5, settings.overlayHeight); ctx.stroke(); }
  }
  for (const event of engine.snapshot(now)) note(ctx, event.lane, event.headY, event.tailY, settings, event.direction);
  ctx.restore();
}

export function drawPreview(canvas, client, now, gameNotes = []) {
  // Show the last 320 logical pixels above the line; crop, never squeeze the game lane.
  const s = client.settings, gameHeight = Math.min(320, getGameGeometry(s).visibleHeight);
  const height = gameHeight + s.overlayHeight;
  const ctx = resizeCanvas(canvas, s.width, height);
  // Constrain the physical preview independently from its logical OBS pixel dimensions.
  canvas.style.width = Math.min(400, s.width) + 'px';
  canvas.style.aspectRatio = `${s.width} / ${height}`;
  ctx.clearRect(0, 0, s.width, height);
  ctx.fillStyle = '#0b0e12'; ctx.fillRect(0, 0, s.width, gameHeight);
  ctx.fillStyle = '#181e25'; ctx.fillRect(0, gameHeight, s.width, s.overlayHeight);
  for (const [index, g] of laneGeometry(s).entries()) {
    if ([2, 4, 6].includes(index)) { ctx.fillStyle = '#121b29'; ctx.fillRect(g.x, 0, g.width, gameHeight); }
    ctx.strokeStyle = '#2a333f'; ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(g.x + .5, 0); ctx.lineTo(g.x + .5, height); ctx.stroke();
  }
  const v = getSpeed(s) / 1000;
  ctx.save(); ctx.beginPath(); ctx.rect(0, 0, s.width, gameHeight); ctx.clip();
  for (const event of gameNotes) {
    const head = gameHeight + (now - event.start) * v;
    const tail = event.long ? gameHeight + (now - event.end) * v : head;
    if (tail > gameHeight + s.noteHeight || head < -s.noteHeight) continue;
    note(ctx, event.lane, head, tail, s, event.direction, .94);
  }
  ctx.restore();
  drawOverlay(ctx, client.engine, s, now, gameHeight);
  ctx.fillStyle = '#fb7876'; ctx.fillRect(0, gameHeight - 1, s.width, 2);
  ctx.fillStyle = 'rgba(251,120,118,.08)'; ctx.fillRect(0, gameHeight - 7, s.width, 14);
}
