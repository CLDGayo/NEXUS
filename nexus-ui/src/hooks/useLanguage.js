import { useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { getToken } from '../lib/auth.js';
import { api } from '../lib/api.js';
import { LANGUAGES } from '../i18n/languages.js';

// Shared entry point for both language switcher touchpoints (header Globe +
// Settings selector). localStorage persistence is handled by the i18next
// detector (`caches: ['localStorage']`, key `nexus.language`); this hook adds a
// best-effort sync of the choice to the signed-in user's backend profile so it
// follows them across devices.
export function useLanguage() {
  const { i18n } = useTranslation();
  // i18n.language can carry a regional suffix (e.g. "en-US"); collapse to the
  // base code so the active row highlights correctly.
  const language = (i18n.resolvedLanguage || i18n.language || 'en').split('-')[0];

  const setLanguage = useCallback(
    (code) => {
      i18n.changeLanguage(code);
      // Fire-and-forget — a failed sync must never block the UI switch. The
      // localStorage cache already holds the choice for the next reload.
      if (getToken()) {
        api.patch('/users/me', { language: code }).catch(() => {
          /* offline / 5xx — choice still persisted locally */
        });
      }
    },
    [i18n],
  );

  return { language, setLanguage, languages: LANGUAGES };
}
