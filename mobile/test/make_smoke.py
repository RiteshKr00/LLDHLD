#!/usr/bin/env python3
"""Builds a JScript smoke test that drives every view of the app against a fake DOM.

There is no browser or Node on this machine, so the app is unwrapped from its IIFE
and run under Windows Script Host with a hand-written DOM stub. It catches the class
of bug that only shows up when a view actually runs: undefined lookups, bad routes,
broken card scheduling.

    python mobile/test/make_smoke.py && cscript //Nologo //E:JScript mobile/test/_smoke.js
"""

import pathlib
import re

HERE = pathlib.Path(__file__).resolve().parent
WWW = HERE.parent / "www"

app = (WWW / "app.js").read_text(encoding="utf-8")
content = (WWW / "content.js").read_text(encoding="utf-8")

# real diagrams get rendered during the view drive, not stubbed out
DIAGRAM_PARTS = ["core.js", "class.js", "flow.js", "state.js", "sequence.js"]
DIAGRAM = "".join((WWW / "diagram" / n).read_text(encoding="utf-8")
                  for n in DIAGRAM_PARTS if (WWW / "diagram" / n).exists())

# unwrap the IIFE so the test can call the app's own functions directly
body = app.split("(function () {", 1)[1]
body = body.rsplit("})();", 1)[0]
body = body.replace("'use strict';", "", 1)

# JScript is an ES3 engine: `catch` is reserved, so `promise.catch(...)` will not
# compile there. Browsers are fine with it - rewrite only for the test run.
body = body.replace(".catch(", "['catch'](")

