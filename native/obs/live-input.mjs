// SPDX-License-Identifier: MIT
// Optional renderer observer: reuse the browser's input/history implementation.
// This process never reads a controller, writes settings, or controls recording.
import { pathToFileURL } from 'node:url';
import { InputClient } from '../../web/client.js';

export class LiveInputObserver {
  constructor() {
    this.client = new InputClient();
    this.ready = false;
    this.dirty = false;
  }

  accept(event) {
    if (!event || typeof event !== 'object' || Array.isArray(event)) throw new Error('Invalid observer event');
    switch (event.type) {
      case 'settings':
        if (!event.settings || typeof event.settings !== 'object' || Array.isArray(event.settings)) {
          throw new Error('Invalid observer settings');
        }
        this.client.configure(event.settings);
        this.ready = true;
        this.dirty = true;
        break;
      case 'input':
        if (!Array.isArray(event.buttons) || event.buttons.length > 32 || !Array.isArray(event.axes)
          || event.axes.length > 6 || !event.buttons.every(value => typeof value === 'boolean')
          || !event.axes.every(value => Number.isFinite(value) && value >= -1 && value <= 1)
          || !Number.isFinite(event.time) || event.time < 0) {
          throw new Error('Invalid observer input');
        }
        if (this.ready) this.client.native(event);
        this.dirty = true;
        break;
      case 'key':
        if (!Number.isInteger(event.lane) || event.lane < 0 || event.lane > 7
          || typeof event.down !== 'boolean' || !Number.isFinite(event.time) || event.time < 0
          || (event.direction !== undefined && ![-1, 0, 1].includes(event.direction))) {
          throw new Error('Invalid observer key');
        }
        if (this.ready && this.client.settings.inputMode === 'demo') this.client.applyKey(event);
        this.dirty = true;
        break;
      case 'reset':
        this.client.reset();
        this.dirty = true;
        break;
      // Status/demo messages do not change the canonical InputClient engine.
      case 'status': case 'demo': break;
      default: throw new Error('Unknown observer event');
    }
  }

  advance(now) {
    const beforeLength = this.client.engine.events.length;
    const beforeDirection = this.client.scratch.direction;
    this.client.tick(now);
    this.client.engine.prune(now);
    if (beforeLength !== this.client.engine.events.length || beforeDirection !== this.client.scratch.direction) {
      this.dirty = true;
    }
  }

  snapshot(now = Date.now()) {
    if (!this.ready) return null;
    if (!Number.isFinite(now) || now < 0) throw new Error('Invalid observer clock');
    this.advance(now);
    this.dirty = false;
    return {
      type: 'snapshot', epochMs: now,
      settings: { ...this.client.settings, buttonMap: [...this.client.settings.buttonMap] },
      // A copy keeps output/inspection from ever changing the existing engine.
      events: this.client.engine.events.map(event => ({ ...event })),
    };
  }
}

export function runObserver(input = process.stdin, output = process.stdout) {
  const observer = new LiveInputObserver();
  let pending = '', blocked = false, stopped = false, lastPublish = 0;
  const maxLineBytes = 128 * 1024;
  const finish = () => { stopped = true; clearInterval(timer); };
  const fail = () => {
    finish();
    // Do not echo settings, controller data, or local paths into diagnostics.
    process.stderr.write('Native renderer observer stopped: invalid stream or closed pipe.\n');
    process.exitCode = 1;
    input.destroy();
  };
  const publish = () => {
    if (stopped || !observer.ready) return;
    const now = Date.now();
    observer.advance(now);
    if (blocked || (!observer.dirty && now - lastPublish < 100 && now >= lastPublish)) return;
    const snapshot = observer.snapshot(now);
    blocked = !output.write(`${JSON.stringify(snapshot)}\n`);
    lastPublish = now;
  };
  const timer = setInterval(() => { try { publish(); } catch { fail(); } }, 4);
  output.on('drain', () => { blocked = false; });
  output.on('error', fail);
  input.setEncoding('utf8');
  input.on('data', chunk => {
    if (stopped) return;
    try {
      pending += chunk;
      let newline;
      while ((newline = pending.indexOf('\n')) >= 0) {
        const line = pending.slice(0, newline);
        pending = pending.slice(newline + 1);
        if (Buffer.byteLength(line) > maxLineBytes || !line.trim()) throw new Error('Invalid line');
        observer.accept(JSON.parse(line));
      }
      if (Buffer.byteLength(pending) > maxLineBytes) throw new Error('Oversized line');
    } catch { fail(); }
  });
  input.on('error', fail);
  input.on('end', () => {
    if (pending.trim()) fail();
    else finish();
  });
  return { observer, close: finish };
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) runObserver();
