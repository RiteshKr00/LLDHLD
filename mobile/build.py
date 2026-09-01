#!/usr/bin/env python3
"""
build.py - turns the LLD Interview Prep markdown folder into the phone app's content bundle.

Run it after adding or editing any problem or reference doc:

    python mobile/build.py

Outputs:
    mobile/www/content.js                 the app's content bundle (all markdown, embedded)
    mobile/www/icons/*.png                app icons (generated once, if missing)
    mobile/dist/LLD-Prep-single.html      with --single: one self-contained file
    mobile/android/.../assets/www/        with --android: copies www into the APK project
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import struct
import sys
import zlib
from datetime import datetime, timezone
from pathlib import Path

import mockparse

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent                      # the "LLD Interview Prep" folder
WWW = HERE / "www"
DIST = HERE / "dist"
ANDROID_ASSETS = HERE / "android" / "app" / "src" / "main" / "assets" / "www"
INTERVIEW = ROOT / "interview-mode"      # mock-interview sources

PROBLEM_DIR = re.compile(r"^(\d{2})-(.+)$")

# the diagram renderer, in load order (must match www/index.html)
DIAGRAM_PARTS = ["core.js", "class.js", "flow.js", "state.js", "sequence.js"]

# doc key -> (filename, label). Any other .md in a problem folder is picked up generically.
DOC_SPEC = [
    ("problem",   "problem.md",   "Problem"),
    ("solution",  "solution.py",  "Solution"),
    ("explained", "explained.md", "Explained"),
    ("hld",       "hld.md",       "HLD"),
    ("diagrams",  "diagrams.md",  "Diagrams"),
]

# Repo meta, not study material - these are about building/planning the track itself,
# so they would just be noise in a revision app.
REF_EXCLUDE = {"BUILD-PROMPT-study-app.md", "NEXT-SESSION.md",
               "AUDIT-findings-cards-mocks.md"}

# Reference docs: filename -> (group, label). This order is the order in the app.
REF_SPEC = [
    ("README.md",              "Start here", "How this track works"),
    ("LLD-HLD-process.md",     "Start here", "LLD & HLD process"),
    ("LLD-entity-playbook.md", "LLD",        "Entity-finding playbook"),
    ("LLD-patterns.md",        "LLD",        "Patterns & principles"),
    ("LLD-pain-to-pattern.md", "LLD",        "Naive code to pattern"),
    ("python-classes-cheatsheet.md", "LLD",  "Plain class vs dataclass vs frozen"),
    ("HLD-revision.md",        "HLD",        "HLD revision flow"),
    ("HLD-method-bank.md",     "HLD",        "HLD method bank"),
    ("HLD-reference.md",       "HLD",        "HLD deep reference"),
]

PATTERN_NAMES = [
    "Strategy", "Repository", "Factory", "Observer", "Command", "Memento", "State",
    "Singleton", "Builder", "Adapter", "Decorator", "Composite", "Template Method",
    "Dependency Injection", "Chain of Responsibility", "Iterator", "Visitor",
    "Flyweight", "Proxy", "Facade",
]


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n")


def words_of(md: str) -> int:
    return len(re.findall(r"[\w'-]+", md))


def reading_mins(md: str) -> int:
    return max(1, round(words_of(md) / 190))


def first_h1(md: str):
    m = re.search(r"^#\s+(.+)$", md, re.M)
    return m.group(1).strip() if m else None


def clean_title(raw: str, slug: str) -> str:
    """'Problem 2: Parking Lot (LLD)' -> 'Parking Lot'"""
    t = re.sub(r"^Problem\s*\d+\s*[:\-\u2014]\s*", "", raw).strip()
    t = re.sub(r"\s*\((LLD|HLD)\)\s*", " ", t).strip()
    t = re.sub(r"\s*[\u2014-]\s*(LLD|HLD)\b", "", t).strip()
    # drop a trailing subtitle: "Food Delivery - the capstone" -> "Food Delivery"
    t = re.sub(r"\s*[\u2014\u2013]\s*[a-z].*$", "", t).strip()
    return t or slug.replace("-", " ").title()


def detect_patterns(text: str):
    """Which patterns does this problem actually teach? Weighted, so a passing mention
    of the word 'state' doesn't earn a tag."""
    found = []
    for name in PATTERN_NAMES:
        esc = re.escape(name)
        score = 0
        score += 5 * len(re.findall(r"\[" + esc + r"\]", text))                        # [Strategy] marker
        score += 3 * len(re.findall(r"\b" + esc + r"\s+pattern\b", text, re.I))        # "Strategy pattern"
        score += 3 * len(re.findall(r"^#{2,4}\s.*\b" + esc + r"\b", text, re.M))       # a heading about it
        score += 2 * len(re.findall(r"\b" + esc + r"\b(?=[A-Z])", text))               # SpotAssignmentStrategy
        score += len(re.findall(r"\b" + esc + r"\b", text))
        if score >= 5:
            found.append((score, name))
    found.sort(key=lambda pair: -pair[0])
    return [n for _, n in found[:4]]


