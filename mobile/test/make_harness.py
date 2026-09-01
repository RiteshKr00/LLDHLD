#!/usr/bin/env python3
"""Builds a JScript harness that runs the app's markdown renderer over every doc.

There is no Node on this machine, so the renderer is exercised with Windows Script
Host (cscript //E:JScript), which is an old engine - the harness shims the ES5 bits
the renderer relies on, stubs the DOM, and then checks the produced HTML.

    python mobile/test/make_harness.py && cscript //Nologo //E:JScript mobile/test/_harness.js
"""

import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
WWW = HERE.parent / "www"

app = (WWW / "app.js").read_text(encoding="utf-8")

# The diagram renderer has to be loaded too, or every mermaid block would quietly
# fall back to showing its source and this test would not notice.
DIAGRAM_PARTS = ["core.js", "class.js", "flow.js", "state.js", "sequence.js"]
DIAGRAM = "".join((WWW / "diagram" / n).read_text(encoding="utf-8")
                  for n in DIAGRAM_PARTS if (WWW / "diagram" / n).exists())

start = app.index("var C = window.LLD_CONTENT")
end = app.index("// ------------------------------------------------------------- rendering")
chunk = app[start:end]

content = json.loads(
    (WWW / "content.js").read_text(encoding="utf-8")
    .split("window.LLD_CONTENT = ", 1)[1].rstrip().rstrip(";")
    .replace("<\\/", "</")
)

docs = []
for p in content["problems"]:
    for d in p["docs"]:
        docs.append({"name": p["id"] + "/" + d["key"], "md": d["md"], "ctx": {"kind": "p", "id": p["id"]}})
for r in content["refs"]:
    docs.append({"name": r["id"], "md": r["md"], "ctx": {"kind": "r", "id": r["id"]}})
for deck in content["decks"]:
    for c in deck["cards"][:3]:
        docs.append({"name": "card/" + deck["id"] + "/" + c["id"], "md": c["front"] + "\n\n" + c["back"], "ctx": None})

SHIMS = r"""
// --- ES5 shims, because Windows Script Host predates most of them -----------
if (!Array.prototype.forEach) Array.prototype.forEach = function (f, t) {
  for (var i = 0; i < this.length; i++) f.call(t, this[i], i, this);
};
if (!Array.prototype.map) Array.prototype.map = function (f, t) {
  var o = []; for (var i = 0; i < this.length; i++) o.push(f.call(t, this[i], i, this)); return o;
};
if (!Array.prototype.filter) Array.prototype.filter = function (f, t) {
  var o = []; for (var i = 0; i < this.length; i++) if (f.call(t, this[i], i, this)) o.push(this[i]); return o;
};
if (!Array.prototype.some) Array.prototype.some = function (f, t) {
  for (var i = 0; i < this.length; i++) if (f.call(t, this[i], i, this)) return true; return false;
};
if (!Array.prototype.indexOf) Array.prototype.indexOf = function (v, s) {
  for (var i = s || 0; i < this.length; i++) if (this[i] === v) return i; return -1;
};
if (!Array.prototype.findIndex) Array.prototype.findIndex = function (f) {
  for (var i = 0; i < this.length; i++) if (f(this[i], i, this)) return i; return -1;
};
if (!String.prototype.trim) String.prototype.trim = function () {
  return this.replace(/^[\s﻿\xA0]+|[\s﻿\xA0]+$/g, '');
};
if (!Object.keys) Object.keys = function (o) { var k = []; for (var n in o) if (o.hasOwnProperty(n)) k.push(n); return k; };
if (!Object.assign) Object.assign = function (t) {
  for (var i = 1; i < arguments.length; i++) { var s = arguments[i]; for (var k in s) if (s.hasOwnProperty(k)) t[k] = s[k]; }
  return t;
};
if (typeof JSON === 'undefined') JSON = { parse: function () { return {}; }, stringify: function () { return '{}'; } };

// --- DOM / browser stubs ---------------------------------------------------
var localStorage = { getItem: function () { return null; }, setItem: function () {} };
var navigator = { clipboard: null };
var document = {
  querySelector: function () { return null; },
  querySelectorAll: function () { return []; },
  createElement: function () { return { classList: { add: function () {}, remove: function () {} } }; },
  addEventListener: function () {},
  documentElement: { setAttribute: function () {}, style: { setProperty: function () {} } },
  body: { appendChild: function () {} }
};
var window = {
  addEventListener: function () {},
  matchMedia: function () { return { matches: false, addEventListener: function () {} }; }
};
function setTimeout() {} function clearTimeout() {} function requestAnimationFrame() {}
"""

