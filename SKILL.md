---
name: i18n-release-gate
description: Gates a localization release by diffing every target locale against the base locale — lost or renamed ICU placeholders, plural categories the target language requires and the translation lacks, unbalanced markup, untranslated strings, glossary drift and length blowouts — and returns PASS/WARN/BLOCK per locale with the key and the reason. Reads .json (nested or flat), .po and .xliff. Use when a release is about to ship in multiple languages, a translation vendor delivered a batch, a locale shows literal braces on screen, a plural renders wrong in Russian or Arabic, or a team needs a per-locale gate before merging strings. Not for translating, for style review, or for choosing wording.
---

# Localization Release Gate

A localized build fails in ways that look like code bugs: `{count} items` printed as literal text, a plural that renders "5 товаров" instead of "5 товара", a missing key that falls back to English mid-screen, a German button that pushed the layout apart. All of them are visible in the strings before the build, which is what this gate does.

## Contract

1. **The base locale is the contract.** Placeholders, plural branches and markup come from the base string; the translation must carry the same set, translated.
2. **Plural categories are per language, not per string.** Russian needs `one/few/many/other`, Arabic needs `zero/one/two/few/many/other`, Japanese needs `other` alone. A translation that only has `other` is a runtime bug in most languages.
3. **A placeholder that changes name is a lost variable.** `{product}` becoming `{produit}` renders literally; it is a blocker, not a typo.
4. **Untranslated is not "done".** A string identical to the base is a warning at minimum, because it ships English to a German screen.
5. **Length is a layout budget.** Compare per string against the base, not the whole file.
6. **The gate does not write translations.** It names what is broken and where.

## Workflow

### Step 0 — Fix the frame

Ask for the base locale, the target locales, the file formats, the glossary (term plus per-locale approved rendering), and the length budget (usually 1.3–1.5× the base). Without a glossary, term drift becomes invisible.

### Step 1 — Run the gate

```bash
python scripts/i18n_gate.py --locales locales/ --base en --glossary glossary.csv --out out/
python scripts/i18n_gate.py --locales locales/ --base en --max-ratio 1.3 --pseudo out/pseudo/
```

Supported inputs: `.json` (nested or flat), `.po` (msgid/msgstr), `.xliff`/`.xlf` (trans-unit or unit). PO and XLIFF key by source string, so the gate aligns them to the base key space by value before comparing.

### Step 2 — Read the verdict per locale

- `BLOCK` — a placeholder mismatch, an ICU syntax error, a missing required plural category, a missing key, or an empty value. The build will visibly break.
- `WARN` — untranslated string, glossary drift, markup mismatch, length over budget.
- `PASS` — the locale can ship as far as strings are concerned.

The verdict is per locale on purpose: releasing `de` while holding `ar` is a normal decision and needs a per-locale answer.

### Step 3 — Work the blockers by damage

1. `ICU_SYNTAX`: unbalanced braces or a plural with no `other` throws at render time.
2. `PLACEHOLDER_MISMATCH`: variable lost or renamed; the string prints braces and the value never appears.
3. `PLURAL_CATEGORIES`: the language's required forms are absent; numbers render with the wrong case.
4. `MISSING_KEY` / `EMPTY_VALUE`: the screen falls back to the base language or shows blank.
5. `TAG_MISMATCH`, `GLOSSARY`, `UNTRANSLATED`, `LENGTH`: cosmetic, brand and layout — decide, do not ignore.

### Step 4 — Feed the vendor, not the file

The JSON gate output is the hand-off: one row per key with code and message. For a vendor, group by code; for an engineer, group by key. Never send the whole file back with "please fix" — a list of 40 named keys gets fixed, a file gets re-translated.

### Step 5 — Ship the evidence

Keep `i18n_gate.md` and `i18n_gate.json` with the release. A "localized" claim without a gate report is a hope. Use `--pseudo` to produce a pseudo-localised copy of the base (`qps.json`) for layout testing: same keys, accented text, 30% longer, which is how overflow gets caught before a language does.

## Output format

- Header: base locale, locale count, base string count, verdict, blocker and warning totals.
- Per-locale table: strings, blockers, warnings, verdict.
- Findings table: locale, severity, code, key, one sentence with the concrete problem.
- Gate rules: the eight checks, so a reader knows what was not checked.
- JSON: the same rows, grouped per locale, for tooling.

## Boundaries

- Does not translate, edit, or suggest wording; it reports the defect and the key.
- Does not check plural *forms* against CLDR selectors beyond the required category set; a `few` branch that exists but is linguistically wrong passes.
- Does not validate context, tone, formality, gender agreement, or punctuation conventions per locale.
- Does not resolve keys shared across files or runtime-composed strings (`t("error." + code)`), which no string file can see.
- Does not cover right-to-left layout, font coverage, or truncation in the actual UI; `--pseudo` is a proxy, not a screenshot test.