STUBS = r"""
// ---------------------------------------------------------------- ES5 shims
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
if (!Array.prototype.reduce) Array.prototype.reduce = function (f, acc) {
  for (var i = 0; i < this.length; i++) acc = f(acc, this[i], i, this); return acc;
};
if (!Array.prototype.indexOf) Array.prototype.indexOf = function (v, s) {
  for (var i = s || 0; i < this.length; i++) if (this[i] === v) return i; return -1;
};
if (!Array.prototype.findIndex) Array.prototype.findIndex = function (f) {
  for (var i = 0; i < this.length; i++) if (f(this[i], i, this)) return i; return -1;
};
if (!String.prototype.trim) String.prototype.trim = function () { return this.replace(/^\s+|\s+$/g, ''); };
if (!Object.keys) Object.keys = function (o) { var k = []; for (var n in o) if (o.hasOwnProperty(n)) k.push(n); return k; };
if (!Object.assign) Object.assign = function (t) {
  for (var i = 1; i < arguments.length; i++) { var s = arguments[i]; for (var k in s) if (s.hasOwnProperty(k)) t[k] = s[k]; }
  return t;
};
if (!Date.prototype.toISOString) Date.prototype.toISOString = function () {
  function p(n, w) { n = String(n); while (n.length < (w || 2)) n = '0' + n; return n; }
  return this.getUTCFullYear() + '-' + p(this.getUTCMonth() + 1) + '-' + p(this.getUTCDate())
    + 'T' + p(this.getUTCHours()) + ':' + p(this.getUTCMinutes()) + ':' + p(this.getUTCSeconds()) + '.000Z';
};
if (typeof JSON === 'undefined') {
  JSON = {
    parse: function (s) { return eval('(' + s + ')'); },
    stringify: function (v) {
      if (v === null || v === undefined) return 'null';
      var t = typeof v;
      if (t === 'number') return isFinite(v) ? String(v) : 'null';
      if (t === 'boolean') return String(v);
      if (t === 'string') {
        return '"' + v.replace(/[\\"]/g, '\\$&').replace(/\n/g, '\\n').replace(/\r/g, '\\r')
          .replace(/\t/g, '\\t') + '"';
      }
      if (Object.prototype.toString.call(v) === '[object Array]') {
        var a = [];
        for (var i = 0; i < v.length; i++) a.push(JSON.stringify(v[i]));
        return '[' + a.join(',') + ']';
      }
      var o = [];
      for (var k in v) {
        if (!v.hasOwnProperty(k)) continue;
        var val = JSON.stringify(v[k]);
        if (val !== undefined) o.push(JSON.stringify(String(k)) + ':' + val);
      }
      return '{' + o.join(',') + '}';
    }
  };
}
// the app filters text nodes through a TreeWalker when highlighting search hits
var NodeFilter = { SHOW_TEXT: 4 };
function URLSearchParams(qs) {
  this._m = {};
  var parts = String(qs).split('&');
  for (var i = 0; i < parts.length; i++) {
    var kv = parts[i].split('=');
    if (kv[0]) this._m[decodeURIComponent(kv[0])] = decodeURIComponent((kv[1] || '').replace(/\+/g, ' '));
  }
}
URLSearchParams.prototype.get = function (k) { return this._m.hasOwnProperty(k) ? this._m[k] : null; };

// ------------------------------------------------------------------ fake DOM
function FakeEl(sel) {
  this.sel = sel || '';
  this.innerHTML = '';
  this.textContent = '';
  this.value = '';
  this.className = '';
  this.dataset = {};
  this.style = { setProperty: function () {}, display: '', width: '' };
  this.parentNode = null;
  this.children = [];
}
FakeEl.prototype.addEventListener = function () {};
FakeEl.prototype.removeEventListener = function () {};
FakeEl.prototype.setAttribute = function () {};
FakeEl.prototype.getAttribute = function () { return null; };
FakeEl.prototype.appendChild = function (c) { this.children.push(c); return c; };
FakeEl.prototype.remove = function () {};
FakeEl.prototype.closest = function () { return null; };
FakeEl.prototype.querySelector = function () { return new FakeEl(); };
FakeEl.prototype.querySelectorAll = function () { return []; };
FakeEl.prototype.getBoundingClientRect = function () { return { width: 600, height: 400, top: 0 }; };
FakeEl.prototype.scrollIntoView = function () {};
FakeEl.prototype.focus = function () {};
FakeEl.prototype.blur = function () {};
FakeEl.prototype.classList = null;

function makeClassList() {
  return { add: function () {}, remove: function () {}, toggle: function () {}, contains: function () { return false; } };
}

var _els = {};
var document = {
  querySelector: function (sel) {
    if (!_els[sel]) { _els[sel] = new FakeEl(sel); _els[sel].classList = makeClassList(); }
    return _els[sel];
  },
  querySelectorAll: function () { return []; },
  createElement: function () { var e = new FakeEl(); e.classList = makeClassList(); return e; },
  getElementById: function (id) {
    var k = '#id:' + id;
    if (!_els[k]) { _els[k] = new FakeEl(k); _els[k].classList = makeClassList(); }
    return _els[k];
  },
  createTreeWalker: function () { return { nextNode: function () { return null; } }; },
  addEventListener: function () {},
  documentElement: { setAttribute: function () {}, style: { setProperty: function () {} } },
  head: new FakeEl('head'),
  body: null,
  visibilityState: 'visible'
};
document.body = new FakeEl('body');
document.body.classList = makeClassList();
document.body.scrollHeight = 4000;

var _store = {};
var localStorage = {
  getItem: function (k) { return _store.hasOwnProperty(k) ? _store[k] : null; },
  setItem: function (k, v) { _store[k] = String(v); },
  removeItem: function (k) { delete _store[k]; }
};

var location = { hash: '#/', protocol: 'file:' };
var history = { length: 1, back: function () {} };
var navigator = { clipboard: null };
var window = {
  innerHeight: 800,
  scrollY: 0,
  scrollTo: function () {},
  addEventListener: function () {},
  matchMedia: function () { return { matches: false, addEventListener: function () {} }; },
  LLD_CONTENT: null
};
function setTimeout(f) { if (typeof f === 'function') f(); return 0; }
function clearTimeout() {}
function requestAnimationFrame() {}
function confirm() { return true; }
"""

