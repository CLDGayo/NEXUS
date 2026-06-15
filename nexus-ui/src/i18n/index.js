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
import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import LanguageDetector from 'i18next-browser-languagedetector';

import { LANGUAGES } from './languages.js';
import en from './locales/en/common.json';
import vi from './locales/vi/common.json';
import fil from './locales/fil/common.json';
import de from './locales/de/common.json';
import fr from './locales/fr/common.json';
import es from './locales/es/common.json';
import ja from './locales/ja/common.json';

export const SUPPORTED_LNGS = LANGUAGES.map((l) => l.code);

const resources = {
  en: { common: en },
  vi: { common: vi },
  fil: { common: fil },
  de: { common: de },
  fr: { common: fr },
  es: { common: es },
  ja: { common: ja },
};

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
    ns: ['common'],
    defaultNS: 'common',
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
