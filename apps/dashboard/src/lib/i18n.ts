// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Minimal i18n scaffold. Mirrors the react-i18next shape (`useTranslation()`
 * + `t(key, params)`) so migration to the real library is a single-file swap
 * when we're ready to ship non-English UIs.
 *
 * Current coverage: English fallback only. Keys live in src/locales/*.json.
 * To add a locale: drop pt-BR.json next to en.json, register in LOCALE_MAP.
 *
 * CLAUDE.md says ~857 strings exist across 283 files; migrating them is a
 * separate concerted effort. This scaffold makes *new* strings first-class
 * translatable without blocking on the mass migration.
 */

import { useEffect, useState } from 'react';
import { getLocale } from './locale';
import en from '@/locales/en.json';

type Dict = Record<string, unknown>;

const LOCALE_MAP: Record<string, Dict> = {
  'en': en as Dict,
  'en-US': en as Dict,
  'en-GB': en as Dict,
};

function resolveDict(locale: string): Dict {
  if (LOCALE_MAP[locale]) return LOCALE_MAP[locale];
  const base = locale.split('-')[0];
	const baseDict = LOCALE_MAP[base!];
	if (baseDict) return baseDict;
  return en as Dict;
}

function lookup(dict: Dict, keyPath: string): string | undefined {
  const parts = keyPath.split('.');
  let cur: unknown = dict;
  for (const part of parts) {
    if (cur && typeof cur === 'object' && part in (cur as Record<string, unknown>)) {
      cur = (cur as Record<string, unknown>)[part];
    } else {
      return undefined;
    }
  }
  return typeof cur === 'string' ? cur : undefined;
}

/**
 * Interpolate ICU-lite: `Hello {name}` → `Hello Ader`. Pluralization via
 * `{count, plural, one {# account} other {# accounts}}` — minimal one/other
 * branching; not a full ICU parser, just enough for the common case.
 */
function format(template: string, params: Record<string, unknown> = {}): string {
  // plural blocks first
  let out = template.replace(
    /\{(\w+),\s*plural,\s*one\s*\{([^}]*)\}\s*other\s*\{([^}]*)\}\}/g,
    (_, key: string, one: string, other: string) => {
      const n = Number(params[key] ?? 0);
      const chosen = n === 1 ? one : other;
      return chosen.replace(/#/g, String(n));
    },
  );
  // simple placeholders
  out = out.replace(/\{(\w+)\}/g, (_, key: string) =>
    params[key] !== undefined ? String(params[key]) : `{${key}}`,
  );
  return out;
}

/** Direct translation function. Use inside event handlers or outside components. */
export function t(key: string, params?: Record<string, unknown>): string {
  const dict = resolveDict(getLocale());
  const found = lookup(dict, key);
  if (found !== undefined) return format(found, params);
  // Fall through to English
  const fallback = lookup(en as Dict, key);
  return fallback !== undefined ? format(fallback, params) : key;
}

/** React hook. Re-renders when the active locale changes. */
export function useTranslation() {
  const [locale, setLocaleState] = useState(() => getLocale());

  useEffect(() => {
    const onStorage = (e: StorageEvent) => {
      if (e.key === 'juno33-locale') setLocaleState(getLocale());
    };
    window.addEventListener('storage', onStorage);
    return () => window.removeEventListener('storage', onStorage);
  }, []);

  return {
    t: (key: string, params?: Record<string, unknown>) => t(key, params),
    locale,
  };
}
