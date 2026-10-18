// Standalone, synthetic comparison. Reads existing settings; never writes them.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { normalizeSettings } from '../../web/engine.js';

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, '../..');
const output = process.argv[2];
if (!output) throw new Error('Usage: node generate-browser.mjs OUTPUT_DIR [SETTINGS_JSON]');
const settings = normalizeSettings(process.argv[3]
  ? JSON.parse(fs.readFileSync(process.argv[3], 'utf8'))
  : { greenNumber: 270, suddenNumber: 70, liftNumber: 401, width: 432,
      scratchWidth: 5 / 3, blackKeyRatio: 7 / 9, noteHeight: 12,
      inputBodyEnabled: false, shortInputEnabled: false });
if (settings.width !== 432 || settings.overlayHeight !== 290)
  throw new Error('Pacing barcode analyzer requires 432 x 290 note region. No settings were changed.');
const uri = source => 'data:text/javascript;base64,' + Buffer.from(source).toString('base64');
const game = uri(fs.readFileSync(path.join(root, 'web/games/infinitas.js'), 'utf8'));
const engine = uri(fs.readFileSync(path.join(root, 'web/engine.js'), 'utf8')
  .replaceAll("'./games/infinitas.js'", JSON.stringify(game)));
const render = uri(fs.readFileSync(path.join(root, 'web/render.js'), 'utf8')
  .replaceAll("'./engine.js'", JSON.stringify(engine)));
const script = `
import { TrailEngine } from ${JSON.stringify(engine)};
import { drawOverlay, resizeCanvas } from ${JSON.stringify(render)};
const settings = ${JSON.stringify(settings)};
const canvas = document.querySelector('canvas');
const engine = new TrailEngine(settings);
const wallOrigin = Date.now(), perfOrigin = performance.now();
let index = -3, sequence = 0, previousDrawUs = 0;
function frame(raf) {
  const callback = performance.now(), wall = Date.now();
  while (index <= Math.floor((callback - perfOrigin + 250) / 120)) {
    const lane = ((index % 7) + 7) % 7 + 1;
    const start = wallOrigin + index++ * 120;
    engine.press(lane, start); engine.release(lane, start + 40);
  }
  const started = performance.now();
  const ctx = resizeCanvas(canvas, 432, 390);
  ctx.clearRect(0, 0, 432, 390);
  ctx.fillStyle = '#000'; ctx.fillRect(0, 290, 432, 100);
  drawOverlay(ctx, engine, settings, wall);
  const values = [++sequence, (raf-perfOrigin)*10, (callback-perfOrigin)*10,
    (wall-wallOrigin)*10, previousDrawUs];
  for (let row=0; row<5; row++) {
    const value = ((Math.round(values[row]) % 16777216) + 16777216) % 16777216;
    const y = 300 + 18*row;
    for (let bit=0; bit<24; bit++) {
      ctx.fillStyle = (value >>> bit) & 1 ? '#fff' : '#000';
      ctx.fillRect(8+bit*12, y, 10, 14);
    }
    ctx.fillStyle='#fff'; ctx.fillRect(308,y,12,14);
    ctx.fillStyle='#000'; ctx.fillRect(324,y,12,14);
  }
  previousDrawUs = (performance.now()-started)*1000;
  if (callback-perfOrigin < 180000) requestAnimationFrame(frame);
}
requestAnimationFrame(frame);
`;
fs.mkdirSync(output, { recursive: true });
fs.writeFileSync(path.join(output, 'browser.html'), '<!doctype html><meta charset="utf-8"><style>html,body{margin:0;overflow:hidden;background:transparent}canvas{display:block}</style><canvas></canvas><script type="module" src="'+uri(script)+'"></script>');
fs.writeFileSync(path.join(output, 'lift-settings.json'), JSON.stringify(settings, null, 2));
console.log(JSON.stringify({ output: path.resolve(output), width: 432, height: 390, noteHeight: settings.noteHeight }));
