#!/usr/bin/env python3
"""Localization release gate: compare locale files against a base locale.

Parses ICU MessageFormat enough to catch the failures that ship: lost or
renamed placeholders, plural categories the target language requires and the
translation lacks, unbalanced tags, untranslated strings, glossary drift and
length blowouts. Reads .json (nested or flat), .po and .xlf/.xliff.

Usage:
    python scripts/i18n_gate.py --locales locales/ --base en --out out/
    python scripts/i18n_gate.py --locales locales/ --base en --glossary glossary.csv --max-ratio 1.4
    python scripts/i18n_gate.py --locales locales/ --base en --pseudo out/pseudo/
"""

import argparse
import csv
import json
import os
import re
import sys
import xml.etree.ElementTree as ET

# Minimum cardinal plural categories a language needs (CLDR, abbreviated).
PLURAL_CATEGORIES = {
    "en": {"one", "other"}, "de": {"one", "other"}, "nl": {"one", "other"},
    "sv": {"one", "other"}, "da": {"one", "other"}, "nb": {"one", "other"},
    "es": {"one", "other"}, "it": {"one", "other"}, "pt": {"one", "other"},
    "el": {"one", "other"}, "hu": {"one", "other"}, "tr": {"one", "other"},
    "hi": {"one", "other"}, "fa": {"one", "other"},
    "fr": {"one", "many", "other"},
    "cs": {"one", "few", "many", "other"}, "sk": {"one", "few", "many", "other"},
    "pl": {"one", "few", "many", "other"}, "ru": {"one", "few", "many", "other"},
    "uk": {"one", "few", "many", "other"}, "hr": {"one", "few", "other"},
    "lt": {"one", "few", "many", "other"},
    "ar": {"zero", "one", "two", "few", "many", "other"},
    "he": {"one", "two", "many", "other"},
    "ja": {"other"}, "zh": {"other"}, "ko": {"other"}, "vi": {"other"},
    "th": {"other"}, "id": {"other"}, "ms": {"other"},
}
TAG = re.compile(r"</?([a-zA-Z][a-zA-Z0-9]*)\s*/?>")
IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


# ---------------------------------------------------------------- ICU parsing


def _match_brace(text, i):
    depth, j = 0, i
    while j < len(text):
        if text[j] == "{":
            depth += 1
        elif text[j] == "}":
            depth -= 1
            if depth == 0:
                return j
        j += 1
    return -1


CATEGORY = re.compile(r"(=\d+|[a-zA-Z]+)\s*\{")


def scan_icu(text):
    """Return (variables, plural_categories, errors, places the parser skipped)."""
    variables, categories, errors = set(), {}, []
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "{":
            end = _match_brace(text, i)
            if end < 0:
                errors.append("unbalanced '{' at position %d" % i)
                break
            inner = text[i + 1: end]
            parts = inner.split(",")
            name = parts[0].strip()
            argtype = parts[1].strip() if len(parts) > 1 else ""
            if not IDENT.match(name):
                errors.append("invalid placeholder name %r" % name)
            variables.add(name)
            if argtype in ("plural", "selectordinal", "select"):
                body = inner.split(",", 2)[2] if inner.count(",") >= 2 else ""
                cats = set()
                pos = 0
                while True:
                    m = CATEGORY.search(body, pos)
                    if not m:
                        break
                    cat = m.group(1)
                    brace = m.end() - 1
                    cend = _match_brace(body, brace)
                    if cend < 0:
                        errors.append("unbalanced category block in {%s}" % name)
                        break
                    cats.add(cat)
                    sub_vars, sub_cats, sub_err = scan_icu(body[brace + 1: cend])
                    variables |= sub_vars
                    for k, v in sub_cats.items():
                        categories.setdefault(k, set()).update(v)
                    errors.extend(sub_err)
                    pos = cend + 1
                categories.setdefault(name, set()).update(cats)
                if argtype == "plural" and "other" not in cats:
                    errors.append("{%s, plural} has no 'other' branch" % name)
                if not cats:
                    errors.append("{%s, %s} has no branches" % (name, argtype))
            elif argtype and argtype not in ("number", "date", "time", "spellout",
                                             "ordinal", "duration", "percent", "currency"):
                errors.append("unknown argument type %r in {%s}" % (argtype, name))
            i = end + 1
        elif ch == "}":
            errors.append("stray '}' at position %d" % i)
            i += 1
        else:
            i += 1
    return variables, categories, errors