def split_sections(md: str, level: int):
    """Split markdown into (heading, body) pairs at the given heading level.
    Headings inside fenced code blocks are ignored."""
    fences = []
    for m in re.finditer(r"^```.*?^```", md, re.M | re.S):
        fences.append((m.start(), m.end()))

    def in_fence(pos):
        return any(a <= pos < b for a, b in fences)

    pat = re.compile("^" + "#" * level + r"\s+(.+)$", re.M)
    marks = [m for m in pat.finditer(md) if not in_fence(m.start())]
    out = []
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(md)
        out.append((m.group(1).strip(), md[m.end():end].strip()))
    return out


def strip_marks(s: str) -> str:
    s = re.sub(r"`([^`]*)`", r"\1", s)
    s = re.sub(r"\*\*([^*]*)\*\*", r"\1", s)
    s = re.sub(r"[\u2705\u26a0\ufe0f\U0001F512\U0001F3AF]", "", s)
    return s.strip()


def card_id(*parts: str) -> str:
    return hashlib.md5("::".join(parts).encode("utf-8")).hexdigest()[:12]


def prompt_of(problem_md: str) -> str:
    m = re.search(r"^>\s*[\"\u201c](.+?)[\"\u201d]", problem_md, re.M | re.S)
    return re.sub(r"\s+", " ", m.group(1)).strip() if m else ""


# ---------------------------------------------------------------------------
# flashcards - a cloze over your own notes, nothing invented
# ---------------------------------------------------------------------------

