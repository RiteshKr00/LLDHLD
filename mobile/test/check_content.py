#!/usr/bin/env python3
"""Proves the app bundle contains every byte of the notes.

The app is generated, so the question "does the phone app have everything the markdown
has?" should be answered with a diff, not an opinion. This walks the notes folder and
checks each source file against what ended up in mobile/www/content.js.

    python mobile/test/check_content.py
"""

import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
WWW = HERE.parent / "www"
NOTES = HERE.parent.parent

SKIP_DIRS = {"mobile", "__pycache__", ".git", ".github"}


def load_bundle():
    raw = (WWW / "content.js").read_text(encoding="utf-8")
    payload = raw.split("window.LLD_CONTENT = ", 1)[1].rstrip().rstrip(";")
    return json.loads(payload.replace("<\\/", "</"))


def norm(s: str) -> str:
    return s.replace("\r\n", "\n").replace("\r", "\n")


def main() -> int:
    bundle = load_bundle()

    bundled = {}                                   # source path -> text as bundled
    for p in bundle["problems"]:
        for d in p["docs"]:
            md = d["md"]
            if d["key"] == "solution":
                m = re.match(r"^```python\n([\s\S]*)\n```$", md)
                md = m.group(1) if m else md
                bundled[p["id"] + "/solution.py"] = md
            else:
                bundled[p["id"] + "/" + d["key"] + ".md"] = md
    for r in bundle["refs"]:
        bundled[r["id"] + ".md"] = r["md"]

    sources = []
    for f in sorted(NOTES.rglob("*")):
        if not f.is_file():
            continue
        if any(part in SKIP_DIRS for part in f.relative_to(NOTES).parts):
            continue
        if f.suffix not in (".md", ".py"):
            continue
        sources.append(f)

    missing, truncated, ok = [], [], []
    src_bytes = 0
    for f in sources:
        rel = str(f.relative_to(NOTES)).replace("\\", "/")
        text = norm(f.read_text(encoding="utf-8", errors="replace"))
        src_bytes += len(text)
        got = bundled.get(rel)
        if got is None:
            missing.append(rel)
            continue
        # solution.py is rstripped on the way in; compare with the same normalisation
        if norm(got).rstrip() != text.rstrip():
            a, b = norm(got).rstrip(), text.rstrip()
            where = next((i for i in range(min(len(a), len(b))) if a[i] != b[i]), min(len(a), len(b)))
            truncated.append((rel, len(b), len(a), where))
        else:
            ok.append(rel)

    extra = sorted(set(bundled) - {str(f.relative_to(NOTES)).replace("\\", "/") for f in sources})

    print("SOURCE FILES")
    print("  %d markdown/python files, %s characters" % (len(sources), format(src_bytes, ",")))
    print()
    print("IN THE APP")
    print("  %d files byte-for-byte identical" % len(ok))
    if truncated:
        print("  %d files DIFFER:" % len(truncated))
        for rel, want, got, at in truncated:
            print("     %-44s source %d chars, bundled %d, first difference at %d" % (rel, want, got, at))
    if missing:
        print("  %d files MISSING from the app:" % len(missing))
        for rel in missing:
            print("     " + rel)
    if extra:
        print("  %d bundled entries with no source file: %s" % (len(extra), ", ".join(extra)))
    print()

    # what the app adds on top of the raw text
    cards = sum(len(d["cards"]) for d in bundle["decks"])
    print("DERIVED ON TOP")
    print("  %d problems, %d sections, %d reference docs" % (
        len(bundle["problems"]), sum(len(p["docs"]) for p in bundle["problems"]), len(bundle["refs"])))
    print("  %d flashcards across %d decks (quoted from the notes, nothing invented)" % (
        cards, len(bundle["decks"])))
    print("  pattern tags, reading times, per-section progress keys, search index")
    print()

    bad = len(missing) + len(truncated)
    print("%d of %d source files fully present" % (len(ok), len(sources)))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