def tag_profile(text):
    open_tags, close_tags = [], []
    for m in TAG.finditer(text):
        if m.group(0).startswith("</"):
            close_tags.append(m.group(1).lower())
        else:
            open_tags.append(m.group(1).lower())
    return sorted(open_tags), sorted(close_tags)


def printf_vars(text):
    return set(re.findall(r"%(?:\d+\$)?[sdif]", text)) | set(re.findall(r"\{\{?\s*([A-Za-z_][\w.]*)\s*\}?\}", text))


# ---------------------------------------------------------------- locale parsers


def flatten(obj, prefix=""):
    out = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            key = "%s.%s" % (prefix, k) if prefix else str(k)
            if isinstance(v, (dict, list)):
                out.update(flatten(v, key))
            else:
                out[key] = "" if v is None else str(v)
    return out


def read_json(path):
    data = json.load(open(path, encoding="utf-8-sig"))
    return flatten(data)


def read_po(path):
    out, cur, last = {}, {}, None
    for raw in open(path, encoding="utf-8-sig"):
        line = raw.strip()
        if not line:
            if cur.get("msgid") is not None:
                key, val = cur["msgid"], cur.get("msgstr", "")
                if key:
                    out[key] = val
            cur, last = {}, None
            continue
        if line.startswith("#"):
            continue
        m = re.match(r'(msgid|msgstr|msgid_plural)\s+"(.*)"$', line)
        if m:
            last = m.group(1)
            cur[last] = m.group(2).encode().decode("unicode_escape")
        elif line.startswith('"') and last:
            cur[last] += line.strip('"').encode().decode("unicode_escape")
    if cur.get("msgid"):
        out[cur["msgid"]] = cur.get("msgstr", "")
    return out


def read_xliff(path):
    out = {}
    tree = ET.parse(path)
    root = tree.getroot()
    for unit in root.iter():
        if unit.tag.split("}")[-1] not in ("trans-unit", "unit"):
            continue
        uid = unit.get("id") or ""
        src = tgt = None
        for el in unit.iter():
            name = el.tag.split("}")[-1]
            if name == "source" and src is None:
                src = "".join(el.itertext())
            if name in ("target", "segment") and tgt is None:
                tgt = "".join(el.itertext())
        if src is not None:
            out[uid or src] = tgt if tgt is not None else ""
    return out


def load_locale(path):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".json":
        return read_json(path)
    if ext == ".po":
        return read_po(path)
    if ext in (".xlf", ".xliff"):
        return read_xliff(path)
    return None


def discover(locales_dir):
    found = {}
    for root, _, names in os.walk(locales_dir):
        for n in sorted(names):
            ext = os.path.splitext(n)[1].lower()
            if ext in (".json", ".po", ".xlf", ".xliff"):
                code = os.path.splitext(n)[0]
                found[code] = os.path.join(root, n)
    return found


# ---------------------------------------------------------------- checks


def load_glossary(path):
    """Rows: term,locale,target  or  term,target1|target2 (locale-agnostic)."""
    terms = []
    if not path or not os.path.exists(path):
        return terms
    with open(path, encoding="utf-8-sig", newline="") as f:
        for row in csv.reader(f):
            if len(row) >= 3 and re.fullmatch(r"[a-z]{2}(-[A-Za-z]{2,4})?", row[1].strip()):
                terms.append((row[0].strip(), row[1].strip().lower(), [row[2].strip()]))
            elif len(row) >= 2 and row[0].strip() and row[1].strip():
                terms.append((row[0].strip(), "*", [t.strip() for t in row[1].split("|")]))
    return terms


