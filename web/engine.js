/** Pure input-history geometry. No device, OBS, or browser dependencies. */
import * as infinitas from './games/infinitas.js';

// Preserve the existing imports used by the settings UI and renderer.
export { FULLSCREEN_LANE_HEIGHT, FULLSCREEN_LAYOUT } from './games/infinitas.js';

export const DEFAULTS = Object.freeze({
  greenNumber: 300,
  suddenNumber: 0,
  liftNumber: 0,
  heightMode: 'auto',
  manualOverlayHeight: 240,
  overlayHeight: 1,
  width: 400,
  scratchWidth: 1.6,
  blackKeyRatio: 1,
  noteHeight: 6,
  inputBodyEnabled: true,
  shortInputEnabled: false,
  shortInputThresholdMs: 200,
  shortInputPercent: 30,
  speedScale: 1,
  delayMs: 0,
  side: '1P',
  obsOffsetX: 0,
  obsOffsetY: 0,
  showGuides: true,
  background: 'black',
  trailOpacity: 0.38,
  scratchThreshold: 0.008,
  scratchStopMs: 100,
  scratchInvert: false,
  axisIndex: 0,
  buttonMap: Object.freeze([0, 1, 2, 3, 4, 5, 6]),
});

function bounded(value, fallback, min, max, integer = false) {
  const number = (typeof value === 'number' || (typeof value === 'string' && value.trim()))
    ? Number(value) : NaN;
  const result = Number.isFinite(number) ? Math.min(max, Math.max(min, number)) : fallback;
  return integer ? Math.round(result) : result;
}

/** Ignore unknown settings and bound data imported from files, URLs, or devices. */
export function normalizeSettings(raw = {}) {
  if (!raw || typeof raw !== 'object') raw = {};
  const liftNumber = bounded(raw.liftNumber, DEFAULTS.liftNumber, 0, 999, true);
  const suddenNumber = bounded(raw.suddenNumber, DEFAULTS.suddenNumber, 0, 999 - liftNumber, true);
  const heightMode = raw.heightMode === 'manual' ? 'manual' : 'auto';
  // Keep the user's custom crop separately from the effective auto height. Once
  // normalized, the derived overlayHeight must never replace this saved value.
  // Earlier versions called the custom crop overlayHeight, or before that liftHeight.
  const savedManualHeight = Object.hasOwn(raw, 'manualOverlayHeight') ? raw.manualOverlayHeight
    : Object.hasOwn(raw, 'overlayHeight') ? raw.overlayHeight : raw.liftHeight;
  const manualOverlayHeight = bounded(savedManualHeight, DEFAULTS.manualOverlayHeight, 40, 2160, true);
  const overlayHeight = heightMode === 'manual' ? manualOverlayHeight
    : infinitas.getAutomaticOverlayHeight(liftNumber);
  return {
    greenNumber: bounded(raw.greenNumber, DEFAULTS.greenNumber, 50, 2000),
    suddenNumber,
    liftNumber,
    heightMode,
    manualOverlayHeight,
    overlayHeight,
    width: bounded(raw.width, DEFAULTS.width, 160, 3840, true),
    scratchWidth: bounded(raw.scratchWidth, DEFAULTS.scratchWidth, 0.5, 4),
    blackKeyRatio: bounded(raw.blackKeyRatio, DEFAULTS.blackKeyRatio, 0.25, 2),
    noteHeight: bounded(raw.noteHeight, DEFAULTS.noteHeight, 2, 30),
    inputBodyEnabled: typeof raw.inputBodyEnabled === 'boolean' ? raw.inputBodyEnabled : DEFAULTS.inputBodyEnabled,
    shortInputEnabled: typeof raw.shortInputEnabled === 'boolean' ? raw.shortInputEnabled : DEFAULTS.shortInputEnabled,
    shortInputThresholdMs: bounded(raw.shortInputThresholdMs, DEFAULTS.shortInputThresholdMs, 1, 2000, true),
    shortInputPercent: bounded(raw.shortInputPercent, DEFAULTS.shortInputPercent, 1, 100, true),
    speedScale: bounded(raw.speedScale, DEFAULTS.speedScale, 0.25, 4),
    // Input cannot be anticipated. For the opposite timing correction, delay the game capture in OBS.
    delayMs: bounded(raw.delayMs, DEFAULTS.delayMs, 0, 2000),
    side: raw.side === '2P' ? '2P' : '1P',
    obsOffsetX: bounded(raw.obsOffsetX, DEFAULTS.obsOffsetX, -3840, 3840, true),
    obsOffsetY: bounded(raw.obsOffsetY, DEFAULTS.obsOffsetY, -2160, 2160, true),
    showGuides: typeof raw.showGuides === 'boolean' ? raw.showGuides : DEFAULTS.showGuides,
    background: raw.background === 'transparent' ? 'transparent' : 'black',
    trailOpacity: bounded(raw.trailOpacity, DEFAULTS.trailOpacity, 0, 1),
    scratchThreshold: bounded(raw.scratchThreshold, DEFAULTS.scratchThreshold, 0.001, 0.5),
    scratchStopMs: bounded(raw.scratchStopMs, DEFAULTS.scratchStopMs, 20, 1000),
    scratchInvert: typeof raw.scratchInvert === 'boolean' ? raw.scratchInvert : DEFAULTS.scratchInvert,
    axisIndex: bounded(raw.axisIndex, DEFAULTS.axisIndex, 0, 5, true),
    buttonMap: DEFAULTS.buttonMap.map((fallback, index) =>
      bounded(Array.isArray(raw.buttonMap) ? raw.buttonMap[index] : undefined, fallback, 0, 31, true)),
  };
}

