#!/usr/bin/env python3
"""Screenshot the app at a real phone size, headlessly.

Edge headless clamps its window to roughly 500px wide, so a plain --window-size cannot
reproduce a 390px phone viewport. This renders the app inside an iframe of exactly the
size we want, and screenshots that - which also makes the shots repeatable.

    python mobile/test/shoot.py                                  # home, phone size
    python mobile/test/shoot.py --route "#/p/01-url-shortener/diagrams" --tall
    python mobile/test/shoot.py --route "#/revise" --width 390 --height 844
    python mobile/test/shoot.py --all                            # a set of key screens
"""

import argparse
import os
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
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]

SHOTS = [
    ("home", "#/", False),
    ("problem", "#/p/02-parking-lot/problem", False),
    ("diagrams", "#/p/01-url-shortener/diagrams", True),
    ("solution", "#/p/08-lru-cache/solution", False),
    ("concepts", "#/concepts", False),
    ("revise", "#/revise", False),
    ("card", "#/revise/pain", True),
    ("search", "#/search", False),
]


def find_browser():
    for c in EDGE_CANDIDATES:
        if pathlib.Path(c).exists():
            return c
    return None


def file_url(p: pathlib.Path) -> str:
    return "file:///" + urllib.parse.quote(str(p).replace("\\", "/"))


def shoot(browser, route, out_png, width, height, profile):
    """Render www/index.html#route inside a width x height iframe and capture it."""
    target = file_url(WWW / "index.html") + route
    wrapper = (
        "<!DOCTYPE html><html><head><meta charset='utf-8'><style>"
        "html,body{margin:0;padding:0;background:#0b0f17;}"
        "iframe{border:0;display:block;width:%dpx;height:%dpx;}"
        "</style></head><body>"
        "<iframe src=\"%s\"></iframe></body></html>" % (width, height, target)
    )
    tmp = pathlib.Path(tempfile.gettempdir()) / ("lld_shot_%d.html" % os.getpid())
    tmp.write_text(wrapper, encoding="utf-8")

    cmd = [
        browser,
        "--headless=new",
        "--disable-gpu",
        "--no-sandbox",
        "--hide-scrollbars",
        "--allow-file-access-from-files",
        "--force-device-scale-factor=1",
        "--user-data-dir=" + str(profile),
        "--window-size=%d,%d" % (max(width + 40, 520), height + 40),
        "--virtual-time-budget=6000",
        "--screenshot=" + str(out_png),
        file_url(tmp),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    tmp.unlink(missing_ok=True)
    if not out_png.exists():
        sys.stderr.write(res.stderr[-1500:] + "\n")
        return False
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--route", default="#/")
    ap.add_argument("--name", default="shot")
    ap.add_argument("--width", type=int, default=390)
    ap.add_argument("--height", type=int, default=844)
    ap.add_argument("--tall", action="store_true", help="capture a long page (height 2600)")
    ap.add_argument("--all", action="store_true", help="capture the standard set of screens")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    browser = find_browser()
    if not browser:
        print("no Edge/Chrome found - looked in:\n  " + "\n  ".join(EDGE_CANDIDATES), file=sys.stderr)
        return 1

    out_dir = pathlib.Path(args.out) if args.out else (HERE / "shots")
    out_dir.mkdir(parents=True, exist_ok=True)
    profile = pathlib.Path(tempfile.gettempdir()) / "lld-edge-profile"

    jobs = SHOTS if args.all else [(args.name, args.route, args.tall)]
    ok = 0
    for name, route, tall in jobs:
        height = 2600 if tall else args.height
        png = out_dir / (name + ".png")
        if png.exists():
            png.unlink()
        if shoot(browser, route, png, args.width, height, profile):
            print("  %-10s %-34s %s (%.0f KB)" % (name, route, png.name, png.stat().st_size / 1024))
            ok += 1
        else:
            print("  FAILED  %s  %s" % (name, route))

    shutil.rmtree(profile, ignore_errors=True)
    print("\n%d/%d screenshots -> %s" % (ok, len(jobs), out_dir))
    return 0 if ok == len(jobs) else 1


if __name__ == "__main__":
    raise SystemExit(main())