DRIVER = r"""
// -------------------------------------------------------------------- driver
function out(s) { WScript.Echo(s); }
var fails = 0, checks = 0;

function check(label, cond, extra) {
  checks++;
  if (!cond) { fails++; out('FAIL  ' + label + (extra ? '  (' + extra + ')' : '')); }
}

function html() { return document.querySelector('#app').innerHTML; }

function drive(label, fn) {
  try {
    fn();
    return true;
  } catch (e) {
    fails++;
    out('FAIL  ' + label + '  threw: ' + (e.message || e) + (e.number ? ' [' + e.number + ']' : ''));
    return false;
  }
}

// --- home -------------------------------------------------------------------
drive('home', function () { location.hash = '#/'; route(); });
check('home renders problem cards', html().indexOf('data-go="#/p/01-url-shortener') > -1);
check('home shows coverage', html().indexOf('sections revised') > -1);
check('home lists every problem', html().split('class="card"').length - 1 >= C.problems.length,
      'cards=' + (html().split('class="card"').length - 1));

// --- concepts ---------------------------------------------------------------
drive('concepts', function () { location.hash = '#/concepts'; route(); });
check('concepts lists refs', html().indexOf('data-go="#/r/LLD-patterns"') > -1);

// --- every problem doc ------------------------------------------------------
var docCount = 0;
for (var i = 0; i < C.problems.length; i++) {
  var p = C.problems[i];
  for (var j = 0; j < p.docs.length; j++) {
    var d = p.docs[j];
    var label = 'doc ' + p.id + '/' + d.key;
    var ok = drive(label, function () {
      location.hash = '#/p/' + p.id + '/' + d.key;
      route();
    });
    if (ok) {
      docCount++;
      check(label + ' has prose', html().indexOf('<div class="prose">') > -1);
      check(label + ' non-trivial', html().length > 400, 'len=' + html().length);
      check(label + ' has tabs', html().indexOf('class="tabs"') > -1);
      check(label + ' tracks progress', !!state.docs['p:' + p.id + ':' + d.key]);
    }
  }
}

// --- every reference --------------------------------------------------------
for (var r = 0; r < C.refs.length; r++) {
  var rf = C.refs[r];
  drive('ref ' + rf.id, function () { location.hash = '#/r/' + rf.id; route(); });
  check('ref ' + rf.id + ' renders', html().indexOf('<div class="prose">') > -1);
}

// --- cross-doc navigation ---------------------------------------------------
drive('neighbours', function () {
  location.hash = '#/p/02-parking-lot/problem';
  route();
});
check('reader marks current doc', currentDoc && currentDoc.id === '02-parking-lot',
      currentDoc ? currentDoc.id : 'null');
check('toc collected', currentDoc && currentDoc.toc.length > 2,
      currentDoc ? String(currentDoc.toc.length) : 'null');

drive('mark revised', function () { markDone(true, true); });
check('revised persisted', state.docs['p:02-parking-lot:problem'].done === 1);

// --- search -----------------------------------------------------------------
drive('search view', function () { location.hash = '#/search'; route(); });
var hits = search('strategy');
check('search finds strategy', hits.length > 3, 'hits=' + hits.length);
check('search snippet marks term', hits.length && hits[0].snips.join('').indexOf('<mark>') > -1);
var toctou = search('toctou');
check('search finds TOCTOU', toctou.length > 0, 'hits=' + toctou.length);
check('search rejects nonsense', search('zzzqqqxxx').length === 0);
check('search hit routes into a doc', hits.length && hits[0].entry.route.indexOf('#/') === 0);

// --- deep link with a query -------------------------------------------------
drive('deep link w/ query', function () {
  location.hash = '#/p/01-url-shortener/problem?q=collision';
  route();
});
check('query route still renders', html().indexOf('<div class="prose">') > -1);

// --- revise -----------------------------------------------------------------
drive('revise home', function () { location.hash = '#/revise'; route(); });
check('decks listed', html().indexOf('data-go="#/revise/') > -1);
check('deck count', C.decks.length >= 4, 'decks=' + C.decks.length);

var totalCards = 0;
for (var k = 0; k < C.decks.length; k++) totalCards += C.decks[k].cards.length;
check('cards exist', totalCards > 40, 'cards=' + totalCards);

drive('session start', function () { location.hash = '#/revise/pain'; route(); });
check('session queue built', session && session.total > 0, session ? String(session.total) : 'null');
check('card front rendered', html().indexOf('class="flash"') > -1);
check('show-answer button', html().indexOf('data-show') > -1);

drive('show answer', function () { showAnswer(); });

// grade the whole deck: every card should schedule forward and land in the log
var graded = 0;
drive('grade all', function () {
  var guard = 0;
  while (session && session.i < session.queue.length && guard < 400) {
    grade(guard % 4 === 3 ? 'again' : 'good');
    graded++;
    guard++;
  }
});
check('graded cards', graded > 0, 'graded=' + graded);
var boxed = 0, scheduled = 0;
for (var id in state.cards) {
  if (!state.cards.hasOwnProperty(id)) continue;
  boxed++;
  if (state.cards[id].due > 0) scheduled++;
}
check('cards recorded', boxed > 0, 'boxed=' + boxed);
check('cards scheduled', scheduled === boxed, scheduled + '/' + boxed);
check('daily log written', state.log[today()] === graded, state.log[today()] + ' vs ' + graded);

// a card graded "good" must move up a box and be due later than one graded "again"
var goodCard = null, againCard = null;
var deck = C.decks[0];
for (var c = 0; c < deck.cards.length; c++) {
  var st = state.cards[deck.cards[c].id];
  if (!st) continue;
  if (st.box > 0 && !goodCard) goodCard = st;
  if (st.box === 0 && !againCard) againCard = st;
}
check('good card promoted', !goodCard || goodCard.box >= 1, goodCard ? 'box=' + goodCard.box : 'none');
check('again card reset', !againCard || againCard.box === 0);
check('due dates ordered', !goodCard || !againCard || goodCard.due > againCard.due);

// --- mixed session ----------------------------------------------------------
drive('mixed session', function () { location.hash = '#/revise/all'; route(); });

// --- settings sheet ---------------------------------------------------------
drive('settings sheet', function () { openSettings(); });

// --- diagram controls must not collide with the reader footer ---------------
drive('diagram markup', function () {
  location.hash = '#/p/01-url-shortener/diagrams';
  route();
});
var dh = html();
check('diagrams rendered in the doc', dh.indexOf('class="diagram') > -1);
// [data-done] selects the "Mark revised" button; if a diagram carried it, every click
// inside a diagram would mark the section revised and swallow the diagram's own buttons
var seg = dh.split('class="diagram');
var leaked = 0;
for (var s2 = 1; s2 < seg.length; s2++) {
  var chunk = seg[s2].split('</div></div>')[0];
  if (chunk.indexOf('data-done') > -1) leaked++;
}
check('no diagram carries data-done', leaked === 0, 'leaked=' + leaked);
check('diagram has its own controls', dh.indexOf('data-dfull') > -1 && dh.indexOf('data-dseen') > -1
      && dh.indexOf('data-src-toggle') > -1);

// --- backup / restore -------------------------------------------------------
drive('backup sheet', function () { openBackup(); });

var savedJson = JSON.stringify(state);
var docsBefore = 0, k;
for (k in state.docs) if (state.docs.hasOwnProperty(k)) docsBefore++;
check('backup has content to save', docsBefore > 0, 'docs=' + docsBefore);

// garbage must be rejected without destroying anything
drive('restore rejects garbage', function () {
  document.getElementById('bk').value = 'not json at all';
  restoreBackup();
});
var docsAfterGarbage = 0;
for (k in state.docs) if (state.docs.hasOwnProperty(k)) docsAfterGarbage++;
check('garbage restore left state intact', docsAfterGarbage === docsBefore,
      docsAfterGarbage + ' vs ' + docsBefore);

// valid JSON of the wrong shape must also be rejected
drive('restore rejects wrong shape', function () {
  document.getElementById('bk').value = '{"hello":"world"}';
  restoreBackup();
});
var docsAfterShape = 0;
for (k in state.docs) if (state.docs.hasOwnProperty(k)) docsAfterShape++;
check('wrong-shape restore left state intact', docsAfterShape === docsBefore);

// a real backup must come back
drive('restore accepts a real backup', function () {
  state.docs = {};
  state.cards = {};
  document.getElementById('bk').value = savedJson;
  restoreBackup();
});
var docsRestored = 0, cardsRestored = 0;
for (k in state.docs) if (state.docs.hasOwnProperty(k)) docsRestored++;
for (k in state.cards) if (state.cards.hasOwnProperty(k)) cardsRestored++;
check('restored docs', docsRestored === docsBefore, docsRestored + ' vs ' + docsBefore);
check('restored cards', cardsRestored > 0, 'cards=' + cardsRestored);
check('restore wrote through to storage',
      (localStorage.getItem('lld:v1') || '').length > 200);

// backgrounding the app must flush immediately, not wait on the debounce
drive('flush on hide', function () {
  state.docs['p:01-url-shortener:problem'] = { p: 1, done: 1, t: 1 };
  writeNow();
  var back = JSON.parse(localStorage.getItem('lld:v1'));
  check('flushed latest change', back.docs['p:01-url-shortener:problem'].done === 1);
});

// --- unknown route falls back ----------------------------------------------
drive('unknown route', function () { location.hash = '#/nope/nothing'; route(); });
check('fallback renders home', html().indexOf('sections revised') > -1);

// --- state round trip -------------------------------------------------------
drive('state json', function () {
  var s = JSON.stringify(state);
  check('state serialises', s.length > 200, 'len=' + s.length);
  var stored = localStorage.getItem('lld:v1');
  check('state persisted to storage', !!stored && stored.length > 200,
        stored ? 'len=' + stored.length : 'nothing stored');
  var back = JSON.parse(stored);
  var n = 0, m = 0;
  for (var a in back.cards) if (back.cards.hasOwnProperty(a)) n++;
  for (var b in state.cards) if (state.cards.hasOwnProperty(b)) m++;
  check('cards survive a round trip', n === m && n > 0, n + ' vs ' + m);
  check('revised flags survive', back.docs['p:02-parking-lot:problem'].done === 1);
});

out('');
out('drove ' + docCount + ' problem docs + ' + C.refs.length + ' references');
out(checks + ' checks, ' + fails + ' failures');
if (fails) WScript.Quit(1);
"""

smoke = STUBS + "\n" + content + "\n" + DIAGRAM + "\n" + body + "\n" + DRIVER

out = HERE / "_smoke.js"
out.write_text(smoke, encoding="utf-16")
print("wrote", out, "({:.1f} MB)".format(out.stat().st_size / 1024 / 1024))
