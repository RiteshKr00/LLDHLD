#!/usr/bin/env python3
"""Renders every mermaid block in the notes through the app's own diagram renderer.

No browser needed: the renderer is a pure string -> SVG transform, so it runs under
Windows Script Host. Each diagram is written out as a real .svg file for check_svg.py
(and for eyeballing).

    python mobile/test/make_diagram_test.py                  # all types
    python mobile/test/make_diagram_test.py --type classDiagram
    cscript //Nologo //E:JScript mobile/test/_diag.js
"""

import argparse
import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
WWW = HERE.parent / "www"
NOTES = HERE.parent.parent

ORDER = ["core.js", "class.js", "flow.js", "state.js", "sequence.js"]

TYPE_OF = [
    (re.compile(r"^classDiagram"), "classDiagram"),
    (re.compile(r"^stateDiagram(-v2)?"), "stateDiagram"),
    (re.compile(r"^(flowchart|graph)\b"), "flowchart"),
    (re.compile(r"^sequenceDiagram"), "sequenceDiagram"),
]


def diagram_type(src: str) -> str:
    head = ""
    for line in src.split("\n"):
        line = line.strip()
        if line and not line.startswith("%%"):
            head = line
            break
    for rx, name in TYPE_OF:
        if rx.match(head):
            return name
    return "unknown"


def collect():
    out = []
    seen = {}
    for f in sorted(NOTES.rglob("*.md")):
        if "mobile" in f.parts:
            continue
        text = f.read_text(encoding="utf-8", errors="replace")
        for i, m in enumerate(re.finditer(r"```mermaid\n(.*?)\n```", text, re.S)):
            src = m.group(1)
            stem = f.parent.name if f.parent != NOTES else f.stem
            name = "%s-%d" % (stem, i + 1)
            seen[name] = seen.get(name, 0) + 1
            if seen[name] > 1:
                name = "%s-%d" % (name, seen[name])
            out.append({"name": name, "type": diagram_type(src), "src": src,
                        "file": str(f.relative_to(NOTES)).replace("\\", "/")})
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--type", default="all", help="classDiagram | flowchart | stateDiagram | sequenceDiagram | all")
    ap.add_argument("--out", default=None, help="output folder for the .svg files")
    args = ap.parse_args()

    diagrams = collect()
    if args.type != "all":
        diagrams = [d for d in diagrams if d["type"] == args.type]
    if not diagrams:
        print("no diagrams matched --type " + args.type, file=sys.stderr)
        return 1

    out_dir = HERE / (args.out or ("out-" + args.type))
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("*.svg"):
        old.unlink()

    src_js = ""
    for name in ORDER:
        f = WWW / "diagram" / name
        if f.exists():
            src_js += "\n// ==== " + name + " ====\n" + f.read_text(encoding="utf-8")

    manifest = [{"name": d["name"], "type": d["type"], "src": d["src"], "file": d["file"]} for d in diagrams]

    harness = (
        "var window = this;\n"
        "if (!Array.prototype.forEach) Array.prototype.forEach = function (f) {"
        " for (var i=0;i<this.length;i++) f(this[i], i, this); };\n"
        "if (!Array.prototype.map) Array.prototype.map = function (f) {"
        " var o=[]; for (var i=0;i<this.length;i++) o.push(f(this[i], i, this)); return o; };\n"
        "if (!Array.prototype.filter) Array.prototype.filter = function (f) {"
        " var o=[]; for (var i=0;i<this.length;i++) if (f(this[i],i,this)) o.push(this[i]); return o; };\n"
        "if (!Array.prototype.indexOf) Array.prototype.indexOf = function (v) {"
        " for (var i=0;i<this.length;i++) if (this[i]===v) return i; return -1; };\n"
        "if (!Array.prototype.some) Array.prototype.some = function (f) {"
        " for (var i=0;i<this.length;i++) if (f(this[i],i,this)) return true; return false; };\n"
        "if (!String.prototype.trim) String.prototype.trim = function () {"
        " return this.replace(/^\\s+|\\s+$/g, ''); };\n"
        + src_js +
        "\nvar DIAGRAMS = " + json.dumps(manifest, ensure_ascii=False) + ";\n"
        "var OUT = " + json.dumps(str(out_dir)) + ";\n"
        r"""
function writeFile(path, text) {
  var fso = new ActiveXObject('Scripting.FileSystemObject');
  var f = fso.CreateTextFile(path, true, true);   // unicode: UTF-16LE, read back with encoding='utf-16'
  f.Write(text);
  f.Close();
}

var ok = 0, bad = 0;
for (var i = 0; i < DIAGRAMS.length; i++) {
  var d = DIAGRAMS[i];
  try {
    var svg = window.LLDD.render(d.src);
    if (typeof svg !== 'string' || svg.indexOf('<svg') !== 0) {
      throw new Error('renderer did not return svg markup');
    }
    writeFile(OUT + '\\' + d.name + '.svg', svg);
    var m = svg.match(/viewBox="0 0 (\d+) (\d+)"/);
    WScript.Echo('  ok    ' + d.type + '  ' + d.name + '  ' + (m ? m[1] + 'x' + m[2] : '?'));
    ok++;
  } catch (e) {
    WScript.Echo('  FAIL  ' + d.type + '  ' + d.name + '  ' + (e.message || e));
    bad++;
  }
}
WScript.Echo('');
WScript.Echo(ok + ' rendered, ' + bad + ' failed  ->  ' + OUT);
if (bad) WScript.Quit(1);
"""
    )

    # per-type harness file, so several types can be tested in parallel
    js = HERE / ("_diag-%s.js" % args.type)
    js.write_text(harness, encoding="utf-16")
    print("%d diagrams (%s)" % (len(diagrams), args.type))
    print("run: cscript //Nologo //E:JScript %s" % js)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