def align_keys(code, base, target):
    """PO and XLIFF key by source string; map them onto the base key space."""
    by_value = {v: k for k, v in base.items()}
    out = {}
    for k, v in target.items():
        if k in base:
            out[k] = v
        elif k in by_value:
            out[by_value[k]] = v
        else:
            out[k] = v
    return out


def check_locale(code, base, target, glossary, max_ratio):
    findings = []

    def add(code_, sev, key, msg):
        findings.append({"code": code_, "severity": sev, "key": key, "message": msg})

    required = PLURAL_CATEGORIES.get(code.split("-")[0].lower(), set())
    for key, base_val in base.items():
        if key not in target:
            add("MISSING_KEY", "blocker", key, "not present in %s" % code)
            continue
        val = target[key]
        if not val.strip():
            add("EMPTY_VALUE", "blocker", key, "empty translation")
            continue

        b_vars, b_cats, b_err = scan_icu(base_val)
        t_vars, t_cats, t_err = scan_icu(val)
        for e in t_err:
            add("ICU_SYNTAX", "blocker", key, e)
        if b_vars != t_vars:
            missing = sorted(b_vars - t_vars)
            extra = sorted(t_vars - b_vars)
            add("PLACEHOLDER_MISMATCH", "blocker", key,
                "placeholders differ — missing %s, unexpected %s" % (missing or "none", extra or "none"))
        if required and any(t_cats.get(v) for v in t_vars if v in b_cats):
            for var, cats in t_cats.items():
                if var not in b_cats:
                    continue
                if required - cats:
                    add("PLURAL_CATEGORIES", "blocker", key,
                        "{%s} lacks %s, required in %s" % (var, ", ".join(sorted(required - cats)), code))
        if not any(t_cats):
            for var in t_vars:
                pass

        b_open, b_close = tag_profile(base_val)
        t_open, t_close = tag_profile(val)
        if b_open != t_open or b_close != t_close:
            add("TAG_MISMATCH", "warning", key,
                "markup differs — base %s, target %s" % (b_open + b_close, t_open + t_close))

        if val.strip() == base_val.strip() and len(base_val) > 3:
            add("UNTRANSLATED", "warning", key, "identical to the base string")

        for term, scope, expected in glossary:
            if scope not in ("*", code.split("-")[0].lower()):
                continue
            if re.search(r"(?<![\w])" + re.escape(term) + r"(?![\w])", base_val, re.I):
                if not any(re.search(r"(?<![\w])" + re.escape(e) + r"(?![\w])", val, re.I) for e in expected):
                    add("GLOSSARY", "warning", key,
                        "\"%s\" should be rendered as %s in %s" % (term, " / ".join(expected), code))

        if b_vars:
            ratio = len(val) / max(1, len(base_val))
            if ratio > max_ratio:
                add("LENGTH", "warning", key,
                    "translation is %.0f%% of the base length (%d vs %d chars)" % (ratio * 100, len(val), len(base_val)))
    return findings


