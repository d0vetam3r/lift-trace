import { DEFAULTS, normalizeSettings, TrailEngine, ScratchTracker } from './engine.js';

export async function api(path, body) {
  const response = await fetch(path, body === undefined ? {} : {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  });
  if (!response.ok) throw new Error(`요청 실패 (${response.status})`);
  return response.json();
}

export function cleanConfig(raw = {}) {
  return { ...normalizeSettings(raw), inputMode: raw.inputMode === 'native' ? 'native' : 'demo' };
}

/** Accept exported and legacy settings, without treating unrelated JSON as a reset. */
export function parseSettingsFile(text) {
  let raw;
  try { raw = JSON.parse(text); } catch { throw new Error('importInvalid'); }
  const isObject = value => value !== null && typeof value === 'object' && !Array.isArray(value);
  if (!isObject(raw)) throw new Error('importInvalid');
  const settings = Object.hasOwn(raw, 'settings') ? raw.settings : raw;
  const knownKeys = new Set([...Object.keys(DEFAULTS), 'inputMode', 'liftHeight', 'visibleHeight']);
  if (!isObject(settings) || !Object.keys(settings).some(key => knownKeys.has(key))) {
    throw new Error('importInvalid');
  }
  return settings;
}

/** All rendering clients use server timestamps, including the OBS browser source. */
export class InputClient extends EventTarget {
  constructor() {
    super(); this.settings = cleanConfig(DEFAULTS); this.engine = new TrailEngine(this.settings);
    this.scratch = new ScratchTracker(this.settings); this.buttons = []; this.stream = null;
  }
  emit(name, detail) { this.dispatchEvent(new CustomEvent(name, { detail })); }
  configure(raw) {
    const next = cleanConfig(raw);
    const mappingChanged = next.inputMode !== this.settings.inputMode || next.axisIndex !== this.settings.axisIndex
      || next.scratchInvert !== this.settings.scratchInvert || JSON.stringify(next.buttonMap) !== JSON.stringify(this.settings.buttonMap);
    this.settings = next; this.engine.configure(next); this.scratch.configure(next);
    if (mappingChanged) this.reset();
    this.emit('settings', next);
  }
  reset() { this.engine.reset(); this.scratch.reset(); this.buttons = []; this.emit('reset', {}); }
  applyKey(event) {
    const time = Number.isFinite(event.time) ? event.time : Date.now();
    if (event.down) this.engine.press(event.lane, time, event.direction || 0);
    else this.engine.release(event.lane, time);
  }
  native(event) {
    this.emit('raw', event);
    if (this.settings.inputMode !== 'native') return;
    const time = event.time;
    this.settings.buttonMap.forEach((button, index) => {
      const down = Boolean(event.buttons[button]);
      if (down !== Boolean(this.buttons[index])) this.applyKey({ lane: index + 1, down, time });
      this.buttons[index] = down;
    });
    const value = event.axes[this.settings.axisIndex];
    for (const item of this.scratch.update(value, time)) this.applyKey({ lane: 0, ...item });
  }
  tick(time) {
    if (this.settings.inputMode === 'native') for (const item of this.scratch.tick(time)) this.applyKey({ lane: 0, ...item });
  }
  async start() {
    // Initial SSE messages supply settings, and the stream retries initial failures.
    this.stream = new EventSource('/api/events');
    this.stream.onopen = () => this.emit('connection', true);
    this.stream.onerror = () => { this.reset(); this.emit('connection', false); };
    this.stream.onmessage = message => {
      let event; try { event = JSON.parse(message.data); } catch { return; }
      if (event.type === 'input') this.native(event);
      if (event.type === 'key' && this.settings.inputMode === 'demo') this.applyKey(event);
      if (event.type === 'reset') this.reset();
      if (event.type === 'settings') this.configure(event.settings);
      if (event.type === 'status') this.emit('status', event);
      if (event.type === 'demo') this.emit('demo', event);
    };
  }
}
