import { translations } from './translations.js';

export const LOCALES = Object.freeze(['en', 'ko', 'ja']);
export const LANGUAGE_STORAGE_KEY = 'lift-trace-language';

function supportedLocale(value) {
  const language = typeof value === 'string' ? value.toLowerCase().split(/[-_]/)[0] : '';
  return LOCALES.includes(language) ? language : null;
}

/** Explicit preference wins; otherwise use the first supported browser language. */
export function resolveLocale(saved, browserLanguages = []) {
  return supportedLocale(saved) || browserLanguages.map(supportedLocale).find(Boolean) || 'en';
}

/** Plain text only: callers assign textContent or an accessibility attribute. */
export function translate(locale, key, values = {}) {
  const dictionary = translations[supportedLocale(locale) || 'en'];
  const template = Object.hasOwn(dictionary, key) ? dictionary[key] : Object.hasOwn(translations.en, key) ? translations.en[key] : key;
  return template.replace(/\{(\w+)\}/g, (match, name) => Object.hasOwn(values, name) ? String(values[name]) : match);
}

export function readLocale(storage, browserLanguages = []) {
  let saved;
  try { saved = storage?.getItem(LANGUAGE_STORAGE_KEY); } catch { /* Storage can be disabled. */ }
  return resolveLocale(saved, browserLanguages);
}

export function saveLocale(storage, locale) {
  const resolved = resolveLocale(locale);
  try { storage?.setItem(LANGUAGE_STORAGE_KEY, resolved); } catch { /* Keep working for this page. */ }
  return resolved;
}

/** The desktop launcher may select a language explicitly without discarding defaults. */
export function initialLocale(search, storage, browserLanguages = []) {
  const requested = supportedLocale(new URLSearchParams(search || '').get('lang'));
  return requested ? saveLocale(storage, requested) : readLocale(storage, browserLanguages);
}

let storage;
try { storage = globalThis.localStorage; } catch { /* OBS or private browser may deny storage. */ }
let locale = initialLocale(globalThis.location?.search, storage, globalThis.navigator?.languages || [globalThis.navigator?.language]);
export const getLocale = () => locale;
export const t = (key, values) => translate(locale, key, values);
export function setLocale(value) { locale = saveLocale(storage, value); return locale; }

export function applyTranslations(root = document) {
  if (root.documentElement) root.documentElement.lang = locale;
  for (const element of root.querySelectorAll('[data-i18n]')) element.textContent = t(element.dataset.i18n);
  for (const element of root.querySelectorAll('[data-i18n-aria-label]')) element.setAttribute('aria-label', t(element.dataset.i18nAriaLabel));
}
