#!/usr/bin/env python3
"""
Video2Doc — Transcription Correction Applier
Applies corrections.json rules to fix common ASR errors.

Usage:
  python3 apply_corrections.py < input.txt > corrected.txt
  python3 apply_corrections.py --domain auto < input.txt > corrected.txt
  python3 apply_corrections.py --json transcript.json > corrected.json
"""

import sys, json, re, argparse
from pathlib import Path

RULES_PATH = Path(__file__).parent.parent / "references" / "corrections.json"

def load_rules(domain=None):
    with open(RULES_PATH) as f:
        data = json.load(f)
    rules = data.get("rules", {})
    all_exact = list(rules.get("exact", []))
    all_context = list(rules.get("context", []))
    all_fuzzy = list(rules.get("fuzzy", []))

    if domain and domain in data.get("domains", {}):
        d = data["domains"][domain]
        all_exact.extend(d.get("exact", []))
        all_context.extend(d.get("context", []))
        all_fuzzy.extend(d.get("fuzzy", []))

    return all_exact, all_context, all_fuzzy


def _python_replacement(replacement):
    r"""Convert JSON/JavaScript-style $1 groups to Python's \g<1> syntax."""
    return re.sub(r"\$(\d+)", lambda m: rf"\g<{m.group(1)}>", replacement)


def _apply_context_rule(text, rule):
    """Apply one rule only when its configured before/after context matches."""
    old = rule["from"]
    new = rule["to"]
    before = rule.get("contextBefore", rule.get("contextBeforeRule", ""))
    after = rule.get("contextAfter", rule.get("contextAfterRule", ""))
    flags = 0 if rule.get("caseSensitive", False) else re.IGNORECASE

    pieces = []
    if before:
        pieces.append(f"(?P<_before>{before})")
    pieces.append(f"(?P<_target>{re.escape(old)})")
    if after:
        pieces.append(f"(?=(?:{after}))")
    pattern = "".join(pieces)

    def replace(match):
        prefix = match.groupdict().get("_before", "") or ""
        return prefix + new

    return re.subn(pattern, replace, text, flags=flags)

def apply_corrections(text, exact_rules, context_rules, fuzzy_rules, stats=False):
    corrections_made = []

    # Phase 1: Exact replacements
    for rule in exact_rules:
        old = rule["from"]
        new = rule["to"]
        if rule.get("contextBeforeRule") or rule.get("contextAfterRule"):
            text, count = _apply_context_rule(text, rule)
        else:
            case_sensitive = rule.get("caseSensitive", False)
            flags = 0 if case_sensitive else re.IGNORECASE
            text, count = re.subn(re.escape(old), lambda _m: new, text, flags=flags)
        if count > 0:
            corrections_made.append(f"  {old} → {new} (x{count})")

    # Phase 2: Context-based replacements
    for rule in context_rules:
        old = rule["from"]
        new = rule["to"]
        before = rule.get("contextBefore", rule.get("contextBeforeRule", ""))
        after = rule.get("contextAfter", rule.get("contextAfterRule", ""))
        text, count = _apply_context_rule(text, rule)
        if count > 0:
            corrections_made.append(
                f"  {old} → {new} [context: {before}...{after}] (x{count})")

    # Phase 3: Fuzzy regex patterns
    for rule in fuzzy_rules:
        pattern = rule.get("from_pattern", "")
        replacement = rule.get("to", "")
        if pattern:
            text, count = re.subn(pattern, _python_replacement(replacement), text)
            if count > 0:
                corrections_made.append(f"  regex:{pattern} → {replacement} (x{count})")

    if stats and corrections_made:
        print(f"[Corrections: {len(corrections_made)} rules applied]", file=sys.stderr)
        for c in corrections_made:
            print(c, file=sys.stderr)

    return text

def main():
    parser = argparse.ArgumentParser(description="Apply transcription corrections")
    parser.add_argument("--domain", help="Domain-specific rules to apply (auto, tech)")
    parser.add_argument("--json", action="store_true", help="Input is JSON (corrects text field)")
    parser.add_argument("--stats", action="store_true", help="Show correction statistics on stderr")
    parser.add_argument("--dry-run", action="store_true", help="Show corrections without modifying text")
    args = parser.parse_args()

    exact, context, fuzzy = load_rules(args.domain)

    if args.json:
        data = json.load(sys.stdin)
        if "text" in data:
            original = data["text"]
            data["text"] = apply_corrections(original, exact, context, fuzzy, args.stats)
            if "segments" in data:
                for seg in data["segments"]:
                    seg["text"] = apply_corrections(seg.get("text", ""), exact, context, fuzzy)
        if args.dry_run:
            print(json.dumps({"original": original, "corrected": data["text"]}, ensure_ascii=False, indent=2))
        else:
            print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        text = sys.stdin.read()
        corrected = apply_corrections(text, exact, context, fuzzy, args.stats)
        print(corrected, end="")

if __name__ == "__main__":
    main()
