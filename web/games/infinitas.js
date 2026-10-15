/** INFINITAS calculations for normalized settings supplied by engine.js.
 * No device, OBS connection, storage, or game detection belongs in this module.
 */

// Fullscreen 1920×1080 reference, cross-checked against one INFINITAS capture.
// Internal lane size reported by an INFINITAS simulator author's measurements:
// https://note.com/masaoblue/n/n02ecb7426a76
export const FULLSCREEN_LANE_HEIGHT = 723;
// Standard fullscreen reference, not coordinates measured from a user's OBS scene.
// 1P is cross-checked against a 1920x1080 capture; 2P mirrors its lane rectangle.
export const FULLSCREEN_LAYOUT = Object.freeze({
  canvasWidth: 1920, laneX: 75, laneWidth: 432, judgmentY: 723,
  scratchWidth: 5 / 3, blackKeyRatio: 7 / 9,
});

export function getAutomaticOverlayHeight(liftNumber) {
  // LIFT zero retains a transparent 1px surface, not a visible input area.
  return Math.max(1, Math.round(FULLSCREEN_LANE_HEIGHT * liftNumber / 1000));
}

/**
 * Approximate IIDX convention: green / 600 seconds visible above the judgment line.
 * KONAMI documents green as visibility duration, but not this numeric conversion:
 * https://p.eagate.573.jp/game/2dx/26/howto/play/option_speed.html
 * Treat this as a calibration starting point, not a measured game synchronization.
 * SUDDEN+ and LIFT use a continuous /1000 approximation at fullscreen 1080p.
 * Output dimensions only crop trails and never change their pixel speed.
 */
export function getGameGeometry(settings) {
  return {
    baseHeight: FULLSCREEN_LANE_HEIGHT,
    visibleHeight: FULLSCREEN_LANE_HEIGHT * (1000 - settings.suddenNumber - settings.liftNumber) / 1000,
    suddenHeight: FULLSCREEN_LANE_HEIGHT * settings.suddenNumber / 1000,
    liftHeight: FULLSCREEN_LANE_HEIGHT * settings.liftNumber / 1000,
  };
}

export function getSpeed(settings) {
  return getGameGeometry(settings).visibleHeight * 600 / settings.greenNumber * settings.speedScale;
}

/** OBS top-left position at 100% scale for the standard fullscreen reference.
 * Size changes crop/extend the output, never move the game judgment line.
 * SUDDEN covers the top; only LIFT moves the judgment line vertically.
 */
export function getObsPlacement(settings) {
  const x = settings.side === '2P'
    ? FULLSCREEN_LAYOUT.canvasWidth - FULLSCREEN_LAYOUT.laneX - FULLSCREEN_LAYOUT.laneWidth
    : FULLSCREEN_LAYOUT.laneX;
  return {
    x: x + settings.obsOffsetX,
    y: FULLSCREEN_LAYOUT.judgmentY - Math.round(FULLSCREEN_LANE_HEIGHT * settings.liftNumber / 1000) + settings.obsOffsetY,
  };
}