DRIVER = r"""
// --- driver ----------------------------------------------------------------
function out(s) { WScript.Echo(s); }

function count(hay, needle) {
  var n = 0, i = hay.indexOf(needle);
  while (i > -1) { n++; i = hay.indexOf(needle, i + needle.length); }
  return n;
}

var failures = 0, warnings = 0, totalHtml = 0, totalToc = 0, svgs = 0, fallbacks = 0;

for (var i = 0; i < DOCS.length; i++) {
  var d = DOCS[i];
  var toc = [];
  var html;
  try {
    html = md2html(d.md, { ctx: d.ctx, toc: toc });
  } catch (err) {
    out('FAIL  ' + d.name + '  threw: ' + (err.message || err));
    failures++;
    continue;
  }
  totalHtml += html.length;
  totalToc += toc.length;
  svgs += count(html, '<svg');
  fallbacks += count(html, 'class="dsrc"');

  var problems = [];
  if (html.length === 0 && d.md.length > 0) problems.push('empty output');
  if (html.indexOf(String.fromCharCode(0)) > -1 || html.indexOf(String.fromCharCode(1)) > -1
      || html.indexOf(String.fromCharCode(2)) > -1) {
    problems.push('leaked placeholder sentinel');
  }
  var opens = count(html, '<pre'), closes = count(html, '</pre>');
  if (opens !== closes) problems.push('pre ' + opens + '/' + closes);
  var li = count(html, '<li>'), lie = count(html, '</li>');
  if (li !== lie) problems.push('li ' + li + '/' + lie);
  var ul = count(html, '<ul>') + count(html, '<ol>');
  var ule = count(html, '</ul>') + count(html, '</ol>');
  if (ul !== ule) problems.push('list ' + ul + '/' + ule);
  var td = count(html, '<td'), tde = count(html, '</td>');
  if (td !== tde) problems.push('td ' + td + '/' + tde);
  var bq = count(html, '<blockquote>'), bqe = count(html, '</blockquote>');
  if (bq !== bqe) problems.push('blockquote ' + bq + '/' + bqe);
  var st = count(html, '<strong>'), ste = count(html, '</strong>');
  if (st !== ste) problems.push('strong ' + st + '/' + ste);
  var cd = count(html, '<code>'), cde = count(html, '</code>');
  if (cd !== cde) problems.push('code ' + cd + '/' + cde);

  // fenced blocks in the source must all survive as rendered code or diagrams
  var fences = 0, re = /^```/gm, m;
  while ((m = re.exec(d.md))) fences++;
  var rendered = count(html, '<div class="codewrap') + count(html, '<div class="diagram');
  if (fences >= 2 && rendered < Math.floor(fences / 2)) {
    problems.push('fences ' + Math.floor(fences / 2) + ' -> ' + rendered);
  }

  if (problems.length) {
    out('WARN  ' + d.name + '  ' + problems.join(', '));
    warnings++;
  }
}

out('');
out('checked ' + DOCS.length + ' docs, ' + Math.round(totalHtml / 1024) + ' KB html, '
    + totalToc + ' toc entries');
out('diagrams: ' + svgs + ' rendered as svg, ' + fallbacks + ' fell back to source');
out(failures + ' failures, ' + warnings + ' warnings');

// --- spot checks -----------------------------------------------------------
out('');
out('--- spot checks ---');
function show(label, src) {
  out(label + ': ' + md2html(src, { ctx: { kind: 'p', id: '02-parking-lot' } }));
}
show('table', '| a | b |\n|---|--:|\n| 1 | `x` |');
show('nested list', '- one\n  - deep **bold**\n- two');
show('ordered+code', '1. first\n2. second\n\n```python\ndef f(x):\n    return x  # hi\n```');
show('quote', '> **Golden rule:** every box exists because a *number* demanded it.');
show('link', 'see [solution.py](solution.py) and [the bank](../HLD-method-bank.md) and [dead](nope.md)');
show('inline', 'a `code_span` with **bold**, *em*, and a C1 T2 literal');
show('mermaid', '```mermaid\nclassDiagram\n  A --> B\n```');
show('setext-ish', '#### Heading four\ntext under it');
"""

# A trimmed copy of the bundle, so resolveLink() can tell a real cross-reference
# from a dead one without carrying every doc's markdown twice.
stub = {
    "problems": [{"id": p["id"], "num": p["num"], "title": p["title"], "tags": p["tags"], "mins": p["mins"],
                  "docs": [{"key": d["key"], "label": d["label"], "md": "", "mins": d["mins"]} for d in p["docs"]]}
                 for p in content["problems"]],
    "refs": [{"id": r["id"], "group": r["group"], "title": r["title"], "md": "", "mins": r["mins"]}
             for r in content["refs"]],
    "decks": [],
}

harness = (SHIMS
           + "\nwindow.LLD_CONTENT = " + json.dumps(stub, ensure_ascii=False) + ";\n"
           + "\nvar DOCS = " + json.dumps(docs, ensure_ascii=False) + ";\n"
           + DIAGRAM + "\n" + chunk + "\n" + DRIVER)

out = HERE / "_harness.js"
# Windows Script Host reads Unicode source only as UTF-16 LE with a BOM.
out.write_text(harness, encoding="utf-16")
print("wrote", out, "({:.1f} MB)".format(out.stat().st_size / 1024 / 1024))
print("run: cscript //Nologo //E:JScript " + str(out))
