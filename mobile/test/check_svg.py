#!/usr/bin/env python3
"""Validates the SVGs produced by make_diagram_test.py.

A diagram that renders is not the same as a diagram that is readable. This checks the
things that actually go wrong in a hand-written layout engine: malformed XML, NaN
coordinates, boxes drawn on top of each other, text escaping off the canvas, and
labels from the source going missing entirely.

    python mobile/test/check_svg.py mobile/test/out-all
"""

import argparse
import pathlib
import re
import sys
import xml.etree.ElementTree as ET

NS = "{http://www.w3.org/2000/svg}"


def boxes(root):
    """Node boxes only: rects with a stroke. Label chips are drawn without one."""
    out = []
    for r in root.iter(NS + "rect"):
        if r.get("stroke") in (None, "none"):
            continue
        try:
            out.append((float(r.get("x", 0)), float(r.get("y", 0)),
                        float(r.get("width", 0)), float(r.get("height", 0))))
        except ValueError:
            out.append(None)
    return out


def overlap(a, b):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ix = min(ax + aw, bx + bw) - max(ax, bx)
    iy = min(ay + ah, by + bh) - max(ay, by)
    if ix <= 0.5 or iy <= 0.5:
        return 0.0
    return ix * iy


def check(path: pathlib.Path):
    problems = []
    text = path.read_text(encoding="utf-16", errors="replace")

    if "NaN" in text or "Infinity" in text or "undefined" in text:
        problems.append("NaN/undefined in output")

    try:
        root = ET.fromstring(text)
    except ET.ParseError as e:
        return ["malformed XML: %s" % e], None

    m = re.search(r'viewBox="0 0 (\d+(?:\.\d+)?) (\d+(?:\.\d+)?)"', text)
    if not m:
        problems.append("no viewBox")
        return problems, None
    vw, vh = float(m.group(1)), float(m.group(2))

    if vw < 60 or vh < 40:
        problems.append("suspiciously small: %gx%g" % (vw, vh))
    if vw > 4000 or vh > 6000:
        problems.append("runaway size: %gx%g" % (vw, vh))

    bs = boxes(root)
    if None in bs:
        problems.append("unparseable rect geometry")
        bs = [b for b in bs if b]

    # nothing should sit outside the canvas
    for b in bs:
        x, y, w, h = b
        if x < -2 or y < -2 or x + w > vw + 2 or y + h > vh + 2:
            problems.append("box outside canvas: %g,%g %gx%g (canvas %gx%g)" % (x, y, w, h, vw, vh))
            break

    # node boxes must not sit on top of each other
    worst = 0.0
    for i in range(len(bs)):
        for j in range(i + 1, len(bs)):
            area = overlap(bs[i], bs[j])
            if area > worst:
                worst = area
    if worst > 4:
        problems.append("overlapping boxes (%.0f px^2)" % worst)

    texts = [(t.text or "") for t in root.iter(NS + "text")]
    joined = " ".join(texts)
    if not joined.strip():
        problems.append("no text rendered")

    empty = sum(1 for t in texts if not t.strip())
    if empty > max(2, len(texts) * 0.25):
        problems.append("%d/%d empty text nodes" % (empty, len(texts)))

    stats = {"w": vw, "h": vh, "boxes": len(bs), "texts": len(texts)}
    return problems, stats


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    folder = pathlib.Path(args.folder)
    if not folder.is_absolute():
        folder = pathlib.Path(__file__).resolve().parent.parent.parent / folder
    files = sorted(folder.glob("*.svg"))
    if not files:
        print("no .svg files in " + str(folder), file=sys.stderr)
        return 1

    bad = 0
    for f in files:
        problems, stats = check(f)
        if problems:
            bad += 1
            print("FAIL  %-26s %s" % (f.stem, "; ".join(problems)))
        elif not args.quiet:
            print("  ok  %-26s %4gx%-5g %2d boxes %3d labels"
                  % (f.stem, stats["w"], stats["h"], stats["boxes"], stats["texts"]))

    print()
    print("%d checked, %d with problems" % (len(files), bad))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
