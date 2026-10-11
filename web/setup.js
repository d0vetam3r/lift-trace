/** Draft-only controller mapping. No settings are changed before apply(). */
export class ControllerSetup {
  constructor(deviceId) {
    this.deviceId = deviceId;
    this.phase = 'release';
    this.buttonMap = [];
    this.axisIndex = null;
    this.candidates = [];
    this.error = null;
    this.pendingButton = null;
    this.previousAxes = [];
    this.pendingAxes = [];
    this.movement = [];
    this.clockwiseDirections = [];
    this.scratchInvert = false;
  }

  feed(event) {
    if (['cancelled', 'detached', 'applied'].includes(this.phase)) return;
    if (event.device !== this.deviceId) { this.detach(); return; }
    const buttons = (event.buttons || []).flatMap((down, index) => down ? [index] : []);
    if (['scratchClockwise', 'scratchCounterclockwise'].includes(this.phase)) {
      this.trackAxes(event.axes || []);
      return;
    }
    if (['review', 'axisChoice'].includes(this.phase)) return;
    if (this.phase === 'release' || this.phase === 'retryRelease') {
      if (!buttons.length) this.phase = 'press';
      return;
    }
    if (buttons.length > 1 || (this.phase === 'held' && buttons.length && buttons[0] !== this.pendingButton)) {
      this.phase = 'retryRelease'; this.pendingButton = null; this.error = 'setupOneAtATime';
      return;
    }
    if (this.phase === 'press' && buttons.length === 1) {
      if (this.buttonMap.includes(buttons[0])) {
        this.phase = 'retryRelease'; this.error = 'setupDuplicate';
      } else {
        this.pendingButton = buttons[0]; this.phase = 'held'; this.error = null;
      }
    } else if (this.phase === 'held' && !buttons.length) {
      this.buttonMap.push(this.pendingButton); this.pendingButton = null;
      if (this.buttonMap.length === 7) this.retryScratch(event.axes || []);
      else this.phase = 'press';
    }
  }

  trackAxes(axes) {
    axes.forEach((value, index) => {
      const previous = this.previousAxes[index];
      if (!Number.isFinite(value) || !Number.isFinite(previous)) return;
      // WinMM reports -1..1; rotating axes can wrap between those endpoints.
      let delta = value - previous;
      if (delta > 1) delta -= 2;
      if (delta < -1) delta += 2;
      // Accumulate slow movement while cancelling small back-and-forth jitter.
      this.pendingAxes[index] = (this.pendingAxes[index] || 0) + delta;
      if (Math.abs(this.pendingAxes[index]) < 0.003) return;
      delta = this.pendingAxes[index]; this.pendingAxes[index] = 0;
      const score = this.movement[index] ||= { positive:0, negative:0 };
      if (delta > 0) score.positive += delta;
      else score.negative -= delta;
    });
    this.previousAxes = [...axes];
  }

  retryScratch(axes = this.previousAxes) {
    if (this.buttonMap.length !== 7) return;
    this.phase = 'scratchClockwise'; this.error = null; this.axisIndex = null; this.candidates = [];
    this.clockwiseDirections = []; this.scratchInvert = false;
    this.previousAxes = [...axes]; this.pendingAxes = []; this.movement = [];
  }

  checkScratch() {
    if (!['scratchClockwise', 'scratchCounterclockwise'].includes(this.phase)) return;
    const directions = this.movement.map(score => {
      if (!score) return 0;
      const dominant = Math.max(score.positive, score.negative);
      const reverse = Math.min(score.positive, score.negative);
      // A deliberate one-way turn must dominate incidental jitter. Both steps
      // are checked separately, so a back-and-forth turn cannot calibrate polarity.
      return dominant >= 0.12 && reverse <= Math.max(0.012, dominant * 0.1)
        ? (score.positive > score.negative ? 1 : -1) : 0;
    });
    if (this.phase === 'scratchClockwise') {
      if (!directions.some(Boolean)) {
        this.error = 'setupNoAxis'; this.pendingAxes = []; this.movement = []; return;
      }
      this.clockwiseDirections = directions;
      this.phase = 'scratchCounterclockwise'; this.error = null;
      this.pendingAxes = []; this.movement = []; return;
    }
    this.candidates = directions.flatMap((direction, index) => direction &&
      direction === -this.clockwiseDirections[index] ? [index] : []);
    if (!this.candidates.length) {
      this.error = 'setupOpposite'; this.pendingAxes = []; this.movement = []; return;
    }
    this.error = null;
    if (this.candidates.length === 1) this.chooseAxis(this.candidates[0]);
    else this.phase = 'axisChoice';
  }

  chooseAxis(index) {
    if (!['scratchCounterclockwise', 'axisChoice'].includes(this.phase) || !this.candidates.includes(index)) return false;
    this.axisIndex = index; this.scratchInvert = this.clockwiseDirections[index] < 0;
    this.phase = 'review'; return true;
  }

  apply() {
    if (this.phase !== 'review' || this.axisIndex === null) return null;
    const result = {buttonMap:[...this.buttonMap], axisIndex:this.axisIndex, scratchInvert:this.scratchInvert};
    this.phase = 'applied'; return result;
  }

  discard(phase) {
    this.phase = phase; this.buttonMap = []; this.axisIndex = null; this.candidates = [];
    this.pendingButton = null; this.previousAxes = []; this.pendingAxes = []; this.movement = []; this.error = null;
    this.clockwiseDirections = []; this.scratchInvert = false;
  }
  cancel() { this.discard('cancelled'); }
  detach() { this.discard('detached'); }
}
