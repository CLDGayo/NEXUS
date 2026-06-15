// Single source of truth for the supported UI languages. The `native` label
// is what users see in both the header Globe switcher and the Settings
// selector (shown in each language's own script — e.g. "日本語", "Español").
// English is the default fallback (see i18n/index.js).
export const LANGUAGES = [
  { code: 'en', native: 'English' },
  { code: 'vi', native: 'Tiếng Việt' },
  { code: 'fil', native: 'Filipino' },
  { code: 'de', native: 'Deutsch' },
  { code: 'fr', native: 'Français' },
  { code: 'es', native: 'Español' },
  { code: 'ja', native: '日本語' },
];