// Keep normalization and the existing API here; only the game calculations move.
export function getGameGeometry(settings = DEFAULTS) {
  return infinitas.getGameGeometry(normalizeSettings(settings));
}

export function getSpeed(settings = DEFAULTS) {
  return infinitas.getSpeed(normalizeSettings(settings));
}

export function getObsPlacement(settings = DEFAULTS) {
  return infinitas.getObsPlacement(normalizeSettings(settings));
}

const MAX_EVENTS = 4096;
const validTime = value => typeof value === 'number' && Number.isFinite(value) && value >= 0;
const validLane = lane => Number.isInteger(lane) && lane >= 0 && lane <= 7;
const directionOf = value => value > 0 ? 1 : value < 0 ? -1 : 0;

export class TrailEngine {
  constructor(settings = {}) {
    this.settings = normalizeSettings(settings);
    this.reset();
  }

  configure(settings = {}) {
    // Callers editing the manual crop use manualOverlayHeight; overlayHeight is
    // derived output. Legacy aliases are migrated only on initial normalization.
    this.settings = normalizeSettings({ ...this.settings, ...settings });
    return this.settings;
  }

  reset() {
    this.events = [];
    this.active = new Map();
  }

  press(lane, timeMs, direction = 0) {
    if (!validLane(lane) || !validTime(timeMs)) return;
    direction = lane === 0 ? directionOf(direction) : 0;
    const previous = this.active.get(lane);
    if (previous) {
      if (lane !== 0 || previous.direction === direction || direction === 0) return;
      timeMs = Math.max(timeMs, previous.start);
      this.release(lane, timeMs);
    }
    const event = { lane, start: timeMs, end: null, direction };
    this.events.push(event);
    this.active.set(lane, event);
    // Remain bounded even if an input producer floods without ever rendering.
    if (this.events.length > MAX_EVENTS) {
      let excess = this.events.length - MAX_EVENTS;
      this.events = this.events.filter(item => {
        if (excess > 0 && item.end !== null) { excess--; return false; }
        return true;
      });
    }
  }

