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

def apply_corrections(text, exact_rules, context_rules, fuzzy_rules, stats=False):
    corrections_made = []

    # Phase 1: Exact replacements
    for rule in exact_rules:
        old = rule["from"]
        new = rule["to"]
        case_sensitive = rule.get("caseSensitive", False)
        flags = 0 if case_sensitive else re.IGNORECASE
        count = len(re.findall(re.escape(old), text, flags)) if stats else 0
        text = re.sub(re.escape(old), new, text, flags=flags)
        if count > 0:
            corrections_made.append(f"  {old} → {new} (x{count})")

    # Phase 2: Context-based replacements
    for rule in context_rules:
        old = rule["from"]
        new = rule["to"]
        before = rule.get("contextBefore", "")
        after = rule.get("contextAfter", "")
        pattern = old
        if before:
            pattern = before + pattern
        if after:
            pattern = pattern + after
        # Simple context-aware replace
        repl = new
        if before:
            repl = before + repl
        if after:
            repl = repl + after
        count = 0
        if old in text:
            text = text.replace(old, new)
            count = 1
        if count > 0:
            corrections_made.append(f"  {old} → {new} [context: {before}...{after}]")

    # Phase 3: Fuzzy regex patterns
    for rule in fuzzy_rules:
        pattern = rule.get("from_pattern", "")
        replacement = rule.get("to", "")
        if pattern:
            count = len(re.findall(pattern, text)) if stats else 0
            text = re.sub(pattern, replacement, text)
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
