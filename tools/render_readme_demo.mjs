/** Render an original synthetic README animation with the application's renderer. */
import { createRequire } from 'node:module';
import { execFileSync } from 'node:child_process';
import { mkdtemp, mkdir, readFile, rm, writeFile, stat } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { TrailEngine, normalizeSettings, getGameGeometry } from '../web/engine.js';
import { drawPreview, SCRATCH_COLORS } from '../web/render.js';

const root = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const args = process.argv.slice(2);
if (args.includes('--help')) {
  console.log(`Render the README's synthetic input demo. No game or controller is needed.
Usage: node tools/render_readme_demo.mjs [--output FILE.gif] [--python PYTHON] [--preview FILE.png]
Optional developer tools: @napi-rs/canvas 0.1.100 and Python Pillow 12.3.0.
See docs/images/README.md. These are not application dependencies.`);
  process.exit(0);
}
const options = { output:path.join(root, 'docs/images/lift-trace-demo.gif'), python:'python', preview:null };
for (let index = 0; index < args.length; index += 2) {
  const key = args[index]?.slice(2);
  if (!args[index]?.startsWith('--') || !Object.hasOwn(options, key) || !args[index + 1]) {
    throw new Error('Unknown or incomplete option. Run with --help.');
  }
  options[key] = args[index + 1];
}
if (!options.output.toLowerCase().endsWith('.gif')) throw new Error('--output must name a GIF file.');
const require = createRequire(import.meta.url);
let createCanvas;
try { ({createCanvas} = require('@napi-rs/canvas')); }
catch { throw new Error('Install the optional @napi-rs/canvas tool; see docs/images/README.md.'); }

const demo = JSON.parse(await readFile(path.join(root, 'web/demo.json'), 'utf8'));
const settings = normalizeSettings({width:432, scratchWidth:5/3, blackKeyRatio:7/9,
  liftNumber:401, suddenNumber:70, greenNumber:300, background:'black', showGuides:true});
const gameHeight = Math.min(320, getGameGeometry(settings).visibleHeight);
const laneHeight = gameHeight + settings.overlayHeight;
const scheduled = demo.notes.flatMap(note => [
  {lane:note.lane, time:note.start, down:true, direction:note.direction || 0},
  {lane:note.lane, time:note.start + note.duration, down:false, direction:note.direction || 0},
]).sort((left, right) => left.time - right.time || Number(left.down) - Number(right.down) || left.lane - right.lane);
const gameNotes = demo.notes.map(note => ({lane:note.lane, start:note.start,
  end:note.start + note.duration, long:note.duration > 300, direction:note.direction || 0}));
const WIDTH = 900, HEIGHT = 620, FPS = 25;
const engine = new TrailEngine(settings);
const canvas = createCanvas(WIDTH, HEIGHT);
const laneCanvas = createCanvas(settings.width, laneHeight);
laneCanvas.style = {};
globalThis.window = {devicePixelRatio:1};
const ctx = canvas.getContext('2d');
const palette = {bg:'#0b1018', panel:'#131c29', border:'#263548', text:'#eef4fc', muted:'#a3b4c9', cyan:'#70dce3'};
const lane = {x:34, y:105, scale:0.75};
const judgmentY = lane.y + gameHeight * lane.scale;

