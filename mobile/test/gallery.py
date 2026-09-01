#!/usr/bin/env python3
"""Renders the generated diagram SVGs into one image, so they can actually be looked at.

check_svg.py proves the geometry is not broken. This proves it is readable.

    python mobile/test/make_diagram_test.py --type all --out out-all
    cscript //Nologo //E:JScript mobile/test/_diag-all.js
    python mobile/test/gallery.py --in out-all
"""

import argparse
import pathlib
import shutil
import subprocess
import sys
import tempfile
import urllib.parse

HERE = pathlib.Path(__file__).resolve().parent
WWW = HERE.parent / "www"

EDGE_CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
]


def find_browser():
    for c in EDGE_CANDIDATES:
        if pathlib.Path(c).exists():
            return c
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="src", default="out-all")
    ap.add_argument("--theme", default="dark", choices=["dark", "light"])
    ap.add_argument("--width", type=int, default=900)
    ap.add_argument("--only", default=None, help="substring filter on the diagram name")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    src = HERE / args.src
    files = sorted(src.glob("*.svg"))
    if args.only:
        files = [f for f in files if args.only in f.stem]
    if not files:
        print("no svg files in " + str(src), file=sys.stderr)
        return 1

    css_url = "file:///" + urllib.parse.quote(str(WWW / "styles.css").replace("\\", "/"))
    parts = [
        "<!DOCTYPE html><html data-theme='%s'><head><meta charset='utf-8'>" % args.theme,
        "<link rel='stylesheet' href='%s'>" % css_url,
        "<style>",
        "body{margin:0;padding:16px;background:var(--bg);font-family:-apple-system,Segoe UI,Roboto,sans-serif;}",
        ".d{margin:0 0 18px;border:1px solid var(--line);border-radius:12px;background:var(--surface);overflow:hidden;}",
        ".d h3{margin:0;padding:8px 12px;font-size:12px;font-weight:600;color:var(--dim);"
        "border-bottom:1px solid var(--line);background:var(--surface-2);}",
        ".d .b{padding:10px;overflow-x:auto;}",
        ".d svg{display:block;}",
        "</style></head><body>",
    ]
    for f in files:
        svg = f.read_text(encoding="utf-16", errors="replace")
        parts.append("<div class='d'><h3>%s</h3><div class='b'>%s</div></div>" % (f.stem, svg))
    parts.append("</body></html>")

    html = HERE / ("_gallery-%s.html" % args.theme)
    html.write_text("\n".join(parts), encoding="utf-8")

    browser = find_browser()
    if not browser:
        print("wrote " + str(html) + " (no browser found to screenshot it)")
        return 0

    # must be absolute: the browser resolves it against its own working directory
    out_png = (pathlib.Path(args.out).resolve() if args.out
               else (HERE / "shots" / ("gallery-%s.png" % args.theme)))
    out_png.parent.mkdir(parents=True, exist_ok=True)
    if out_png.exists():
        out_png.unlink()

    # tall window so the whole sheet lands in one capture
    height = 400 + sum(1 for _ in files) * 430
    height = min(height, 15000)
    profile = pathlib.Path(tempfile.gettempdir()) / "lld-edge-gallery"
    cmd = [
        browser, "--headless=new", "--disable-gpu", "--no-sandbox", "--hide-scrollbars",
        "--allow-file-access-from-files", "--force-device-scale-factor=1",
        "--user-data-dir=" + str(profile),
        "--window-size=%d,%d" % (args.width, height),
        "--virtual-time-budget=5000",
        "--screenshot=" + str(out_png),
        "file:///" + urllib.parse.quote(str(html).replace("\\", "/")),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    shutil.rmtree(profile, ignore_errors=True)
    if not out_png.exists():
        sys.stderr.write(res.stderr[-1200:] + "\n")
        return 1
    print("%d diagrams -> %s (%.0f KB)" % (len(files), out_png, out_png.stat().st_size / 1024))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
