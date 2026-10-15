const copy = value => structuredClone(value);
const same = (a, b) => {
  if (Object.is(a, b)) return true;
  if (!a || !b || typeof a !== 'object' || typeof b !== 'object' || Array.isArray(a) !== Array.isArray(b)) return false;
  const keys = Object.keys(a);
  return keys.length === Object.keys(b).length && keys.every(key => Object.hasOwn(b, key) && same(a[key], b[key]));
};

/** Serialize complete settings writes and protect the newest local draft from old SSE echoes. */
export class SettingsWriter {
  constructor(write, {read, onRefresh = () => {}, clock = globalThis, echoTimeoutMs = 2000, refreshTimeoutMs = 2000} = {}) {
    this.write = write; this.read = read; this.onRefresh = onRefresh;
    this.clock = clock; this.echoTimeoutMs = echoTimeoutMs; this.refreshTimeoutMs = refreshTimeoutMs;
    this._tail = Promise.resolve(); this._count = 0;
    this._latest = null; this._active = null; this._successful = null; this._remote = null;
    this._received = 0; this._written = 0; this._recovery = null; this._refreshing = null;
  }
  get pending() { return this._count > 0 || this._latest !== null; }
  get latest() {
    const value = this._latest?.settings ?? this._remote ?? this._successful?.settings;
    return value === undefined || value === null ? null : copy(value);
  }
  current(fallback = {}) { return this.latest ?? copy(fallback); }
  receive(settings) {
    this._remote = copy(settings); this._received++;
    for (const item of [this._active, this._latest, this._successful]) {
      if (item?.started && same(item.settings, settings)) item.confirmed = true;
    }
    this._release();
    return this.current(settings);
  }
  _release() {
    if (this._count === 0 && this._latest?.succeeded && this._latest.confirmed) {
      // SSE is ordered: a snapshot received after our confirmation may be a
      // newer edit from another window. Never replace it with our submission.
      this._latest = null;
      this._clearRecovery();
    }
  }
  _clearRecovery() {
    if (this._recovery !== null) this.clock.clearTimeout(this._recovery);
    this._recovery = null;
  }
  _scheduleRecovery() {
    this._clearRecovery();
    if (this._count || !this._latest?.succeeded) return;
    this._recovery = this.clock.setTimeout(() => {
      this._recovery = null; void this.refresh();
    }, this.echoTimeoutMs);
  }
  async _readBounded() {
    if (!this.read) throw new Error('Settings refresh is unavailable.');
    const controller = new AbortController();
    let timer;
    try {
      return await Promise.race([
        Promise.resolve().then(() => this.read(controller.signal)),
        new Promise((_, reject) => {
          timer = this.clock.setTimeout(() => {
            controller.abort(); reject(new Error('Settings refresh timed out.'));
          }, this.refreshTimeoutMs);
        }),
      ]);
    } finally { this.clock.clearTimeout(timer); }
  }
  /** Reconcile after a lost echo or reconnect; no server changes are required. */
  refresh() {
    if (this._count) return Promise.resolve(this.current());
    if (this._refreshing) return this._refreshing;
    this._clearRecovery();
    const written = this._written, received = this._received;
    const guarded = this._latest;
    this._refreshing = (async () => {
      let snapshot, refreshed = false;
      try { snapshot = await this._readBounded(); refreshed = true; }
      catch { /* A committed save stays useful offline; later SSE can recover. */ }
      if (written !== this._written || this._count) return this.current();
      // A GET started earlier must not overwrite a later SSE snapshot. If the
      // refresh fails without new evidence, keep the last successful write.
      if (received === this._received) {
        if (refreshed) this._remote = copy(snapshot);
        else if (guarded) this._remote = copy(guarded.settings);
      }
      this._latest = null;
      if (this._successful) this._successful.confirmed = true;
      this._clearRecovery();
      const effective = this.current(); this.onRefresh(effective);
      return effective;
    })().finally(() => {
      this._refreshing = null;
      // A newer save may have superseded this request while it was in flight.
      if (this._latest) this._scheduleRecovery();
    });
    return this._refreshing;
  }
  save(settings) {
    const item = { settings: copy(settings), started: false, succeeded: false, confirmed: false };
    this._latest = item; this._count++; this._written++; this._clearRecovery();
    const operation = this._tail.then(async () => {
      item.started = true; this._active = item;
      try {
        await this.write(copy(item.settings));
        item.succeeded = true; this._successful = item;
      } catch (error) {
        if (this._latest === item) {
          this._latest = this._successful && !this._successful.confirmed ? this._successful : null;
        }
        throw error;
      } finally {
        this._active = null; this._count--; this._release();
        this._scheduleRecovery();
      }
    });
    // A failed request rejects its caller, but must not poison later saves.
    this._tail = operation.catch(() => {});
    return operation;
  }
}