function text(value, x, y, size = 14, color = palette.text, weight = 400) {
  ctx.font = `${weight} ${size}px Arial, sans-serif`; ctx.fillStyle = color; ctx.fillText(value, x, y);
}
function card(x, y, width, height, fill = palette.panel, stroke = palette.border, radius = 12) {
  ctx.beginPath(); ctx.roundRect(x, y, width, height, radius); ctx.fillStyle = fill; ctx.fill();
  ctx.strokeStyle = stroke; ctx.lineWidth = 1; ctx.stroke();
}
function arrow(x, y, radius, direction, color) {
  const start = direction > 0 ? 0.4 * Math.PI : 0.6 * Math.PI;
  const end = direction > 0 ? 2 * Math.PI : -Math.PI;
  const tipX = x + Math.cos(end) * radius, tipY = y + Math.sin(end) * radius;
  const tx = -Math.sin(end) * direction, ty = Math.cos(end) * direction;
  const wing = radius * 0.5;
  ctx.beginPath(); ctx.arc(x, y, radius, start, end, direction < 0);
  ctx.moveTo(tipX - tx * wing - ty * wing, tipY - ty * wing + tx * wing);
  ctx.lineTo(tipX, tipY); ctx.lineTo(tipX - tx * wing + ty * wing, tipY - ty * wing - tx * wing);
  ctx.strokeStyle = color; ctx.lineWidth = 2.5; ctx.lineCap = 'round'; ctx.lineJoin = 'round'; ctx.stroke();
}
function phase(now) {
  if (now < 1650) return ['Short presses', 'Taps and two scratch directions'];
  if (now < 2350) return ['Play together', 'Several keys can light at once'];
  if (now < 4450) return ['Hold an input', 'The input note grows while held'];
  if (now < 4920) return ['Change direction', 'A reverse turn starts a new segment'];
  if (now < 6300) return ['Release and repeat', 'Released input notes keep falling'];
  return ['Ready for the next loop', 'Inputs show timing and duration'];
}
function drawFrame(now) {
  drawPreview(laneCanvas, {settings, engine}, now, gameNotes);
  ctx.fillStyle = palette.bg; ctx.fillRect(0, 0, WIDTH, HEIGHT);
  text('LIFT TRACE', 34, 40, 25, palette.text, 700);
  text('Your inputs, continuing below the judgment line.', 34, 66, 16, palette.muted);
  card(716, 21, 150, 29, '#172a30', '#29494f', 14);
  text('SYNTHETIC DEMO', 730, 40, 11, palette.cyan, 700);
  text('SIMULATED PLAY LANE', lane.x, 93, 11, palette.muted, 700);
  card(lane.x - 1, lane.y - 1, settings.width * lane.scale + 2, laneHeight * lane.scale + 2, palette.panel, palette.border, 2);
  ctx.drawImage(laneCanvas, lane.x, lane.y, settings.width * lane.scale, laneHeight * lane.scale);
  ctx.fillStyle = '#fb7876'; ctx.fillRect(lane.x, judgmentY - 1, settings.width * lane.scale, 2);
  text('LIFT TRACE INPUT DISPLAY', lane.x, 586, 11, palette.cyan, 700);

  card(394, 105, 472, 177);
  text('NOW PLAYING', 418, 132, 11, palette.muted, 700);
  const [title, description] = phase(now);
  text(title, 418, 164, 23, palette.text, 700);
  text(description, 418, 190, 15, palette.muted);
  arrow(431, 225, 11, 1, SCRATCH_COLORS.clockwise);
  text('Clockwise', 454, 230, 14, SCRATCH_COLORS.clockwise, 700);
  arrow(638, 225, 11, -1, SCRATCH_COLORS.counterclockwise);
  text('Counterclockwise', 661, 230, 14, SCRATCH_COLORS.counterclockwise, 700);
  text('Direction is shown by both color and arrow.', 418, 260, 13, palette.muted);

  ctx.beginPath(); ctx.moveTo(lane.x + settings.width * lane.scale + 1, judgmentY);
  ctx.lineTo(412, judgmentY); ctx.strokeStyle = '#fb7876'; ctx.lineWidth = 1.5; ctx.stroke();
  text('JUDGMENT LINE', 423, judgmentY - 8, 11, '#ff9e9b', 700);
  text('Inputs begin here, then move down.', 423, judgmentY + 15, 15, palette.text);

  card(394, 390, 472, 173);
  text('SIMULATED CONTROLLER INPUT', 418, 418, 11, palette.muted, 700);
  const active = engine.snapshot(now).filter(event => event.active);
  const scratch = active.find(event => event.lane === 0);
  const scratchColor = scratch ? (scratch.direction > 0 ? SCRATCH_COLORS.clockwise : SCRATCH_COLORS.counterclockwise) : '#324255';
  ctx.beginPath(); ctx.arc(449, 486, 33, 0, Math.PI * 2); ctx.fillStyle = '#0d141f'; ctx.fill();
  ctx.strokeStyle = scratchColor; ctx.lineWidth = 4; ctx.stroke();
  arrow(449, 486, 16, scratch?.direction || 1, scratchColor);
  for (let number = 1; number <= 7; number++) {
    const down = active.some(event => event.lane === number);
    const black = number % 2 === 0, x = 504 + (number - 1) * 47, y = black ? 455 : 468;
    const fill = down ? (black ? '#71b2ff' : '#e8edf5') : (black ? '#172336' : '#28374a');
    card(x, y, 35, 51, fill, down ? fill : '#40536a', 5);
    text(String(number), x + 13, y + 33, 14, down ? '#101824' : palette.muted, 700);
  }
  text('Button lights show which inputs are held.', 418, 544, 13, palette.muted);
  text('App renderer + synthetic inputs. No game footage or game data.', 394, 587, 12, palette.muted);
}

