import json, pathlib
# Phase 68 — add nav.systemSummary across all locales (the /docs item is removed;
# nav.documentation is left in place harmlessly). JSON round-trip avoids
# line-insert errors.
TRANSLATIONS = {
    "en": "System Summary", "de": "Systemübersicht", "es": "Resumen del sistema",
    "fil": "Buod ng Sistema", "fr": "Résumé du système", "ja": "システム概要",
    "vi": "Tóm tắt hệ thống",
}
base = pathlib.Path("src/i18n/locales")
for lang, label in TRANSLATIONS.items():
    p = base / lang / "common.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    if "nav" not in data:
        print(f"SKIP {lang}: no nav block"); continue
    data["nav"]["systemSummary"] = label
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"OK  {lang}: {label!r}")
