import { normalizeSettings } from './engine.js';
import { t } from './i18n.js';
import { drawShortInputComparison } from './short-input-preview.js';

const keys = ['inputBodyEnabled', 'shortInputEnabled', 'shortInputThresholdMs', 'shortInputPercent'];
const values = raw => {
  const normalized = normalizeSettings(raw);
  return Object.fromEntries(keys.map(key => [key, normalized[key]]));
};
const same = (a, b) => keys.every(key => a[key] === b[key]);

// A local draft never sends test inputs or changes the live overlay. Only Apply
// writes settings. SettingsWriter resolves network ordering; this class only
// owns the user's draft, keeping it through external edits and failed saves.
export class ShortInputDraft {
  constructor(settings = {}) {
    this.saved = values(settings); this.draft = {...this.saved};
    this.saving = false; this.error = false;
  }
  get dirty() { return !same(this.draft, this.saved); }
  receive(settings) {
    const incoming = values(settings);
    const keepDraft = this.dirty || this.saving;
    this.saved = incoming;
    if (!keepDraft) this.draft = {...incoming};
  }
  edit(patch) {
    if (this.saving) return;
    this.draft = values({...this.draft, ...patch}); this.error = false;
  }
  discard() {
    if (this.saving) return;
    this.draft = {...this.saved}; this.error = false;
  }
  begin() {
    if (this.saving || !this.dirty) return null;
    this.saving = true; this.error = false;
    this.submitted = {...this.draft};
    return {...this.submitted};
  }
  finish(success, effective = this.saved) {
    this.saving = false; this.error = !success;
    if (success) { this.saved = values(effective); this.draft = {...this.saved}; }
  }
}

export class ShortInputControls {
  constructor(root, applySettings) {
    this.root = root; this.applySettings = applySettings;
    this.state = new ShortInputDraft(); this.settings = {};
    this.get = id => root.querySelector('#' + id);
    this.get('inputBodyEnabled').addEventListener('change', event => this.edit({inputBodyEnabled:event.target.checked}));
    this.get('shortInputEnabled').addEventListener('change', event => this.edit({shortInputEnabled:event.target.checked}));
    for (const name of ['shortInputThresholdMs', 'shortInputPercent']) {
      this.get(name).addEventListener('change', event => this.edit({[name]:event.target.value}));
    }
    this.get('short-input-slider').addEventListener('input', event => this.edit({shortInputPercent:event.target.value}));
    for (const button of root.querySelectorAll('[data-short-percent]')) {
      button.addEventListener('click', () => this.edit({shortInputPercent:Number(button.dataset.shortPercent)}));
    }
    this.get('short-input-discard').addEventListener('click', () => { this.state.discard(); this.render(); });
    this.get('short-input-apply').addEventListener('click', () => this.apply());
  }
  edit(patch) { this.state.edit(patch); this.render(); }
  sync(settings) { this.settings = settings; this.state.receive(settings); this.render(); }
  async apply() {
    const submitted = this.state.begin(); if (!submitted) return;
    this.render();
    try { const effective = await this.applySettings(submitted); this.state.finish(true, effective); }
    catch { this.state.finish(false); }
    this.render();
  }
  render() {
    const s = this.state.draft, disabled = !s.inputBodyEnabled || !s.shortInputEnabled || this.state.saving;
    this.get('inputBodyEnabled').checked = s.inputBodyEnabled;
    this.get('inputBodyEnabled').disabled = this.state.saving;
    this.get('shortInputEnabled').checked = s.shortInputEnabled;
    this.get('shortInputEnabled').disabled = !s.inputBodyEnabled || this.state.saving;
    for (const name of ['shortInputThresholdMs', 'shortInputPercent']) {
      this.get(name).value = s[name]; this.get(name).disabled = disabled;
    }
    const slider = this.get('short-input-slider');
    slider.value = s.shortInputPercent; slider.disabled = disabled;
    slider.setAttribute('aria-valuetext', t('shortInputRatioValue', {percent:s.shortInputPercent, reduction:100 - s.shortInputPercent}));
    for (const button of this.root.querySelectorAll('[data-short-percent]')) {
      button.disabled = disabled;
      button.setAttribute('aria-pressed', String(Number(button.dataset.shortPercent) === s.shortInputPercent));
    }
    this.get('short-input-ratio').textContent = t(!s.inputBodyEnabled ? 'inputHeadOnly' : s.shortInputEnabled ? 'shortInputRatioValue' : 'shortInputOff', {
      percent:s.shortInputPercent, reduction:100 - s.shortInputPercent,
    });
    this.get('short-input-help').textContent = t(!s.inputBodyEnabled ? 'inputHeadOnlyHelp' : s.shortInputEnabled ? 'shortInputHelp' : 'shortInputOffHelp', {threshold:s.shortInputThresholdMs, percent:s.shortInputPercent});
    this.get('short-input-apply').disabled = this.state.saving || !this.state.dirty;
    this.get('short-input-discard').disabled = this.state.saving || (!this.state.dirty && !this.state.error);
    const status = this.get('short-input-status');
    status.textContent = t(this.state.saving ? 'shortInputSaving' : this.state.error ? 'shortInputSaveFailed'
      : this.state.dirty ? 'shortInputDraft' : 'shortInputCurrent');
    status.classList.toggle('save-error', this.state.error);
    drawShortInputComparison(this.get('short-input-comparison'), {...this.settings, ...s}, {
      original:t('shortInputOriginal'), current:t('shortInputAdjusted'), scratch:t('shortInputScratch'),
    });
  }
}