def build_decks(problems, refs):
    decks = []
    ref_md = {r["id"]: r["md"] for r in refs}

    def add(deck_id, title, subtitle, cards):
        cards = [c for c in cards if len(c["back"].strip()) > 40]
        if cards:
            decks.append({"id": deck_id, "title": title, "subtitle": subtitle, "cards": cards})

    # 1. Pain -> pattern. Show the naive code, ask what hurts. The highest-value card here.
    md = ref_md.get("LLD-pain-to-pattern")
    if md:
        cards = []
        for heading, body in split_sections(md, 2):
            subs = dict(split_sections(body, 3))
            naive = subs.get("What everyone writes first", "")
            tells = subs.get("What it's telling you", "")
            symptoms = subs.get("Run it in your head", "")
            if naive and tells:
                name = strip_marks(re.sub(r"^\d+\.\s*", "", heading))
                back = "**What it's telling you**\n\n" + tells
                if symptoms:
                    back += "\n\n---\n\n**Run it in your head**\n\n" + symptoms
                cards.append({
                    "id": card_id("pain", heading),
                    "tag": name,
                    "front": ("**" + name + "** - someone writes this first.\n\n"
                              "What breaks, and which pattern is it asking for?\n\n" + naive),
                    "back": back,
                })
        add("pain", "Naive code to pattern", "Read the code, name the pain", cards)

    # 2. Pattern glossary. Name on the front, definition on the back.
    md = ref_md.get("LLD-patterns")
    if md:
        cards = []
        for h2, body2 in split_sections(md, 2):
            subs = split_sections(body2, 3)
            for h3, body3 in subs:
                name = strip_marks(h3)
                if name.startswith("(add"):
                    continue
                cards.append({
                    "id": card_id("pat", h2, h3),
                    "tag": strip_marks(h2),
                    "front": "**" + name + "**\n\nWhat is it, when does it earn its place, and what is the tell?",
                    "back": body3,
                })
            if not subs and len(body2) > 60:
                cards.append({
                    "id": card_id("pat2", h2),
                    "tag": "Principles",
                    "front": "**" + strip_marks(h2) + "**\n\nRecall this section.",
                    "back": body2,
                })
        add("patterns", "Patterns & principles", "Glossary recall", cards)

    # 3. HLD method bank - one card per phase.
    md = ref_md.get("HLD-method-bank")
    if md:
        cards = [{
            "id": card_id("hld", h2),
            "tag": "HLD",
            "front": "**" + strip_marks(h2) + "**\n\nWhat is the menu here - the options, and when do you pick each?",
            "back": body,
        } for h2, body in split_sections(md, 2)]
        add("hldbank", "HLD method bank", "The menu, phase by phase", cards)

    # 4. Entity playbook.
    md = ref_md.get("LLD-entity-playbook")
    if md:
        cards = [{
            "id": card_id("ent", h2),
            "tag": "Entities",
            "front": "**" + strip_marks(h2) + "**\n\nRecall this.",
            "back": body,
        } for h2, body in split_sections(md, 2)]
        add("entities", "Entity-finding playbook", "Nouns to classes", cards)

    # 5. Per problem: clarifying questions, then locked scope and entities.
    q_cards, scope_cards = [], []
    for p in problems:
        pm = next((d["md"] for d in p["docs"] if d["key"] == "problem"), "")
        if not pm:
            continue
        for name, body in split_sections(pm, 2):
            n = strip_marks(name)
            low = n.lower()
            if low.startswith("clarifying questions"):
                ask = p["prompt"] or "Design it."
                q_cards.append({
                    "id": card_id("q", p["id"]),
                    "tag": p["title"],
                    "front": ("**" + p["title"] + "**\n\n> \"" + ask + "\"\n\n"
                              "What do you ask before writing a line of code?"),
                    "back": body,
                })
            elif low.startswith("step 2") or low.startswith("clarifications"):
                scope_cards.append({
                    "id": card_id("s", p["id"], n),
                    "tag": p["title"],
                    "front": "**" + p["title"] + " - " + n + "**\n\nRecall it.",
                    "back": body,
                })
    add("clarify", "Clarifying questions", "Step 1 reps, per problem", q_cards)
    add("scope", "Scope & entities", "What you locked, per problem", scope_cards)

    return decks


def scan_mocks():
    """interview-mode/hld/*.md -> structured mock problems (see mockparse)."""
    d = INTERVIEW / "hld"
    if not d.is_dir():
        return []
    out = []
    # the LLD folders drive mocks too - same shape, different source layout
    for p in sorted(x for x in ROOT.iterdir() if x.is_dir() and PROBLEM_DIR.match(x.name)):
        f = p / "problem.md"
        if not f.exists():
            continue
        md = read(f)
        m = mockparse.parse_lld(md, p.name)
        if not m["steps"]:
            continue
        m["title"] = clean_title(first_h1(md) or "", p.name)
        m["mins"] = reading_mins(md)
        out.append(m)

    for f in sorted(d.glob("*.md")):
        md = read(f)
        m = mockparse.parse(md, f.stem)
        # the h1 is "HLD-01 - News Feed (Twitter)"; the app already shows the number
        t = clean_title(first_h1(md) or "", f.stem)
        m["title"] = re.sub(r"^HLD-\d+\s*[—\-]\s*", "", t).strip()
        m["md"] = md
        m["mins"] = reading_mins(md)
        out.append(m)
    return out


# ---------------------------------------------------------------------------
# scan
# ---------------------------------------------------------------------------