const encoding = String.raw`
from PIL import Image
from pathlib import Path
import json, sys
folder, output, duration = Path(sys.argv[1]), Path(sys.argv[2]), int(sys.argv[3])
paths = sorted(folder.glob('frame-*.png'))
sampled = paths[::max(1, len(paths) // 16)]
strip = Image.new('RGB', (225 * len(sampled), 155))
for index, file in enumerate(sampled):
    with Image.open(file) as image:
        strip.paste(image.convert('RGB').resize((225, 155)), (index * 225, 0))
# Keep the UI's exact meaning-bearing colors; a reduced thumbnail alone can
# omit thin scratch arrows, note heads and the judgment line from the palette.
fixed = ['ffb4aa', 'e45470', 'e8edf5', '71b2ff', 'fb7876', 'eef4fc', 'a3b4c9', '70dce3',
         '0b1018', '131c29', '263548', '000000', 'ff9e9b', '324255', '28374a', '172336']
colors = [int(color[index:index + 2], 16) for color in fixed for index in (0, 2, 4)]
colors += strip.quantize(colors=112, method=Image.Quantize.MEDIANCUT).getpalette()[:112 * 3]
palette = Image.new('P', (1, 1))
palette.putpalette(colors + [0] * (768 - len(colors)))
frames = []
for file in paths:
    with Image.open(file) as image:
        frames.append(image.convert('RGB').quantize(palette=palette, dither=Image.Dither.NONE))
frames[0].save(output, save_all=True, append_images=frames[1:], duration=duration,
               loop=0, optimize=True, disposal=1)
with Image.open(output) as image:
    total = 0
    for frame in range(image.n_frames):
        image.seek(frame)
        total += image.info['duration']
    print(json.dumps({'frames': image.n_frames, 'durationMs': total, 'size': image.size}))
`;
const temporaryRoot = path.resolve(tmpdir());
const temporary = await mkdtemp(path.join(temporaryRoot, 'lift-trace-demo-'));
if (path.dirname(path.resolve(temporary)) !== temporaryRoot || !path.basename(temporary).startsWith('lift-trace-demo-')) {
  throw new Error('Unexpected temporary frame directory.');
}
try {
  let nextEvent = 0;
  const count = Math.round(demo.period / 1000 * FPS);
  for (let frame = 0; frame < count; frame++) {
    const now = frame * 1000 / FPS;
    while (nextEvent < scheduled.length && scheduled[nextEvent].time <= now) {
      const event = scheduled[nextEvent++];
      if (event.down) engine.press(event.lane, event.time, event.direction);
      else engine.release(event.lane, event.time);
    }
    drawFrame(now);
    const png = canvas.toBuffer('image/png');
    await writeFile(path.join(temporary, `frame-${String(frame).padStart(4, '0')}.png`), png);
    if (options.preview && frame === Math.round(3400 / 1000 * FPS)) {
      await mkdir(path.dirname(path.resolve(options.preview)), {recursive:true});
      await writeFile(options.preview, png);
    }
  }
  await mkdir(path.dirname(path.resolve(options.output)), {recursive:true});
  const result = execFileSync(options.python, ['-c', encoding, temporary, options.output, String(1000 / FPS)], {encoding:'utf8'});
  console.log(result.trim());
  console.log(`Wrote ${options.output} (${(await stat(options.output)).size.toLocaleString()} bytes)`);
} finally {
  await rm(temporary, {recursive:true, force:true});
}
