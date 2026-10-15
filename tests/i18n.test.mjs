import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { translations } from '../web/translations.js';
import { LOCALES, LANGUAGE_STORAGE_KEY, resolveLocale, translate, readLocale, saveLocale, initialLocale, setLocale, getLocale, applyTranslations } from '../web/i18n.js';

const placeholders = text => [...text.matchAll(/\{(\w+)\}/g)].map(match => match[1]).sort();

test('all languages provide every UI key with matching interpolation placeholders', () => {
  const expectedKeys = Object.keys(translations.en).sort();
  for (const locale of LOCALES) {
    assert.deepEqual(Object.keys(translations[locale]).sort(), expectedKeys, locale);
    for (const key of expectedKeys) {
      const value = translations[locale][key];
      assert.equal(typeof value, 'string', `${locale}.${key}`);
      assert.ok(value.trim().length, `${locale}.${key} must not be empty`);
      assert.deepEqual(placeholders(value), placeholders(translations.en[key]), `${locale}.${key}`);
    }
  }
});

test('saved language wins, regional browser languages are supported, and unknown languages fall back to English', () => {
  assert.equal(resolveLocale('ja', ['ko-KR', 'en-US']), 'ja');
  assert.equal(resolveLocale(null, ['ko-KR', 'en']), 'ko');
  assert.equal(resolveLocale(undefined, ['ja-JP', 'en']), 'ja');
  assert.equal(resolveLocale(undefined, ['fr-FR', 'JA_jp', 'ko']), 'ja');
  assert.equal(resolveLocale('en-GB', ['ko']), 'en');
  assert.equal(resolveLocale('invalid', ['ko']), 'ko');
  assert.equal(resolveLocale(null, ['fr-FR']), 'en');
  assert.equal(resolveLocale(null, []), 'en');
});

test('language preference persists without changing exported overlay settings and tolerates disabled storage', () => {
  const entries = new Map();
  const storage = { getItem:key => entries.get(key), setItem:(key, value) => entries.set(key, value) };
  assert.equal(readLocale(storage, ['ko-KR']), 'ko');
  assert.equal(saveLocale(storage, 'ja'), 'ja');
  assert.deepEqual([...entries], [[LANGUAGE_STORAGE_KEY, 'ja']]);
  assert.equal(readLocale(storage, ['ko-KR']), 'ja');
  const denied = { getItem() { throw new Error('denied'); }, setItem() { throw new Error('denied'); } };
  assert.equal(readLocale(denied, ['ja-JP']), 'ja');
  assert.equal(saveLocale(denied, 'ko'), 'ko');
  assert.equal(readLocale(undefined, ['en']), 'en');
});

test('desktop language query overrides saved preference only when a supported language is provided', () => {
  const entries = new Map([[LANGUAGE_STORAGE_KEY, 'ko']]);
  const storage = {getItem:key => entries.get(key), setItem:(key, value) => entries.set(key, value)};
  assert.equal(initialLocale('?lang=ja', storage, ['en']), 'ja');
  assert.equal(entries.get(LANGUAGE_STORAGE_KEY), 'ja');
  assert.equal(initialLocale('', storage, ['en']), 'ja');
  assert.equal(initialLocale('?lang=not-supported', storage, ['en']), 'ja');
  assert.equal(initialLocale('?other=en', undefined, ['ko']), 'ko');
  assert.equal(initialLocale('?lang=en', undefined, ['ko']), 'en');
});

test('interpolation preserves numeric zero, plain text, and unknown error messages', () => {
  assert.equal(translate('en', 'speedDetail', {height:'382.5', seconds:'0.450'}), 'Visible lane 382.5 px · visibility 0.450 s');
  assert.equal(translate('ja', 'requestFailed', {status:503}), 'リクエストに失敗しました (503)');
  assert.equal(translate('ko', 'keyPress', {key:0}), '건반 0 누르기');
  assert.equal(translate('en', 'requestFailed'), 'Request failed ({status})');
  assert.equal(translate('unknown', 'clear'), 'Clear input notes');
  assert.equal(translate('ja', 'Diagnostic from driver'), 'Diagnostic from driver');
  assert.equal(translate('ja', 'toString'), 'toString');
  assert.equal(translate('en', 'keyPress', {key:'<img src=x>'}), 'Hold key <img src=x>');
});