def scan():
    problems = []
    for d in sorted(p for p in ROOT.iterdir() if p.is_dir()):
        m = PROBLEM_DIR.match(d.name)
        if not m:
            continue
        num, slug = int(m.group(1)), m.group(2)
        docs, seen = [], set()
        for key, fname, label in DOC_SPEC:
            f = d / fname
            if not f.exists():
                continue
            seen.add(fname)
            body = read(f)
            md = "```python\n" + body.rstrip() + "\n```" if f.suffix == ".py" else body
            docs.append({"key": key, "label": label, "md": md, "mins": reading_mins(body)})
        for f in sorted(d.glob("*.md")):
            if f.name in seen:
                continue
            body = read(f)
            docs.append({"key": f.stem, "label": f.stem.replace("-", " ").title(),
                         "md": body, "mins": reading_mins(body)})
        if not docs:
            continue
        pm = next((x["md"] for x in docs if x["key"] == "problem"), "")
        blob = "\n".join(x["md"] for x in docs)
        problems.append({
            "id": d.name,
            "num": num,
            "slug": slug,
            "title": clean_title(first_h1(pm) or "", slug),
            "prompt": prompt_of(pm),
            "tags": detect_patterns(blob),
            "mins": sum(x["mins"] for x in docs),
            "docs": docs,
        })
    problems.sort(key=lambda p: p["num"])

    refs = []
    for fname, group, label in REF_SPEC:
        f = ROOT / fname
        if not f.exists():
            continue
        body = read(f)
        refs.append({"id": f.stem, "group": group, "title": label,
                     "heading": first_h1(body) or label, "md": body,
                     "mins": reading_mins(body)})
    known = {f for f, _, _ in REF_SPEC} | REF_EXCLUDE
    for f in sorted(ROOT.glob("*.md")):
        if f.name in known:
            continue
        body = read(f)
        refs.append({"id": f.stem, "group": "More", "title": f.stem.replace("-", " "),
                     "heading": first_h1(body) or f.stem, "md": body,
                     "mins": reading_mins(body)})

    # interview-mode top-level docs (HLD-BASICS is the beginner on-ramp)
    for fname, label in (("HLD-BASICS.md", "HLD basics"),
                         ("INDEX.md", "Mock index"),
                         ("FORMAT.md", "Mock file format")):
        f = INTERVIEW / fname
        if not f.exists():
            continue
        body = read(f)
        refs.append({"id": f.stem, "group": "HLD", "title": label,
                     "heading": first_h1(body) or label, "md": body,
                     "mins": reading_mins(body)})

    mocks = scan_mocks()

    # every HLD round is readable as well as runnable, so ship its markdown
    # as a reference too - that is what 'read it instead' opens
    for m in mocks:
        if m["track"] != "HLD":
            continue
        refs.append({"id": m["id"], "group": "HLD rounds", "title": m["title"],
                     "heading": m["title"], "md": m["md"], "mins": m["mins"]})

    payload = {
        "built": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "problems": problems,
        "refs": refs,
        "mocks": mocks,
        "decks": build_decks(problems, refs),
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    payload["version"] = hashlib.md5(raw.encode("utf-8")).hexdigest()[:10]
    return payload


# ---------------------------------------------------------------------------
# icons - a tiny PNG writer, so no image library is needed
# ---------------------------------------------------------------------------

def png_bytes(width, height, pixels):
    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))
    raw = b"".join(b"\x00" + pixels[y * width * 4:(y + 1) * width * 4] for y in range(height))
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9))
            + chunk(b"IEND", b""))


def in_round_rect(x, y, rx, ry, w, h, r):
    if not (rx <= x <= rx + w and ry <= y <= ry + h):
        return False
    if r <= 0:
        return True
    ax = min(max(x, rx + r), rx + w - r)
    ay = min(max(y, ry + r), ry + h - r)
    return (x - ax) ** 2 + (y - ay) ** 2 <= r * r