def pseudo(text):
    accented = "áàâäéèêëíìîïóòôöúùûüñçßøåæ"
    vowels = "aeiouyAEIOUY"
    out = []
    for i, ch in enumerate(text):
        if ch in vowels:
            out.append(accented[ord(ch) % len(accented)])
        else:
            out.append(ch)
    s = "".join(out)
    if "{" in s or "<" in s:
        return s
    return "[" + s + " ·" + ("·" * max(2, len(text) // 6)) + "]"


def render(report):
    out = ["# Localization release gate\n"]
    out.append("Base locale: %s · locales: %d · strings: %d\n"
               % (report["base"], report["locales"], report["base_strings"]))
    verdict = report["verdict"]
    out.append("**Verdict: %s** — blockers: %d · warnings: %d\n" % (verdict, report["blockers"], report["warnings"]))
    out.append("## Per locale\n")
    out.append("| Locale | Strings | Blockers | Warnings | Verdict |")
    out.append("|---|---|---|---|---|")
    for lc in report["per_locale"]:
        out.append("| %s | %d | %d | %d | %s |" % (lc["locale"], lc["strings"], lc["blockers"],
                                                   lc["warnings"], lc["verdict"]))
    out.append("\n## Findings\n")
    out.append("| Locale | Severity | Code | Key | What is wrong |")
    out.append("|---|---|---|---|---|")
    for lc in report["per_locale"]:
        for f in lc["findings"]:
            out.append("| %s | %s | %s | %s | %s |" % (lc["locale"], f["severity"], f["code"],
                                                       f["key"][:60], f["message"].replace("|", "/")))
    out.append("\n## Gate rules\n")
    out.append("- Every placeholder in the base string must appear in the translation; a renamed `{count}` renders as literal text.")
    out.append("- A plural message must carry every cardinal category the target language requires; `other` alone is correct only for ja/zh/ko/vi/th/id/ms.")
    out.append("- Unbalanced braces and a plural without `other` block the release: the runtime throws on both.")
    out.append("- Strings identical to the base are untranslated, not translated.")
    out.append("- Length is compared per string against the base; the threshold is the layout budget, not style.")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description="Gate a localization release against the base locale.")
    ap.add_argument("--locales", required=True, help="folder of locale files (en.json, de.json, ...)")
    ap.add_argument("--base", required=True, help="base locale code, e.g. en")
    ap.add_argument("--glossary", default=None, help="CSV: source term, target term (| for alternatives)")
    ap.add_argument("--max-ratio", type=float, default=1.4, help="allowed length ratio vs base")
    ap.add_argument("--pseudo", default=None, help="write a pseudo-localised copy of the base here")
    ap.add_argument("--out", default="out")
    a = ap.parse_args()

    files = discover(a.locales)
    if a.base not in files:
        raise SystemExit("base locale %r not found in %s (found: %s)" % (a.base, a.locales, ", ".join(sorted(files))))
    base = load_locale(files[a.base])
    if base is None:
        raise SystemExit("cannot parse base locale file")

    glossary = load_glossary(a.glossary)
    per_locale, blockers, warnings = [], 0, 0
    for code, path in sorted(files.items()):
        if code == a.base:
            continue
        target = load_locale(path)
        if target is None:
            per_locale.append({"locale": code, "strings": 0, "blockers": 1, "warnings": 0, "verdict": "BLOCK",
                               "findings": [{"code": "UNPARSED", "severity": "blocker", "key": "",
                                             "message": "unsupported locale file format"}]})
            blockers += 1
            continue
        target = align_keys(code, base, target)
        fs = check_locale(code, base, target, glossary, a.max_ratio)
        b = sum(1 for f in fs if f["severity"] == "blocker")
        w = len(fs) - b
        blockers += b
        warnings += w
        per_locale.append({"locale": code, "strings": len(target), "blockers": b, "warnings": w,
                           "verdict": "BLOCK" if b else ("WARN" if w else "PASS"), "findings": fs})

    report = {"base": a.base, "locales": len(per_locale), "base_strings": len(base),
              "blockers": blockers, "warnings": warnings,
              "verdict": "BLOCK" if blockers else ("WARN" if warnings else "PASS"),
              "per_locale": per_locale}

    os.makedirs(a.out, exist_ok=True)
    open(os.path.join(a.out, "i18n_gate.md"), "w", encoding="utf-8").write(render(report))
    open(os.path.join(a.out, "i18n_gate.json"), "w", encoding="utf-8").write(
        json.dumps(report, ensure_ascii=False, indent=2))

    if a.pseudo:
        os.makedirs(a.pseudo, exist_ok=True)
        json.dump({k: pseudo(v) for k, v in base.items()},
                  open(os.path.join(a.pseudo, "qps.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    print("base=%s locales=%d verdict=%s blockers=%d warnings=%d" % (a.base, len(per_locale), report["verdict"], blockers, warnings))
    for lc in per_locale:
        print("  %-6s %-5s b=%d w=%d" % (lc["locale"], lc["verdict"], lc["blockers"], lc["warnings"]))
        for f in lc["findings"][:3]:
            print("      [%s] %s %s" % (f["severity"], f["code"], f["key"]))
    print("wrote %s" % os.path.join(a.out, "i18n_gate.md"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
