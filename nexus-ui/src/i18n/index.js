// i18next bootstrap. Imported once from main.jsx (before render) so the
// active language is resolved before any component mounts.
//
// State model: i18next holds the active language; react-i18next's
// `useTranslation` re-renders subscribers on `changeLanguage`, so the header
// switcher and the Settings selector stay in sync without a custom context.
//
// Persistence: LanguageDetector reads `localStorage['nexus.language']` first,
// then the browser's `navigator.language`, falling back to English. The chosen
// language is written back to the same key (`caches: ['localStorage']`). For
// signed-in users, `useLanguage` additionally syncs the choice to their backend
// profile, and AuthProvider applies the saved profile language on login.
//
// Resources: every `locales/<lng>/<ns>.json` file is auto-discovered via Vite's
// import.meta.glob, so adding a new feature namespace (e.g. dashboard.json) only
// requires dropping the JSON files in — no edits here. `common` is the default
// namespace (shell/nav/header). Per-feature namespaces are loaded by name via
// useTranslation('<ns>').
import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import LanguageDetector from 'i18next-browser-languagedetector';

import { LANGUAGES } from './languages.js';

export const SUPPORTED_LNGS = LANGUAGES.map((l) => l.code);

// Eagerly bundle all locale JSON. Keys look like './locales/en/common.json'.
const modules = import.meta.glob('./locales/*/*.json', { eager: true });

const resources = {};
const namespaceSet = new Set();
for (const [path, mod] of Object.entries(modules)) {
  const match = path.match(/\.\/locales\/([^/]+)\/([^/]+)\.json$/);
  if (!match) continue;
  const [, lng, ns] = match;
  resources[lng] ??= {};
  resources[lng][ns] = mod.default ?? mod;
  namespaceSet.add(ns);
}

const namespaces = [...namespaceSet];

i18n
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    resources,
    fallbackLng: 'en',
    supportedLngs: SUPPORTED_LNGS,
    // Collapse regional variants ("en-US" → "en", "ja-JP" → "ja") so browser
    // detection maps onto our base-code resources.
    load: 'languageOnly',
    nonExplicitSupportedLngs: true,
    ns: namespaces,
    defaultNS: 'common',
    fallbackNS: 'common',
    detection: {
      order: ['localStorage', 'navigator'],
      lookupLocalStorage: 'nexus.language',
      caches: ['localStorage'],
    },
    // React already escapes interpolated values.
    interpolation: { escapeValue: false },
    // Resources are bundled synchronously, so Suspense is unnecessary and
    // would force every t() consumer to sit under a boundary.
    react: { useSuspense: false },
  });

export default i18n;