def draw_icon(size, maskable=False, mode="square"):
    """A UML-ish glyph: one class box branching into two, drawn pixel by pixel.

    mode "square"    rounded-square app icon
    mode "maskable"  full-bleed, extra padding, for maskable/adaptive backgrounds
    mode "fg"        glyph only on transparent, for an Android adaptive foreground
    """
    if maskable:
        mode = "maskable"
    bg = (13, 17, 27)
    accent = (110, 168, 254)
    accent2 = (167, 139, 250)
    ink = (226, 232, 245)

    pad = size * {"square": 0.11, "maskable": 0.22, "fg": 0.28}[mode]
    inner = size - 2 * pad
    outer_r = 0 if mode != "square" else size * 0.22
    line_w = max(2.0, size * 0.028)

    boxes = [
        (0.28, 0.06, 0.44, 0.22, accent),
        (0.02, 0.62, 0.40, 0.22, accent2),
        (0.58, 0.62, 0.40, 0.22, accent2),
    ]
    tx = pad + inner * 0.50
    ty = pad + inner * 0.28
    my = pad + inner * 0.45
    lx = pad + inner * 0.22
    rx2 = pad + inner * 0.78
    by = pad + inner * 0.62

    px = bytearray()
    for y in range(size):
        fy = y + 0.5
        for x in range(size):
            fx = x + 0.5
            if not in_round_rect(fx, fy, 0, 0, size, size, outer_r):
                px += b"\x00\x00\x00\x00"
                continue
            lift = int(12 * ((fx + fy) / (2 * size)))
            r, g, b = bg[0] + lift, bg[1] + lift, bg[2] + lift + 5
            alpha = 0 if mode == "fg" else 255      # the foreground layer keeps only the glyph

            on_line = (
                (abs(fx - tx) <= line_w / 2 and ty <= fy <= my)
                or (abs(fy - my) <= line_w / 2 and lx <= fx <= rx2)
                or (abs(fx - lx) <= line_w / 2 and my <= fy <= by)
                or (abs(fx - rx2) <= line_w / 2 and my <= fy <= by)
            )
            if on_line:
                r, g, b = ink
                alpha = 255

            for bx, byy, bw, bh, col in boxes:
                X, Y = pad + inner * bx, pad + inner * byy
                W, H = inner * bw, inner * bh
                if in_round_rect(fx, fy, X, Y, W, H, min(W, H) * 0.26):
                    if fy < Y + H * 0.40:
                        r, g, b = min(255, col[0] + 45), min(255, col[1] + 45), min(255, col[2] + 45)
                    else:
                        r, g, b = col
                    alpha = 255

            px += bytes((min(r, 255), min(g, 255), min(b, 255), alpha))
    return png_bytes(size, size, bytes(px))


def write_icons(force=False):
    (WWW / "icons").mkdir(parents=True, exist_ok=True)
    for name, size, mode in [("icon-192.png", 192, "square"),
                             ("icon-512.png", 512, "square"),
                             ("icon-maskable-512.png", 512, "maskable")]:
        out = WWW / "icons" / name
        if out.exists() and not force:
            continue
        out.write_bytes(draw_icon(size, mode=mode))
        print("  icon  " + str(out.relative_to(HERE)))


# Android launcher icons: legacy square PNGs plus an adaptive foreground layer.
MIPMAPS = [("mdpi", 48), ("hdpi", 72), ("xhdpi", 96), ("xxhdpi", 144), ("xxxhdpi", 192)]


def write_mipmaps(force=False):
    res = HERE / "android" / "app" / "src" / "main" / "res"
    made = 0
    for density, size in MIPMAPS:
        folder = res / ("mipmap-" + density)
        folder.mkdir(parents=True, exist_ok=True)
        for name, mode in [("ic_launcher.png", "square"),
                           ("ic_launcher_round.png", "maskable"),
                           ("ic_launcher_foreground.png", "fg")]:
            out = folder / name
            if out.exists() and not force:
                continue
            scale = 2 if name == "ic_launcher_foreground.png" else 1   # adaptive layers are 108dp
            out.write_bytes(draw_icon(size * scale, mode=mode))
            made += 1
    if made:
        print("  icons  {} android launcher files".format(made))


# ---------------------------------------------------------------------------
# emit
# ---------------------------------------------------------------------------

def write_content(payload):
    js = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    js = js.replace("</", "<\\/")            # never break out of the <script> tag
    js = js.replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    WWW.mkdir(parents=True, exist_ok=True)
    (WWW / "content.js").write_text(
        "/* generated by mobile/build.py - do not edit by hand */\n"
        "window.LLD_CONTENT = " + js + ";\n", encoding="utf-8")


