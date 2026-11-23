# Plural rules, failure modes, and the honest edge of a string gate

## Plural categories the gate requires

The table is a minimum, not a full CLDR implementation: it lists which cardinal selectors a language needs at least one branch for. A translation missing one of these is a defect even if the sentence "looks fine" with `other` alone.

| Group | Languages | Required categories |
|---|---|---|
| Two-form | en, de, nl, sv, da, nb, es, it, pt, el, hu, tr, hi, fa | `one`, `other` |
| Three-form (French style) | fr | `one`, `many`, `other` |
| Slavic | ru, uk, pl, cs, sk | `one`, `few`, `many`, `other` |
| Baltic | lt | `one`, `few`, `many`, `other` |
| South Slavic | hr | `one`, `few`, `other` |
| Arabic | ar | `zero`, `one`, `two`, `few`, `many`, `other` |
| Hebrew | he | `one`, `two`, `many`, `other` |
| Single-form | ja, zh, ko, vi, th, id, ms | `other` |

Consequences that the gate reports as blockers:

- Russian with `one/other`: "5 товаров" where "5 товара" is required. The string renders; the grammar is wrong.
- Arabic with `one/other`: dual and zero forms missing; 0 and 2 read as insults.
- English with `other` only: "1 items".
- Japanese with `one/other`: harmless but redundant; the gate does not block it, because Japanese only needs `other`.

## Failure modes the gate catches, and why each is a real bug

1. **Renamed placeholder.** `{product}` → `{produit}`. The runtime prints `{produit}` literally: the user sees braces, the variable never renders. Not a typo — a lost variable.
2. **Unbalanced braces.** `{count, plural, one{# item} other{# items}` missing the closing brace. ICU throws; the whole screen fails, not just the string.
3. **Plural without `other`.** ICU requires `other` as the fallback for every plural. Without it, any count not matching another category throws.
4. **Duplicate or nested placeholder.** `{count} {count}` in the base, `{count}` in the translation: one number disappears silently, no error.
5. **Markup drift.** Base `<b>Session</b> expired`, target `<b>Сессия</b>`: the closing tag is gone, so the rest of the screen renders bold. Tag counts are compared, not tag order.
6. **Missing key.** The screen falls back to the base locale or shows the key. Silent in English-only QA, visible only in the localized build.
7. **Untranslated.** Identical to the base. Ships English to a user who chose German; usually a sign the string arrived after the batch.
8. **Glossary drift.** "Checkout" becomes "Paiement" in French but "Valider" elsewhere: the same button, two names, two support tickets.
9. **Length blowout.** German compounds and Japanese explanations run 1.3–2× the English string; the threshold is the design's budget, so it is set per project, not per language.

## What the gate cannot decide

- **Whether the plural branch is linguistically right.** It knows `few` exists, not whether the genitive is correct. That is a translator review.
- **Gender and case agreement.** Slavic and Germanic adjectives agree with nouns the gate never sees.
- **Context.** "Book" as noun and verb share a key and need two translations; the file does not distinguish them, so `--context` style disambiguation is a workflow problem, not a check.
- **Runtime-composed keys.** `t("error." + code)` never appears in a static scan.
- **Layout.** `--pseudo` approximates overflow with a 30% expansion and accents; it does not test fonts, RTL mirroring, or a 320px screen.
- **Semantic fidelity.** A fluent but wrong translation passes every check here.

## Working with a vendor

- Send the gate JSON grouped by code: `PLACEHOLDER_MISMATCH` to the engineer, `UNTRANSLATED` and `GLOSSARY` to the translator, `LENGTH` to whoever owns the layout.
- Re-run after the batch arrives; the second report is the acceptance evidence.
- For a single locale, one blocker is enough to hold the release; for ten locales, hold the affected ones and ship the rest. Say which in the release note.

## Pseudo-localisation

`--pseudo` writes `qps.json`: the base keys with accented vowels, bracketed, and padded toward 130% length. Layout, truncation, and hard-coded strings show up immediately, and no translator time is spent. It is a proxy: if the pseudo build overflows, the real German will too; if it fits, Japanese still might not.