test('language switches update visible and accessibility text as plain text', () => {
  const label = { dataset:{ i18n:'greenNumber' }, textContent:'' };
  const aria = { dataset:{ i18nAriaLabel:'previewLabel' }, attributes:{}, setAttribute(name, value) { this.attributes[name] = value; } };
  const root = { documentElement:{lang:'en'}, querySelectorAll(selector) { return selector === '[data-i18n]' ? [label] : [aria]; } };
  for (const [locale, expected] of [['ja','緑数字'], ['ko','녹숫'], ['en','Green number']]) {
    setLocale(locale); applyTranslations(root);
    assert.equal(getLocale(), locale);
    assert.equal(root.documentElement.lang, locale);
    assert.equal(label.textContent, expected);
    assert.equal(aria.attributes['aria-label'], translations[locale].previewLabel);
  }
});

test('both HTML entry points and literal runtime messages reference existing dictionary keys', async () => {
  for (const filename of ['index.html', 'overlay.html']) {
    const html = await readFile(new URL(`../web/${filename}`, import.meta.url), 'utf8');
    for (const match of html.matchAll(/data-i18n(?:-aria-label)?="([^"]+)"/g)) {
      assert.ok(Object.hasOwn(translations.en, match[1]), `${filename}: ${match[1]}`);
    }
    // A translated node's contents are replaced: never mark a label/select with child controls.
    assert.doesNotMatch(html, /<(?:label|select)[^>]*\sdata-i18n="/);
  }
  for (const filename of ['app.js', 'setup.js', 'short-input-controls.js']) {
    const app = await readFile(new URL(`../web/${filename}`, import.meta.url), 'utf8');
    for (const match of app.matchAll(/\b(?:t|toast)\('([^']+)'/g)) {
      assert.ok(Object.hasOwn(translations.en, match[1]), `${filename}: ${match[1]}`);
    }
    for (const match of app.matchAll(/'((?:setup|first)[A-Z][A-Za-z]+)'/g)) {
      assert.ok(Object.hasOwn(translations.en, match[1]), `${filename}: ${match[1]}`);
    }
  }
});


test('user-facing input note terminology and both physical scratch directions are localized', () => {
  const wording = {en:'input notes', ko:'입력 노트', ja:'入力ノーツ'};
  for (const locale of LOCALES) {
    const dictionary = translations[locale];
    assert.ok(dictionary.clear.toLowerCase().includes(wording[locale]), locale);
    for (const [key, value] of Object.entries(dictionary)) {
      assert.doesNotMatch(value.replaceAll('Lift Trace', ''), /흔적|軌跡|\btrails?\b|\btraces?\b/i, `${locale}.${key}`);
    }
    assert.ok(dictionary.scratchClockwise.includes('↻'));
    assert.ok(dictionary.scratchCounterclockwise.includes('↺'));
    assert.ok(dictionary.setupRotateClockwise.includes('↻'));
    assert.ok(dictionary.setupRotateCounterclockwise.includes('↺'));
  }
});

test('settings page has unique IDs and every literal app control exists', async () => {
  const html = await readFile(new URL('../web/index.html', import.meta.url), 'utf8');
  const app = await readFile(new URL('../web/app.js', import.meta.url), 'utf8');
  const ids = [...html.matchAll(/\bid="([^"]+)"/g)].map(match => match[1]);
  assert.equal(new Set(ids).size, ids.length, 'HTML IDs must be unique');
  for (const match of app.matchAll(/\$\('([^']+)'\)/g)) {
    assert.ok(ids.includes(match[1]), `Missing app control: ${match[1]}`);
  }
  const fields = app.match(/const fields = \[([^\]]+)\]/)[1];
  for (const match of fields.matchAll(/'([^']+)'/g)) {
    assert.ok(ids.includes(match[1]), `Missing synchronized settings control: ${match[1]}`);
  }
});