def write_single_file(payload):
    """One self-contained .html - everything inlined, including mermaid."""
    DIST.mkdir(parents=True, exist_ok=True)
    html = read(WWW / "index.html")
    css = read(WWW / "styles.css")
    app = read(WWW / "app.js")
    content = read(WWW / "content.js")

    html = html.replace('<link rel="stylesheet" href="styles.css">', "<style>\n" + css + "\n</style>")
    html = re.sub(r'\s*<link rel="manifest"[^>]*>', "", html)
    html = re.sub(r'\s*<link rel="apple-touch-icon"[^>]*>', "", html)
    html = re.sub(r'\s*<link rel="icon"[^>]*>', "", html)
    html = html.replace('<script src="content.js"></script>', "<script>\n" + content + "\n</script>")
    for name in DIAGRAM_PARTS:
        tag = '<script src="diagram/' + name + '"></script>'
        part = WWW / "diagram" / name
        html = html.replace(tag, "<script>\n" + read(part) + "\n</script>" if part.exists() else "")
    html = html.replace(
        '<script src="app.js"></script>',
        "<script>window.LLD_SINGLE_FILE = true;</script>\n"
        "<script>\n" + app + "\n</script>")
    out = DIST / "LLD-Prep-single.html"
    out.write_text(html, encoding="utf-8")
    return out


def copy_to_android(force_icons=False):
    if ANDROID_ASSETS.exists():
        shutil.rmtree(ANDROID_ASSETS)
    ANDROID_ASSETS.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(WWW, ANDROID_ASSETS, ignore=shutil.ignore_patterns("*.map"))
    write_mipmaps(force=force_icons)
    return ANDROID_ASSETS


def asset_fingerprint(content_version):
    """Hash the notes AND the app's own files.

    The service worker is cache-first, so this string is the only thing that tells an
    already-installed app that anything changed. Stamping it from the notes alone meant
    editing app.js or styles.css shipped nothing: the phone kept serving the old copy.
    """
    h = hashlib.md5(content_version.encode("utf-8"))
    shell = ["index.html", "styles.css", "app.js", "manifest.webmanifest"]
    shell += ["diagram/" + n for n in DIAGRAM_PARTS]
    for rel in shell:
        f = WWW / rel
        if f.exists():
            h.update(rel.encode("utf-8"))
            h.update(f.read_bytes())
    return h.hexdigest()[:10]


def stamp_service_worker(version):
    sw = WWW / "sw.js"
    if not sw.exists():
        return version
    stamp = asset_fingerprint(version)
    text = read(sw)
    new = re.sub(r"const CACHE = '[^']*';", "const CACHE = 'lld-" + stamp + "';", text)
    if new != text:
        sw.write_text(new, encoding="utf-8")
    return stamp


def main():
    ap = argparse.ArgumentParser(description="Build the LLD Prep phone app content bundle.")
    ap.add_argument("--single", action="store_true", help="also emit dist/LLD-Prep-single.html")
    ap.add_argument("--android", action="store_true", help="also copy www/ into the Android project")
    ap.add_argument("--icons", action="store_true", help="regenerate the app icons")
    args = ap.parse_args()

    if not ROOT.joinpath("README.md").exists():
        print("! expected the LLD Interview Prep folder at " + str(ROOT), file=sys.stderr)
        return 1

    payload = scan()
    write_content(payload)
    stamp = stamp_service_worker(payload["version"])
    write_icons(force=args.icons)

    cards = sum(len(d["cards"]) for d in payload["decks"])
    docs = sum(len(p["docs"]) for p in payload["problems"])
    size = (WWW / "content.js").stat().st_size / 1024
    print("built  {} problems ({} docs) - {} references - {} cards in {} decks".format(
        len(payload["problems"]), docs, len(payload["refs"]), cards, len(payload["decks"])))
    print("       content.js {:.0f} KB - notes {} - cache {}".format(
        size, payload["version"], stamp))
    for p in payload["problems"]:
        print("       {:>2}. {:<26} {:>3} min   {}".format(
            p["num"], p["title"], p["mins"], ", ".join(p["tags"]) or "-"))
    for d in payload["decks"]:
        print("       deck {:<24} {:>3} cards".format(d["title"], len(d["cards"])))

    if args.single:
        out = write_single_file(payload)
        print("       single file -> {} ({:.1f} MB)".format(
            out.relative_to(HERE), out.stat().st_size / 1024 / 1024))
    if args.android:
        out = copy_to_android(force_icons=args.icons)
        print("       android assets -> " + str(out.relative_to(HERE)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