  release(lane, timeMs) {
    if (!validLane(lane) || !validTime(timeMs)) return;
    const event = this.active.get(lane);
    if (!event) return;
    event.end = Math.max(event.start, timeMs);
    this.active.delete(lane);
  }

  prune(timeMs) {
    if (!validTime(timeMs)) return;
    const visualTime = timeMs - this.settings.delayMs;
    const travelMs = (this.settings.overlayHeight + this.settings.noteHeight) / getSpeed(this.settings) * 1000;
    this.events = this.events.filter(event => event.end === null || event.end + travelMs >= visualTime);
  }

  snapshot(timeMs) {
    if (!validTime(timeMs)) return [];
    this.prune(timeMs);
    const visualTime = timeMs - this.settings.delayMs;
    const speedPerMs = getSpeed(this.settings) / 1000;
    return this.events.flatMap(event => {
      if (event.start > visualTime) return [];
      const active = event.end === null || event.end > visualTime;
      const headY = (visualTime - event.start) * speedPerMs;
      const tailY = active ? 0 : Math.max(0, (visualTime - event.end) * speedPerMs);
      return [{ ...event, headY, tailY, active }];
    });
  }
}

/**
 * Converts a wrapping absolute turntable axis in [-1, 1] to motion intervals.
 * Calibrated output direction: +1 is clockwise, -1 is counterclockwise.
 * This detects controller movement; it cannot infer the chart's scratch notes.
 * A producer must call tick() even when the device has not changed.
 */
export class ScratchTracker {
  constructor(settings = {}) {
    this.configure(settings);
    this.reset();
  }

  configure(settings = {}) {
    const s = normalizeSettings(settings);
    this.threshold = s.scratchThreshold;
    this.stopMs = s.scratchStopMs;
    this.directionMultiplier = s.scratchInvert ? -1 : 1;
  }

  reset() {
    this.previous = null;
    this.previousTime = null;
    this.pendingDelta = 0;
    this.direction = 0;
    this.lastMotionTime = null;
  }

  update(value, timeMs) {
    if (!Number.isFinite(value) || value < -1 || value > 1 || !validTime(timeMs)) return [];
    if (this.previousTime !== null && timeMs < this.previousTime) return [];
    const events = this.tick(timeMs);
    if (this.previous === null) {
      this.previous = value;
      this.previousTime = timeMs;
      return events;
    }
    let delta = value - this.previous;
    this.previous = value;
    this.previousTime = timeMs;
    // The endpoints are adjacent positions on the turntable's circular axis.
    if (delta > 1) delta -= 2;
    if (delta < -1) delta += 2;
    // A >quarter-turn jump in one sample is ambiguous (including reconnects).
    // Rebase without inventing a direction; normal high-frequency polling is expected.
    if (Math.abs(delta) > 0.5) {
      this.pendingDelta = 0;
      return events;
    }
    this.pendingDelta += delta * this.directionMultiplier;
    if (Math.abs(this.pendingDelta) + Number.EPSILON < this.threshold) return events;
    const direction = directionOf(this.pendingDelta);
    this.pendingDelta = 0;
    if (this.direction !== direction) {
      if (this.direction) events.push({ down: false, direction: this.direction, time: timeMs });
      events.push({ down: true, direction, time: timeMs });
      this.direction = direction;
    }
    this.lastMotionTime = timeMs;
    return events;
  }

  tick(timeMs) {
    if (!validTime(timeMs) || !this.direction || timeMs - this.lastMotionTime < this.stopMs) return [];
    // We cannot know the actual end of physical motion until this grace period passes.
    // Include that configurable grace time in the visible interval so its tail departs
    // smoothly now, instead of retrospectively jumping down the lift by stopMs.
    const event = { down: false, direction: this.direction, time: timeMs };
    this.direction = 0;
    this.lastMotionTime = null;
    this.pendingDelta = 0;
    return [event];
  }
}
