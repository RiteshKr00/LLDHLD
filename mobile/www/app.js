/* LLD Prep - offline study app.
   No frameworks, no network. Content comes from content.js (built by mobile/build.py). */

(function () {
  'use strict';

  var C = window.LLD_CONTENT || { problems: [], refs: [], decks: [], mocks: [] };
  if (!C.mocks) C.mocks = [];
  var SINGLE = !!window.LLD_SINGLE_FILE;

  // ------------------------------------------------------------------ utils

  function $(sel, root) { return (root || document).querySelector(sel); }
  function $$(sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }

  function esc(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  function slug(s) {
    return String(s).toLowerCase().replace(/[^\w\s-]/g, '').trim()
      .replace(/\s+/g, '-').slice(0, 60);
  }

  function clamp(n, lo, hi) { return n < lo ? lo : n > hi ? hi : n; }

  var toastEl;
  function toast(msg) {
    if (!toastEl) {
      toastEl = document.createElement('div');
      toastEl.className = 'toast';
      toastEl.setAttribute('role', 'status');
      toastEl.setAttribute('aria-live', 'polite');
      document.body.appendChild(toastEl);
    }
    toastEl.textContent = msg;
    requestAnimationFrame(function () { toastEl.classList.add('in'); });
    clearTimeout(toast._t);
    toast._t = setTimeout(function () { toastEl.classList.remove('in'); }, 1700);
  }

  // ------------------------------------------------------------------ state

  var KEY = 'lld:v1';
  var state = load();

  function load() {
    var base = {
      settings: { theme: 'system', size: 2, wake: false, goal: 3, interviewDate: '' },
      docs: {},     // docKey -> {p: scroll 0..1, done: 1|0, t: last opened }
      star: {},     // problem id -> 1
      cards: {},    // card id -> {box, due, n}
      open: {},     // section key -> 0 when the user collapsed it (default open)
      diag: {},     // diagram hash -> 1 once you have been through it
      mock: {},     // mock id -> {best, runs, last, missed}
      streak: {},   // 'YYYY-MM-DD' -> units of work done that day
      lastPath: null,  // which track's path Home should point at - null means
                        // never chosen, distinct from having genuinely chosen 'ai'
      last: null    // last route
    };
    try {
      var raw = JSON.parse(localStorage.getItem(KEY) || '{}');
      Object.keys(base).forEach(function (k) {
        if (raw[k] && typeof raw[k] === 'object') base[k] = Object.assign(base[k], raw[k]);
        else if (raw[k] !== undefined) base[k] = raw[k];
      });
    } catch (e) { /* first run, or storage blocked */ }
    return base;
  }

  var saveTimer;
  var storageOk = true;

  /* Write through immediately. Called on a debounce during use, and directly whenever
     the app is being backgrounded - on a phone the OS can kill the process without
     warning, and a pending 250ms timer would take the last answer with it. */
  function writeNow() {
    clearTimeout(saveTimer);
    saveTimer = null;
    try {
      localStorage.setItem(KEY, JSON.stringify(state));
      storageOk = true;
    } catch (e) {
      storageOk = false;                 // private window, quota, or a locked-down origin
    }
  }

  function save() {
    clearTimeout(saveTimer);
    saveTimer = setTimeout(writeNow, 250);
  }

  window.addEventListener('pagehide', writeNow);
  window.addEventListener('beforeunload', writeNow);
  document.addEventListener('visibilitychange', function () {
    if (document.visibilityState === 'hidden') writeNow();
  });

  /* Ask the browser not to evict this origin's storage when space runs low. Installed
     apps are usually granted it silently; a plain browser tab may not be. */
  if (navigator.storage && navigator.storage.persist) {
    try { navigator.storage.persist(); } catch (e) { /* not supported */ }
  }

  function doc(key) {
    if (!state.docs[key]) state.docs[key] = { p: 0, done: 0, t: 0 };
    return state.docs[key];
  }

  /* Local date, not UTC. toISOString() rolls the day over at 05:30 in IST,
     so a session at 1am used to count for the day before. */
  function today(d) {
    d = d ? new Date(d) : new Date();
    return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0')
      + '-' + String(d.getDate()).padStart(2, '0');
  }

  function dayBefore(key, n) {
    if (n === undefined) n = 1;
    var q = key.split('-'), d = new Date(+q[0], +q[1] - 1, +q[2]);
    d.setDate(d.getDate() - n);
    return today(d);
  }

  var GOALS = [1, 3, 5];
  function goalN() {
    var g = state.settings.goal;
    return GOALS.indexOf(g) > -1 ? g : 3;
  }
  function metOn(k) { return (state.streak[k] || 0) >= goalN(); }

  /* Derived from the day log every time, never stored. A restored backup, a
     flight across timezones or a nudged clock cannot leave a phantom streak. */
  function streakInfo() {
    var t = today();
    var cur = 0, k = metOn(t) ? t : dayBefore(t);
    while (metOn(k)) { cur++; k = dayBefore(k); }
    var best = 0, run = 0, prev = null;
    Object.keys(state.streak).filter(metOn).sort().forEach(function (d) {
      run = (prev && dayBefore(d) === prev) ? run + 1 : 1;
      if (run > best) best = run;
      prev = d;
    });
    return { cur: cur, best: Math.max(best, cur), n: state.streak[t] || 0,
             goal: goalN(), met: metOn(t) };
  }

  /* One unit of work: a section read to the end, a card graded, a mock run. */
  function bump(n) {
    var t = today(), was = metOn(t);
    state.streak[t] = (state.streak[t] || 0) + (n || 1);
    save();
    if (!was && metOn(t)) {
      var s = streakInfo();
      toast(s.cur > 1 ? s.cur + '-day streak' : 'Streak started');
    }
  }

  function weekStrip() {
    var t = today(), out = '';
    for (var i = 6; i >= 0; i--) {
      var k = dayBefore(t, i);
      var q = k.split('-'), d = new Date(+q[0], +q[1] - 1, +q[2]);
      var cls = metOn(k) ? ' met' : ((state.streak[k] || 0) ? ' some' : '');
      out += '<div class="wd' + cls + (i === 0 ? ' now' : '') + '">'
        + '<i></i><span>' + 'SMTWTFS'.charAt(d.getDay()) + '</span></div>';
    }
    return '<div class="week">' + out + '</div>';
  }

  // ------------------------------------------------------- content lookups

  var byId = {};
  C.problems.forEach(function (p) { byId['p:' + p.id] = p; });
  C.refs.forEach(function (r) { byId['r:' + r.id] = r; });
  C.mocks.forEach(function (m) { byId['m:' + m.id] = m; });

  function problem(id) { return byId['p:' + id]; }
  function ref(id) { return byId['r:' + id]; }
  function docOf(p, key) {
    for (var i = 0; i < p.docs.length; i++) if (p.docs[i].key === key) return p.docs[i];
    return p.docs[0];
  }
  function docKey(kind, id, sub) { return kind + ':' + id + (sub ? ':' + sub : ''); }

  // -------------------------------------------------------------- markdown

  var PY_KEYWORDS = ('def class return if elif else for while in not and or import from as with try except '
    + 'finally raise yield lambda None True False self pass break continue global nonlocal assert del is '
    + 'async await print').split(' ');

  var PY_RE = new RegExp(
    '(#[^\\n]*)'                                                    // 1 comment
    + '|("""[\\s\\S]*?"""|\'\'\'[\\s\\S]*?\'\'\''                    // 2 strings
    + '|"(?:[^"\\\\\\n]|\\\\.)*"|\'(?:[^\'\\\\\\n]|\\\\.)*\')'
    + '|(@[\\w.]+)'                                                  // 3 decorator
    + '|\\b(' + PY_KEYWORDS.join('|') + ')\\b'                       // 4 keyword
    + '|\\b(\\d[\\d_]*(?:\\.\\d+)?)\\b'                              // 5 number
    + '|\\b([A-Za-z_]\\w*)(?=\\s*\\()'                               // 6 call
    + '|\\b([A-Z][A-Za-z0-9_]*)\\b',                                 // 7 class-ish
    'g');

  function hlPython(code) {
    var out = '', last = 0, m;
    PY_RE.lastIndex = 0;
    while ((m = PY_RE.exec(code))) {
      out += esc(code.slice(last, m.index));
      var cls = m[1] ? 'com' : m[2] ? 'str' : m[3] ? 'dec' : m[4] ? 'kw'
        : m[5] ? 'num' : m[6] ? 'fn' : 'cls';
      out += '<span class="tk-' + cls + '">' + esc(m[0]) + '</span>';
      last = m.index + m[0].length;
      if (m[0].length === 0) PY_RE.lastIndex++;
    }
    return out + esc(code.slice(last));
  }

  /* Link rewriting: the notes cross-reference each other with relative paths.
     Turn those into in-app routes so they work offline, on a phone. */
  function resolveLink(href, ctx) {
    if (/^(https?:|mailto:)/i.test(href)) return { href: href, ext: true };
    if (href.charAt(0) === '#') return { href: href };
    var clean = href.replace(/^\.\//, '').split('#')[0];
    var m = clean.match(/^\.\.\/([\w.-]+)\.md$/) || clean.match(/^([\w.-]+)\.md$/);
    if (m && ref(m[1])) return { href: '#/r/' + m[1] };
    m = clean.match(/^\.\.\/(\d{2}-[\w-]+)\/([\w-]+)\.(md|py)$/);
    if (m && problem(m[1])) return { href: '#/p/' + m[1] + '/' + (m[3] === 'py' ? 'solution' : m[2]) };
    m = clean.match(/^(\d{2}-[\w-]+)\/([\w-]+)\.(md|py)$/);
    if (m && problem(m[1])) return { href: '#/p/' + m[1] + '/' + (m[3] === 'py' ? 'solution' : m[2]) };
    if (ctx && ctx.kind === 'p') {
      m = clean.match(/^([\w-]+)\.(md|py)$/);
      if (m) {
        var key = m[2] === 'py' ? 'solution' : m[1];
        var p = problem(ctx.id);
        if (p && p.docs.some(function (d) { return d.key === key; })) {
          return { href: '#/p/' + ctx.id + '/' + key };
        }
      }
    }
    return null;                                    // unresolvable: render as plain text
  }

  function inline(text, ctx) {
    var codes = [], tags = [];
    text = String(text).replace(/`([^`]+)`/g, function (_, c) {
      codes.push(c); return '\u0001C' + (codes.length - 1) + '\u0001';
    });
    text = esc(text);
    // [label](target)
    text = text.replace(/\[([^\]]+)\]\(([^)\s]+)(?:\s+&quot;[^&]*&quot;)?\)/g, function (_, label, href) {
      var r = resolveLink(href.replace(/&amp;/g, '&'), ctx);
      if (!r) return label;
      var a = '<a href="' + esc(r.href) + '"' + (r.ext ? ' target="_blank" rel="noopener"' : '') + '>' + label + '</a>';
      tags.push(a);
      return '\u0002T' + (tags.length - 1) + '\u0002';
    });
    // bare urls
    text = text.replace(/(^|[\s(])(https?:\/\/[^\s<)]+)/g, function (_, pre, url) {
      tags.push('<a href="' + esc(url) + '" target="_blank" rel="noopener">' + esc(url) + '</a>');
      return pre + '\u0002T' + (tags.length - 1) + '\u0002';
    });
    text = text.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    text = text.replace(/(^|[\s(\[])\*([^*\n]+)\*(?=[\s.,;:!?)\]]|$)/g, '$1<em>$2</em>');
    text = text.replace(/~~([^~]+)~~/g, '<del>$1</del>');
    text = text.replace(/\u0002T(\d+)\u0002/g, function (_, i) { return tags[+i]; });
    text = text.replace(/\u0001C(\d+)\u0001/g, function (_, i) { return '<code>' + esc(codes[+i]) + '</code>'; });
    return text;
  }

  function renderCode(block) {
    var lang = block.lang || '';
    if (lang === 'mermaid') {
      return diagramBlock(block.code);
    }
    var body = lang === 'python' ? hlPython(block.code) : esc(block.code);
    return '<div class="codewrap' + (lang ? ' has-lang' : '') + '">'
      + (lang ? '<span class="lang">' + esc(lang) + '</span>' : '')
      + '<button class="copy" data-copy>Copy</button>'
      + '<pre><code>' + body + '</code></pre></div>';
  }

  function md2html(src, opts) {
    opts = opts || {};
    var ctx = opts.ctx, toc = opts.toc;
    src = String(src).replace(/\r\n?/g, '\n').replace(/\t/g, '    ');

    var blocks = [];
    src = src.replace(/^([ \t]*)```([\w+-]*)[ \t]*\n([\s\S]*?)^[ \t]*```[ \t]*$/gm, function (_, ind, lang, code) {
      blocks.push({ lang: lang, code: code.replace(/\n$/, '') });
      return ind + '\u0000B' + (blocks.length - 1) + '\u0000';
    });

    var lines = src.split('\n');
    var seenIds = {};

    function headingId(text) {
      var base = slug(text.replace(/`|\*\*|\*/g, '')) || 'section';
      var id = base, n = 2;
      while (seenIds[id]) id = base + '-' + (n++);
      seenIds[id] = 1;
      return id;
    }

    function isBlockStart(line) {
      return /^\s*$/.test(line) || /^#{1,6}\s/.test(line) || /^\s*(-{3,}|\*{3,}|_{3,})\s*$/.test(line)
        || /^>/.test(line) || /^\s*([-*+]|\d+[.)])\s+/.test(line) || /^\s*\|/.test(line)
        || /^\s*\u0000B\d+\u0000\s*$/.test(line);
    }

    function parse(lines) {
      var out = [], i = 0;
      while (i < lines.length) {
        var line = lines[i];

        if (/^\s*$/.test(line)) { i++; continue; }

        var fence = line.match(/^\s*\u0000B(\d+)\u0000\s*$/);
        if (fence) { out.push(renderCode(blocks[+fence[1]])); i++; continue; }

        var h = line.match(/^(#{1,6})\s+(.+?)\s*#*$/);
        if (h) {
          var lvl = h[1].length, txt = h[2].trim();
          var id = headingId(txt);
          if (toc && lvl >= 2 && lvl <= 3) toc.push({ id: id, text: txt.replace(/`|\*\*/g, ''), lvl: lvl });
          out.push('<h' + lvl + ' id="' + id + '">' + inline(txt, ctx) + '</h' + lvl + '>');
          i++; continue;
        }

        if (/^\s*(-{3,}|\*{3,}|_{3,})\s*$/.test(line)) { out.push('<hr>'); i++; continue; }

        if (/^\s*>/.test(line)) {
          var buf = [];
          while (i < lines.length && (/^\s*>/.test(lines[i]) || (buf.length && !/^\s*$/.test(lines[i]) && !isBlockStart(lines[i])))) {
            buf.push(lines[i].replace(/^\s*>\s?/, ''));
            i++;
          }
          out.push('<blockquote>' + parse(buf) + '</blockquote>');
          continue;
        }

        // table: header row + separator row
        if (/^\s*\|/.test(line) && i + 1 < lines.length && /^\s*\|?[\s:|-]*-[\s:|-]*$/.test(lines[i + 1]) && lines[i + 1].indexOf('-') > -1) {
          var cells = function (row) {
            return row.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map(function (c) { return c.trim(); });
          };
          var head = cells(line);
          var aligns = cells(lines[i + 1]).map(function (c) {
            if (/^:.*:$/.test(c)) return 'center';
            if (/:$/.test(c)) return 'right';
            return 'left';
          });
          i += 2;
          var rows = [];
          while (i < lines.length && /^\s*\|/.test(lines[i])) { rows.push(cells(lines[i])); i++; }
          var t = '<div class="tablewrap"><table><thead><tr>';
          head.forEach(function (c, n) {
            t += '<th style="text-align:' + (aligns[n] || 'left') + '">' + inline(c, ctx) + '</th>';
          });
          t += '</tr></thead><tbody>';
          rows.forEach(function (r) {
            t += '<tr>';
            head.forEach(function (_, n) {
              t += '<td style="text-align:' + (aligns[n] || 'left') + '">' + inline(r[n] || '', ctx) + '</td>';
            });
            t += '</tr>';
          });
          out.push(t + '</tbody></table></div>');
          continue;
        }

        var li = line.match(/^(\s*)([-*+]|\d+[.)])\s+(.*)$/);
        if (li) {
          var baseIndent = li[1].length;
          var ordered = /\d/.test(li[2]);
          var items = [], cur = null;
          while (i < lines.length) {
            var l = lines[i];
            if (/^\s*$/.test(l)) {
              // a blank line only continues the list if more list content follows
              var j = i + 1;
              while (j < lines.length && /^\s*$/.test(lines[j])) j++;
              if (j >= lines.length) break;
              var nextIndent = lines[j].match(/^(\s*)/)[1].length;
              var nextIsItem = /^\s*([-*+]|\d+[.)])\s+/.test(lines[j]);
              if (nextIndent > baseIndent || (nextIsItem && nextIndent === baseIndent)) {
                if (cur) cur.push('');
                i = j;
                continue;
              }
              break;
            }
            var m2 = l.match(/^(\s*)([-*+]|\d+[.)])\s+(.*)$/);
            var ind = l.match(/^(\s*)/)[1].length;
            if (m2 && m2[1].length === baseIndent) {
              cur = [m2[3]];
              items.push(cur);
              i++;
              continue;
            }
            if (cur && ind > baseIndent) { cur.push(l.slice(Math.min(ind, baseIndent + 2))); i++; continue; }
            if (cur && !m2 && !isBlockStart(l)) { cur.push(l.trim()); i++; continue; }
            break;
          }
          var html = '<' + (ordered ? 'ol' : 'ul') + '>';
          items.forEach(function (buf) {
            // unwrap the item's leading paragraph so short list items stay tight
            var inner = parse(buf).replace(/^<p>([\s\S]*?)<\/p>(\n|$)/, '$1$2');
            html += '<li>' + inner + '</li>';
          });
          out.push(html + '</' + (ordered ? 'ol' : 'ul') + '>');
          continue;
        }

        var para = [];
        while (i < lines.length && !/^\s*$/.test(lines[i]) && !(para.length && isBlockStart(lines[i]))) {
          para.push(lines[i]);
          i++;
        }
        if (para.length) out.push('<p>' + inline(para.join('\n'), ctx).replace(/\n/g, '<br>') + '</p>');
      }
      return out.join('\n');
    }

    return parse(lines);
  }

  // ----------------------------------------------------------- diagrams

  /* Diagrams are rendered by www/diagram/*.js - a small purpose-built SVG renderer
     for the mermaid subset these notes use. It is synchronous and dependency-free,
     so a diagram is already drawn by the time the section appears, and the SVG uses
     CSS custom properties for colour, so it follows a theme change with no redraw. */

  function diagramSvg(src) {
    if (!window.LLDD || !window.LLDD.render) throw new Error('diagram renderer missing');
    var svg = window.LLDD.render(src);
    if (typeof svg !== 'string' || svg.indexOf('<svg') !== 0) throw new Error('bad svg');
    return svg;
  }

  /* A diagram's identity is its source text, so the visited mark survives a rebuild
     and follows the diagram if it moves to another note. */
  function diagKey(src) {
    var h = 5381, i;
    for (i = 0; i < src.length; i++) h = ((h * 33) ^ src.charCodeAt(i)) >>> 0;
    return h.toString(36);
  }

  function diagramBlock(src) {
    var body, state_ = '1';
    try {
      body = diagramSvg(src);
    } catch (e) {
      // an unsupported or malformed diagram degrades to its source, never to nothing
      body = '<pre class="dsrc">' + esc(src) + '</pre>';
      state_ = 'src';
    }
    var key = diagKey(src);
    var seen = !!state.diag[key];
    return '<div class="diagram' + (seen ? ' seen' : '') + '" data-src="' + esc(src) + '"'
      + ' data-dkey="' + key + '" data-drawn="' + state_ + '">'
      + '<div class="scroll">' + body + '</div>'
      + '<div class="dbar">'
      + '<button data-dseen class="seenbtn">' + (seen ? '&#10003; got it' : 'got it') + '</button>'
      + '<span class="spacer"></span>'
      + '<button data-dfull>full screen</button>'
      + '<button data-src-toggle>source</button></div></div>';
  }

  /* Full-screen diagram viewer. An in-page overlay rather than the Fullscreen API:
     the API needs a WebChromeClient hook that the APK's WebView does not install, and
     an overlay behaves identically across the PWA, the APK and the single file. */
  function openFull(src) {
    closeFull();
    var body;
    try {
      body = diagramSvg(src);
    } catch (e) {
      body = '<pre class="dsrc">' + esc(src) + '</pre>';
    }
    var el = document.createElement('div');
    el.className = 'dfull';
    el.innerHTML =
      '<div class="top">'
      + '<span class="hint">pinch or use + to zoom &middot; drag to pan</span>'
      + '<span class="spacer"></span>'
      + '<button class="btn" data-fzoom="-">&minus;</button>'
      + '<button class="btn" data-fzoom="+">+</button>'
      + '<button class="btn" data-ffit>fit</button>'
      + '<button class="btn primary" data-fclose>Close</button>'
      + '</div><div class="body">' + body + '</div>';
    document.body.appendChild(el);
    document.body.classList.add('locked');
  }

  function closeFull() {
    var el = $('.dfull');
    if (el) el.remove();
    document.body.classList.remove('locked');
  }

  function fullZoom(dir) {
    var el = $('.dfull');
    if (!el) return;
    var svg = $('svg', el);
    var host = $('.body', el);
    if (!svg || !host) return;
    var natural = parseFloat(svg.getAttribute('width')) || 600;
    var fit = Math.min(1, Math.max(0.2, (host.clientWidth - 24) / natural));
    if (dir === 'fit') {
      el.dataset.scale = '';
      svg.style.maxWidth = '';
      svg.style.width = '';
      return;
    }
    var cur = parseFloat(el.dataset.scale || String(fit));
    var next = clamp(cur + (dir === '+' ? 0.3 : -0.3), Math.min(0.4, fit), 4);
    el.dataset.scale = next;
    svg.style.maxWidth = 'none';
    svg.style.width = (natural * next) + 'px';
    svg.style.height = 'auto';
  }

  /** Re-render one diagram element in place (used by the source toggle). */
  function drawDiagram(el) {
    var host = $('.scroll', el);
    if (!host) return;
    try {
      host.innerHTML = diagramSvg(el.dataset.src);
      el.dataset.drawn = '1';
    } catch (e) {
      host.innerHTML = '<pre class="dsrc">' + esc(el.dataset.src) + '</pre>';
      el.dataset.drawn = 'src';
    }
    el.dataset.scale = '1';
    var svg = $('svg', host);
    if (svg) svg.style.width = '';
  }

  // ------------------------------------------------------------- rendering

  var app = $('#app');
  var scrollSaver = null;

  function setNav(active) {
    $$('.tabbar button').forEach(function (b) {
      var on = b.dataset.nav === active;
      b.classList.toggle('on', on);
      if (on) b.setAttribute('aria-current', 'page');
      else b.removeAttribute('aria-current');
    });
    document.body.classList.toggle('no-nav', !active);
    $('.tabbar').style.display = active ? '' : 'none';
  }

  function icon(name) {
    var paths = {
      back: '<path d="M15 18l-6-6 6-6"/>',
      home: '<path d="M3 11l9-8 9 8"/><path d="M5 10v10h14V10"/>',
      search: '<circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/>',
      book: '<path d="M4 5.5A2.5 2.5 0 016.5 3H19v15H6.5A2.5 2.5 0 004 20.5z"/><path d="M4 15.5h15"/>',
      layers: '<path d="M12 3l9 5-9 5-9-5 9-5z"/><path d="M3 13l9 5 9-5"/>',
      cards: '<rect x="3" y="6" width="14" height="12" rx="2"/><path d="M8 3h11a2 2 0 012 2v11"/>',
      list: '<path d="M4 6h16M4 12h16M4 18h11"/>',
      cog: '<circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M5 5l2 2M17 17l2 2M19 5l-2 2M7 17l-2 2"/>',
      star: '<path d="M12 3l2.6 5.6 6 .8-4.4 4.2 1.1 6-5.3-2.9-5.3 2.9 1.1-6L3.4 9.4l6-.8z"/>',
      check: '<path d="M20 6L9 17l-5-5"/>',
      x: '<path d="M18 6L6 18M6 6l12 12"/>',
      flame: '<path d="M12 3s5 4.2 5 8.6a5 5 0 01-10 0C7 9.4 9 7.6 9 7.6s.6 1.8 1.7 2.4C10.4 7.4 12 3 12 3z"/>'
        + '<path d="M12 21a6.5 6.5 0 006.5-6.5"/>'
    };
    return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" '
      + 'stroke-linecap="round" stroke-linejoin="round">' + (paths[name] || '') + '</svg>';
  }

  function ring(pct, size) {
    var r = 16, c = 2 * Math.PI * r;
    return '<svg class="ring" viewBox="0 0 40 40" width="' + size + '" height="' + size + '">'
      + '<circle cx="20" cy="20" r="' + r + '" fill="none" stroke="var(--surface-3)" stroke-width="4"/>'
      + '<circle cx="20" cy="20" r="' + r + '" fill="none" stroke="var(--accent)" stroke-width="4"'
      + ' stroke-linecap="round" stroke-dasharray="' + c + '"'
      + ' stroke-dashoffset="' + (c * (1 - pct)) + '" transform="rotate(-90 20 20)"/>'
      + '<text x="20" y="24" text-anchor="middle" font-size="12" font-weight="700" fill="currentColor">'
      + Math.round(pct * 100) + '</text></svg>';
  }

  function bar(pct) { return '<div class="bar"><i style="width:' + clamp(pct * 100, 0, 100) + '%"></i></div>'; }

  // ---------------------------------------------------------------- views

  /* Home is a fork, not a list. The two tracks are different skills that happen
     to share a folder - LLD is classes and code, HLD is boxes and tradeoffs -
     and mixing them into one scroll made it hard to tell which one you were
     neglecting. Each tile owns its own progress. */

  function lldDocKeys() {
    var keys = [];
    C.problems.forEach(function (p) {
      if (p.track && p.track !== 'LLD') return;
      p.docs.forEach(function (d) {
        if (d.key !== 'hld') keys.push(docKey('p', p.id, d.key));
      });
    });
    return keys;
  }

  /* The AI track is its own content root - topic folders plus its reference docs. */
  function aiDocKeys() {
    var keys = [];
    C.problems.forEach(function (p) {
      if (p.track !== 'AI') return;
      p.docs.forEach(function (d) { keys.push(docKey('p', p.id, d.key)); });
    });
    C.refs.forEach(function (r) {
      if (r.group === 'AI' || r.group === 'AI rounds') keys.push(docKey('r', r.id));
    });
    return keys;
  }

  function hldDocKeys() {
    var keys = [];
    C.problems.forEach(function (p) {
      if (p.track && p.track !== 'LLD') return;
      p.docs.forEach(function (d) {
        if (d.key === 'hld') keys.push(docKey('p', p.id, d.key));
      });
    });
    C.refs.forEach(function (r) {
      if (r.group === 'HLD' || r.group === 'HLD rounds') keys.push(docKey('r', r.id));
    });
    return keys;
  }

  function doneRatio(keys) {
    if (!keys.length) return 0;
    var n = keys.filter(function (k) { return state.docs[k] && state.docs[k].done; }).length;
    return n / keys.length;
  }

  function lldProblems() {
    return C.problems.filter(function (p) { return !p.track || p.track === 'LLD'; });
  }
  /* AI folders 01-14 are concept topics, 15+ are design scenarios. Splitting
     them keeps one 44-card list from becoming an undifferentiated scroll. */
  function aiProblems(kind) {
    return C.problems.filter(function (p) {
      return p.track === 'AI' && (!kind || (p.kind || 'topic') === kind);
    });
  }

  /* The list you are actually reading through. C.problems holds all three
     tracks end to end, so walking it blindly ran the last AI scenario
     straight into LLD problem 1. */
  function siblings(p) {
    var tr = p.track || 'LLD', kd = p.kind || 'topic';
    return C.problems.filter(function (x) {
      return (x.track || 'LLD') === tr && (x.kind || 'topic') === kd;
    });
  }

  function unitName(p) {
    if ((p.track || 'LLD') !== 'AI') return 'Problem';
    return (p.kind || 'topic') === 'design' ? 'Scenario' : 'Topic';
  }

  /* "Scenario 7 of 30" beats "Problem 22": the folder number alone tells you
     nothing about how much of the track is left. */
  function posLabel(p) {
    var sib = siblings(p), i = sib.indexOf(p);
    if (i < 0) return unitName(p) + ' ' + p.num;
    return unitName(p) + ' ' + (i + 1) + ' of ' + sib.length;
  }

  /* Long list views were one unbroken scroll, so you lost track of which
     group you were in. Each group is now a native <details> - keyboard and
     screen-reader friendly for free - and the open/closed choice is
     remembered per section. */
  function sect(key, title, meta, body) {
    if (!body) return '';
    var shut = state.open && state.open[key] === 0;
    return '<details class="sect" data-sect="' + key + '"' + (shut ? '' : ' open') + '>'
      + '<summary><span class="sect-t">' + title + '</span>'
      + (meta ? '<span class="sect-n">' + meta + '</span>' : '') + '</summary>'
      + '<div class="sect-body">' + body + '</div></details>';
  }

  function setSect(key, isOpen) {
    if (!state.open) state.open = {};
    if (isOpen) delete state.open[key]; else state.open[key] = 0;
    save();
  }

  /* Jumping between tracks used to mean going back to Home first. */
  function trackChips(active) {
    return '<div class="chips" role="tablist" aria-label="Track">'
      + ['LLD', 'HLD', 'AI'].map(function (t) {
          var on = t.toLowerCase() === active;
          return '<button class="chip' + (on ? ' on' : '') + '" role="tab"'
            + ' aria-selected="' + (on ? 'true' : 'false') + '"'
            + ' data-go="#/t/' + t.toLowerCase() + '">' + t + '</button>';
        }).join('')
      + '</div>';
  }

  function trackMocks(track) { return C.mocks.filter(function (m) { return m.track === track; }); }

  function trackTile(track, blurb, keys) {
    var ms = trackMocks(track);
    var read = doneRatio(keys);
    var runs = ms.filter(function (m) { return mockStat(m.id).runs; }).length;
    return '<button class="track" data-go="#/t/' + track.toLowerCase() + '">'
      + '<div class="track-top"><h3>' + track + '</h3>'
      + '<span class="track-pct">' + Math.round(read * 100) + '%</span></div>'
      + '<p>' + blurb + '</p>'
      + bar(read)
      + '<div class="track-meta">' + keys.length + ' sections &middot; ' + ms.length + ' mocks'
      + (runs ? ' &middot; ' + runs + ' attempted' : '') + '</div>'
      + '</button>';
  }

  /* ------------------------------------------------------------- widgets
     Everything below reads state the app already keeps and never showed. The
     most valuable of it is mock.missed - up to 40 checkpoints you failed to
     mention, banked on every run since the feature shipped, and displayed
     nowhere. */

  function newAndDue() {
    var fresh = 0, due = 0, now = Date.now();
    C.decks.forEach(function (d) {
      d.cards.forEach(function (c) {
        var st = cardState(c.id);
        if (st.box < 0) fresh++;
        else if (st.due <= now) due++;
      });
    });
    return { fresh: fresh, due: due };
  }

  /* The checkpoints you missed, newest run first. One per round, so a single
     bad round cannot fill the list. */
  function weakSpots(limit) {
    var out = [];
    C.mocks.forEach(function (m) {
      var st = state.mock[m.id];
      if (!st || !st.runs || !st.missed || !st.missed.length) return;
      out.push({ when: st.last || 0, round: m.title, track: m.track,
                 id: m.id, n: st.missed.length, sample: st.missed[0] });
    });
    out.sort(function (a, b) { return b.n - a.n || b.when - a.when; });
    return out.slice(0, limit || 5);
  }

  /* Docs opened recently, from the timestamp viewDoc already writes. */
  function recentDocs(limit) {
    var rows = [];
    Object.keys(state.docs).forEach(function (k) {
      var st = state.docs[k];
      if (!st || !st.t) return;
      var bits = k.split(':');
      var item = bits[0] === 'p' ? problem(bits[1]) : ref(bits[1]);
      if (!item) return;
      rows.push({
        t: st.t, done: !!st.done, p: st.p || 0,
        title: item.title,
        sub: bits[0] === 'p' ? (docOf(item, bits[2]) || {}).label : (item.mins + ' min read'),
        route: bits[0] === 'p' ? '#/p/' + bits[1] + '/' + bits[2] : '#/r/' + bits[1]
      });
    });
    rows.sort(function (a, b) { return b.t - a.t; });
    return rows.slice(0, limit || 4);
  }

  function todayWidget(lld, hld, ai) {
    var s = streakInfo();
    var nd = newAndDue();

    /* 'ai' was the hardcoded fallback here regardless of whether a countdown
       said AI was a long shot - so a brand-new user with 5 days left would
       see "Run your first mock" next to a recommendation to start the one
       track the countdown, on the same screen, says to write off. Only the
       untouched default gets second-guessed; once lastPath is set by an
       actual visit to a path (see nextStep's caller), that choice is final -
       someone deliberately working the AI path does not want to be redirected
       just because it is also the hard one. */
    var lp = state.lastPath;
    if (!PATHS[lp]) {
      lp = 'ai';
      var triage = countdownTriage(lld, hld, ai);
      if (triage.status === 'ok') {
        var aiIsLongShot = triage.longShot.filter(function (x) { return x.n === 'AI'; }).length > 0;
        if (aiIsLongShot && triage.doable.length) lp = triage.doable[0].n.toLowerCase();
      }
    }
    var nx = nextStep(lp);
    var lastMock = C.mocks.reduce(function (a, m) {
      var st = state.mock[m.id];
      return Math.max(a, (st && st.last) || 0);
    }, 0);
    var daysSinceMock = lastMock ? Math.floor((Date.now() - lastMock) / 86400000) : null;

    var jobs = [];
    if (nd.due) jobs.push({ t: nd.due + ' card' + (nd.due === 1 ? '' : 's') + ' due',
                            s: 'scheduled for today', go: '#/revise' });
    else if (nd.fresh) jobs.push({ t: 'Start a deck', s: nd.fresh + ' cards never seen',
                                   go: '#/revise' });
    if (nx) jobs.push({ t: nx.label, s: nx.sub + ' \u00b7 ' + PATH_LABEL[lp] + ' path',
                        go: nx.route });
    if (daysSinceMock === null) jobs.push({ t: 'Run your first mock',
                                            s: 'timed, out loud', go: '#/mock' });
    else if (daysSinceMock >= 7) jobs.push({ t: 'A mock round',
                                             s: 'last one ' + daysSinceMock + ' days ago',
                                             go: '#/mock' });

    return '<div class="hero today">'
      + '<div class="flamerow">'
      + '<div class="flame' + (s.met ? ' lit' : '') + '">' + icon('flame') + '</div>'
      + '<div class="flametext"><div class="big">Today</div>'
      + '<div class="label">' + (s.met
          ? 'done \u2014 ' + s.cur + ' day' + (s.cur === 1 ? '' : 's') + ' running'
          : s.n + ' of ' + s.goal + ' toward the goal') + '</div></div>'
      + '<div class="best"><b>' + s.cur + '</b><span>streak</span></div></div>'
      + bar(s.goal ? Math.min(1, s.n / s.goal) : 0)
      + '<div class="todo">' + jobs.slice(0, 3).map(function (j) {
          return '<button class="todo-row" data-go="' + j.go + '">'
            + '<span class="dot-lg"></span>'
            + '<span class="tt">' + esc(j.t) + '<em>' + esc(j.s) + '</em></span>'
            + '<span class="chev">&#8250;</span></button>';
        }).join('') + '</div>'
      + '</div>';
  }

  function weakWidget() {
    var all = weakSpots(1000);
    if (!all.length) return '';
    var top = all.slice(0, 4);

    /* The itemized list below is capped to the 4 worst rounds, which can hide
       that one whole track is the real problem - a round-by-round view and a
       track-by-track view answer different questions ("what do I retry" vs
       "where do I focus"), so show both rather than picking one. */
    var byTrack = {};
    all.forEach(function (x) { byTrack[x.track] = (byTrack[x.track] || 0) + x.n; });
    var tracks = Object.keys(byTrack).sort(function (a, b) { return byTrack[b] - byTrack[a]; });
    var tally = tracks.length > 1
      ? '<div class="wgt-tally">' + tracks.map(function (t) {
          return '<b>' + t + '</b> ' + byTrack[t];
        }).join('<span>&middot;</span>') + '</div>'
      : '';

    return '<div class="wgt"><h3>Weak spots</h3>'
      + '<p class="wgt-note">Checkpoints you did not mention, from your last run of each round.</p>'
      + tally
      + top.map(function (x) {
          return '<button class="wrow" data-go="#/mock/' + x.id + '">'
            + '<span class="wn">' + x.n + '</span>'
            + '<span class="wt">' + esc(x.round) + '<em>' + esc(x.sample) + '</em></span>'
            + '</button>';
        }).join('')
      + '</div>';
  }

  function recentWidget() {
    var r = recentDocs(4);
    if (r.length < 2) return '';
    return '<div class="wgt"><h3>Recently open</h3>'
      + r.map(function (x) {
          return '<button class="wrow" data-go="' + x.route + '">'
            + '<span class="wn' + (x.done ? ' ok' : '') + '">'
            + (x.done ? '&#10003;' : Math.round(x.p * 100) + '%') + '</span>'
            + '<span class="wt">' + esc(x.title) + '<em>' + esc(x.sub || '') + '</em></span>'
            + '</button>';
        }).join('')
      + '</div>';
  }

  /* Same "local midnight, not UTC" rule as today() - new Date('YYYY-MM-DD') parses
     as UTC midnight, which would shift the day boundary by the timezone offset and
     make "3 days left" wrong by one near midnight, exactly the today() bug above. */
  function parseLocalDate(dstr) {
    var q = dstr.split('-');
    return new Date(+q[0], +q[1] - 1, +q[2]);
  }

  /* The shared read on "where do things stand against the date" - todayWidget
     needs the doable/longShot split too (to stop recommending a track the
     countdown itself says to write off), so this is pulled out rather than
     computed twice. Pure: no rendering, just the numbers and the split. */
  function countdownTriage(lld, hld, ai) {
    var dstr = state.settings.interviewDate;
    if (!dstr) return { status: 'unset' };

    var target = parseLocalDate(dstr);
    var now = new Date();
    var startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    var days = Math.round((target - startOfToday) / 86400000);
    if (days < 0) return { status: 'passed', dstr: dstr };

    var tracks = [{ n: 'LLD', k: lld }, { n: 'HLD', k: hld }, { n: 'AI', k: ai }];
    tracks.forEach(function (t) {
      t.left = Math.max(0, Math.round((1 - doneRatio(t.k)) * t.k.length));
      t.pace = (days > 0 && t.left > 0) ? Math.ceil(t.left / days) : 0;
    });
    var remaining = tracks.filter(function (t) { return t.left > 0; });

    if (days === 0) return { status: 'today', days: 0, remaining: remaining };
    if (!remaining.length) return { status: 'done', days: days };

    /* One blended "sections/day to finish everything" number is honest and
       useless the moment the tracks are wildly uneven in size - it reads as a
       single achievable target when really one track is impossible regardless
       of the other two. A track needing more than 3x the easiest remaining
       track's pace is not happening alongside the rest in the time left, so
       split it out rather than let it drag the headline number into fantasy.
       The 3x line is relative to the other tracks, not a guessed personal
       capacity - there is no "sections per day a person can do" constant to
       reach for here, only what the three tracks say about each other. */
    var minPace = remaining.reduce(function (m, t) { return Math.min(m, t.pace); }, Infinity);
    var longShot = remaining.filter(function (t) { return t.pace > minPace * 3; });
    var doable = remaining.filter(function (t) { return t.pace <= minPace * 3; })
      .sort(function (a, b) { return a.pace - b.pace; });

    return { status: 'ok', days: days, remaining: remaining, doable: doable, longShot: longShot };
  }

  function countdownWidget(lld, hld, ai) {
    var t = countdownTriage(lld, hld, ai);

    if (t.status === 'unset') {
      return '<button class="wgt wgt-cta" data-settings>'
        + '<h3>Set your interview date</h3>'
        + '<p class="wgt-note">Get a days-left countdown and the pace you need to finish, in Settings.</p>'
        + '</button>';
    }
    if (t.status === 'passed') {
      return '<div class="wgt"><h3>Interview date has passed</h3>'
        + '<p class="wgt-note">' + esc(t.dstr) + ' &middot; update it in Settings when you have a new one.</p></div>';
    }
    if (t.status === 'today') {
      var todayLeft = t.remaining.reduce(function (s, x) { return s + x.left; }, 0);
      return '<div class="hero mini countdown"><div class="label">Today is the day</div>'
        + '<div class="big">' + (todayLeft ? todayLeft + ' sections left' : 'Everything is covered') + '</div>'
        + '</div>';
    }
    if (t.status === 'done') {
      return '<div class="hero mini countdown">'
        + '<div class="label">' + t.days + (t.days === 1 ? ' day' : ' days') + ' to go</div>'
        + '<div class="big">Everything is covered<span class="of"> &middot; keep the mocks up</span></div>'
        + '</div>';
    }

    var doableLeft = t.doable.reduce(function (s, x) { return s + x.left; }, 0);
    var headlinePace = Math.ceil(doableLeft / t.days);

    var rows = t.remaining.slice().sort(function (a, b) { return a.pace - b.pace; })
      .map(function (x) {
        var isLong = t.longShot.indexOf(x) > -1;
        return '<div class="cd-row' + (isLong ? ' long' : '') + '"><b>' + x.n + '</b>'
          + '<span>' + x.left + ' left &middot; ' + x.pace + '/day</span></div>';
      }).join('');

    var note = '';
    if (t.longShot.length) {
      note = '<p class="wgt-note">' + t.longShot.map(function (x) { return x.n; }).join(' and ')
        + ' ' + (t.longShot.length === 1 ? 'needs' : 'need') + ' '
        + t.longShot.map(function (x) { return x.pace + '/day'; }).join(', ')
        + ' alone — not happening alongside the rest in ' + t.days + ' days. '
        + 'Write it off, or make it the only thing you do.</p>';
    }

    return '<div class="hero mini countdown">'
      + '<div class="label">' + t.days + (t.days === 1 ? ' day' : ' days') + ' to go</div>'
      + '<div class="big">' + headlinePace + ' <span class="of">sections/day to hold '
      + t.doable.map(function (x) { return x.n; }).join(' + ') + '</span></div>'
      + '<div class="cd-rows">' + rows + '</div>'
      + note
      + '</div>';
  }

  function viewHome() {
    setNav('home');
    var lld = lldDocKeys(), hld = hldDocKeys(), ai = aiDocKeys();
    var all = lld.length + hld.length + ai.length;
    var done = Math.round(doneRatio(lld) * lld.length + doneRatio(hld) * hld.length
                          + doneRatio(ai) * ai.length);

    var nd = newAndDue();
    var h = '<div class="view">';

    /* Today first: the old hero led with a coverage number that reads as 0%
       for weeks and gives you nothing to do about it. */
    h += todayWidget(lld, hld, ai);

    if (state.last && byId[state.last.book]) {
      var L = state.last;
      h += '<button class="card" data-go="' + esc(L.route) + '"><div class="card-row">'
        + '<div class="num" style="color:var(--accent)">&#9654;</div>'
        + '<div class="body"><h3>Continue: ' + esc(L.title) + '</h3>'
        + '<div class="meta">' + esc(L.sub) + ' &middot; ' + Math.round((L.p || 0) * 100) + '% in</div>'
        + '</div></div></button>';
    }

    h += countdownWidget(lld, hld, ai);

    var side = weakWidget() + recentWidget();
    if (side) h += '<div class="wgts">' + side + '</div>';

    h += '<h2 class="eyebrow">Pick a track</h2><div class="tracks">';
    h += trackTile('LLD', 'One machine. Classes, responsibilities, patterns, working code.', lld);
    h += trackTile('HLD', 'Many machines. Scale, storage, tradeoffs, failure.', hld);
    h += trackTile('AI', 'LLM systems. RAG, agents, evaluation, cost, failure at scale.', ai);
    h += '</div>';

    h += '<div class="hero mini"><div class="label">Coverage</div>'
      + '<div class="big">' + done + ' <span class="of">of ' + all
      + ' sections revised</span></div>'
      + bar(all ? done / all : 0)
      + '<div class="stats">'
      + '<div class="stat"><b>' + C.mocks.length + '</b><span>mock rounds</span></div>'
      + '<div class="stat"><b>' + nd.due + '</b><span>cards due</span></div>'
      + '<div class="stat"><b>' + nd.fresh + '</b><span>never seen</span></div>'
      + '</div></div>';

    var starred = C.problems.filter(function (p) { return state.star[p.id]; });
    if (starred.length) {
      h += '<h2 class="eyebrow">Starred</h2>';
      starred.forEach(function (p) { h += problemCard(p); });
    }
    h += '</div>';
    render(h, 'Interview Prep', lldProblems().length + ' LLD &middot; '
      + trackMocks('HLD').length + ' HLD &middot; ' + aiProblems().length + ' AI', true);
  }

  // ----------------------------------------------------------------- path

  /* 44 cards and a wish of luck is not a plan. The path is one ordered route
     through the material, so "what do I do next" has exactly one answer. */
  /* Shared by all three paths. rs() takes reference ids, ps() takes problems. */
  function rs(ids) {
    return ids.map(ref).filter(Boolean).map(function (r) { return { kind: 'r', item: r }; });
  }
  function ps(list) {
    return list.map(function (p) { return { kind: 'p', item: p }; });
  }
  function refsIn(group) {
    return rs(C.refs.filter(function (r) { return r.group === group; })
                .map(function (r) { return r.id; }));
  }

  function aiPath() {
    var topics = aiProblems('topic'), design = aiProblems('design');
    return [
      { key: 'orient', title: 'Get oriented',
        blurb: 'How the track works, how to defend a project you built, and how to talk about numbers without getting caught out.',
        items: rs(['ai-README', 'ai-AI-defense-process', 'ai-AI-metrics-discipline']) },
      { key: 'found', title: 'Foundations',
        blurb: 'Serving, retrieval, cost, evaluation. What an AI round opens with, every time.',
        items: ps(topics.slice(0, 7)) },
      { key: 'agents', title: 'Agents and production',
        blurb: 'Orchestration, tool use, and everything that breaks once real traffic shows up.',
        items: ps(topics.slice(7)) },
      { key: 'design', title: 'Design scenarios',
        blurb: 'The whiteboard round. One system per card, the same five parts each time.',
        items: ps(design) },
      { key: 'refs', title: 'Reference and rubrics',
        blurb: 'Architectures worth copying, and the rubric an interviewer is quietly scoring you against.',
        items: rs(['ai-AI-architecture-diagrams', 'ai-AI-scaling-rubric', 'ai-AI-concepts-glossary']) },
      { key: 'bank', title: 'Question bank',
        blurb: 'Sixty-eight questions that do not depend on your projects, plus what to say when you do not know.',
        items: rs(['ai-AI-general-question-bank', 'ai-AI-behavioral-honesty']) },
      { key: 'mocks', title: 'Mock rounds',
        blurb: 'Timed. Say the answer out loud before you open the solution.',
        items: [], mocks: trackMocks('AI') },
      { key: 'final', title: 'The last pass',
        blurb: 'The night before. One sheet, nothing new.',
        items: rs(['ai-AI-fast-revision']) }
    ];
  }

  /* LLD had been one 65-section lump at the end of the AI path, which is not a
     route through anything. It is its own track with its own method. */
  function lldPath() {
    var probs = lldProblems();
    return [
      { key: 'l.orient', title: 'Get oriented',
        blurb: 'How the track works, and the process an interviewer expects you to follow out loud.',
        items: rs(['README', 'LLD-HLD-process']) },
      { key: 'l.method', title: 'The method',
        blurb: 'Finding entities, asking the clarifying questions, and turning nouns into classes. This is the part that transfers to a problem you have never seen.',
        items: rs(['LLD-entity-playbook', 'python-classes-cheatsheet']) },
      { key: 'l.core', title: 'Core problems',
        blurb: 'The eight that come up most. Working code, not diagrams.',
        items: ps(probs.slice(0, 8)) },
      { key: 'l.harder', title: 'Harder problems',
        blurb: 'Where the state machines get real and the patterns start earning their place.',
        items: ps(probs.slice(8)) },
      { key: 'l.mocks', title: 'Mock rounds',
        blurb: 'Timed. Write the class list before you open the solution.',
        items: [], mocks: trackMocks('LLD') },
      { key: 'l.ref', title: 'Patterns reference',
        blurb: 'The pattern names, and the pain each one exists to remove.',
        items: rs(['LLD-patterns', 'LLD-pain-to-pattern']) }
    ];
  }

  /* HLD was absent entirely, despite 15 mock rounds, 15 round guides and the
     per-problem companions living inside the LLD problems. */
  function hldPath() {
    var companions = lldProblems().filter(function (p) {
      return p.docs.some(function (d) { return d.key === 'hld'; });
    });
    return [
      { key: 'h.basics', title: 'New to HLD? Start here',
        blurb: 'The six building blocks, the numbers worth memorising, and the nine steps.',
        items: rs(['HLD-BASICS', 'HLD-revision']) },
      { key: 'h.rounds', title: 'The rounds',
        blurb: 'Fifteen systems, each walked through the same way. Read these before attempting the timed version.',
        items: refsIn('HLD rounds') },
      { key: 'h.comp', title: 'Per-problem companions',
        blurb: 'The HLD side of a problem you have already built at class level. The cheapest way to practise scaling something you understand.',
        items: companions.map(function (p) {
          return { kind: 'p', item: p, only: 'hld' };
        }) },
      { key: 'h.mocks', title: 'Mock rounds',
        blurb: 'Timed. Estimate before you draw.',
        items: [], mocks: trackMocks('HLD') },
      { key: 'h.ref', title: 'Reference',
        blurb: 'The method bank and the deep reference, for when you are stuck mid-round.',
        items: rs(['HLD-method-bank', 'HLD-reference']) }
    ];
  }

  var PATHS = { ai: aiPath, lld: lldPath, hld: hldPath };

  function pathStages(track) {
    var fn = PATHS[track] || PATHS.ai;
    return fn().filter(function (s) {
      return s.items.length || (s.mocks && s.mocks.length);
    });
  }

  /* An item can target one doc of a problem rather than all of them - the HLD
     companions are a single tab inside an otherwise-LLD problem, and counting
     the other four against HLD progress would be wrong. */
  function itemDocs(it) {
    if (it.kind !== 'p') return [docKey('r', it.item.id)];
    return it.item.docs
      .filter(function (d) { return !it.only || d.key === it.only; })
      .map(function (d) { return docKey('p', it.item.id, d.key); });
  }

  function itemRoute(it) {
    if (it.kind !== 'p') return '#/r/' + it.item.id;
    return '#/p/' + it.item.id + '/' + (it.only || it.item.docs[0].key);
  }

  function stageKeys(s) {
    var keys = [];
    s.items.forEach(function (it) { keys.push.apply(keys, itemDocs(it)); });
    return keys;
  }

  function stageStat(s) {
    if (s.mocks) {
      return { done: s.mocks.filter(function (m) { return mockStat(m.id).runs; }).length,
               total: s.mocks.length, unit: 'attempted' };
    }
    var keys = stageKeys(s);
    return { done: keys.filter(function (k) { return state.docs[k] && state.docs[k].done; }).length,
             total: keys.length, unit: 'sections' };
  }

  function isDoneKey(k) { return !!(state.docs[k] && state.docs[k].done); }

  /* The one next thing: the first unread section of the first unfinished
     stage. Nothing is locked - this points, it does not gate. */
  function nextStep(track) {
    var stages = pathStages(track);
    for (var i = 0; i < stages.length; i++) {
      var s = stages[i], j;
      if (s.mocks) {
        for (j = 0; j < s.mocks.length; j++) {
          if (!mockStat(s.mocks[j].id).runs) {
            return { stage: s, label: s.mocks[j].title, sub: 'mock round',
                     route: '#/mock/' + s.mocks[j].id };
          }
        }
        continue;
      }
      for (j = 0; j < s.items.length; j++) {
        var it = s.items[j];
        var keys = itemDocs(it);
        for (var q = 0; q < keys.length; q++) {
          if (!isDoneKey(keys[q])) {
            var sub = it.kind === 'r'
              ? it.item.mins + ' min read'
              : (it.only ? 'HLD' : it.item.docs[q].label);
            return { stage: s, label: it.item.title, sub: sub,
                     route: it.kind === 'r' ? '#/r/' + it.item.id
                                            : '#/p/' + it.item.id + '/'
                                              + (it.only || it.item.docs[q].key) };
          }
        }
      }
    }
    return null;
  }

  function streakBox() {
    var s = streakInfo();
    return '<div class="hero streakbox">'
      + '<div class="flamerow">'
      + '<div class="flame' + (s.met ? ' lit' : '') + '">' + icon('flame') + '</div>'
      + '<div class="flametext">'
      + '<div class="big">' + s.cur + '<span class="unit"> day' + (s.cur === 1 ? '' : 's') + '</span></div>'
      + '<div class="label">'
      + (s.met ? 'today is done' : s.n + ' of ' + s.goal + ' toward today')
      + '</div></div>'
      + '<div class="best"><b>' + s.best + '</b><span>best</span></div>'
      + '</div>'
      + weekStrip()
      + '</div>';
  }

  /* A problem card for a single tab of a problem - the HLD companions. */
  function docCard(it) {
    var d = docOf(it.item, it.only);
    var st = state.docs[docKey('p', it.item.id, it.only)];
    return '<button class="card" data-go="' + itemRoute(it) + '"><div class="card-row">'
      + '<div class="num' + (st && st.done ? ' done' : '') + '">'
      + (st && st.done ? '&#10003;' : it.item.num) + '</div>'
      + '<div class="body"><h3>' + esc(it.item.title) + '</h3>'
      + '<div class="meta">the ' + esc(d.label) + ' side of the same problem</div>'
      + '</div></div></button>';
  }

  function nextCard(nx) {
    if (!nx) return '<div class="empty">Every stage is finished. Go and do the interview.</div>';
    return '<button class="card nextup" data-go="' + esc(nx.route) + '"><div class="card-row">'
      + '<div class="num play">&#9654;</div>'
      + '<div class="body"><h3>' + esc(nx.label) + '</h3>'
      + '<div class="meta">' + esc(nx.sub) + ' &middot; ' + esc(nx.stage.title) + '</div>'
      + '</div></div></button>';
  }

  var PATH_LABEL = { ai: 'AI', lld: 'LLD', hld: 'HLD' };

  function pathChips(active) {
    return '<div class="chips" role="tablist" aria-label="Path">'
      + ['ai', 'lld', 'hld'].map(function (t) {
          var st = pathStages(t).reduce(function (a, s) {
            var q = stageStat(s); a.done += q.done; a.total += q.total; return a;
          }, { done: 0, total: 0 });
          var on = t === active;
          return '<button class="chip' + (on ? ' on' : '') + '" role="tab"'
            + ' aria-selected="' + (on ? 'true' : 'false') + '"'
            + ' data-go="#/path/' + t + '">' + PATH_LABEL[t]
            + '<span class="chip-n">' + Math.round(st.total ? st.done / st.total * 100 : 0)
            + '%</span></button>';
        }).join('')
      + '</div>';
  }

  function viewPath(track) {
    setNav('path');
    track = PATHS[track] ? track : 'ai';
    state.lastPath = track;
    save();
    var stages = pathStages(track);
    var h = '<div class="view">' + streakBox() + pathChips(track)
      + '<h2 class="eyebrow">Next up</h2>' + nextCard(nextStep(track))
      + '<h2 class="eyebrow">The path</h2><ol class="road">';

    var reached = false;
    stages.forEach(function (st, i) {
      var q = stageStat(st);
      var full = q.total && q.done >= q.total;
      var now = !full && !reached;
      if (now) reached = true;
      h += '<li class="stage ' + (full ? 'done' : now ? 'now' : 'todo') + '">'
        + '<div class="node">' + (full ? '&#10003;' : (i + 1)) + '</div>'
        + '<details class="scard"' + (now ? ' open' : '') + '>'
        + '<summary><h3>' + esc(st.title) + '</h3>'
        + '<div class="meta">' + q.done + ' of ' + q.total + ' ' + q.unit
        + (now ? ' &middot; <b>you are here</b>' : '') + '</div>'
        + bar(q.total ? q.done / q.total : 0)
        + '</summary>'
        + '<p class="blurb">' + esc(st.blurb) + '</p>'
        + '<div class="stagelist">'
        + (st.mocks ? st.mocks.map(mockCard).join('')
                    : st.items.map(function (it) {
                        if (it.kind === 'r') return refCard(it.item);
                        return it.only ? docCard(it) : problemCard(it.item);
                      }).join(''))
        + '</div></details></li>';
    });
    h += '</ol></div>';
    render(h, 'Your path', PATH_LABEL[track] + ' &middot; ' + stages.length + ' stages', true);
  }

  function viewTrack(track) {
    setNav('home');
    var isLld = track === 'lld', isAi = track === 'ai';
    var name = isAi ? 'AI' : (isLld ? 'LLD' : 'HLD');
    var h = '<div class="view">' + trackChips(track);

    function cards(list, fn) { return list.map(fn).join(''); }

    if (isAi) {
      var topics = aiProblems('topic'), designs = aiProblems('design');
      h += sect('ai.topics', 'Concept topics', topics.length,
                cards(topics, problemCard));
      if (designs.length) {
        h += sect('ai.design', 'Design scenarios', designs.length,
                  cards(designs, problemCard));
      }
      var aiRefs = C.refs.filter(function (r) { return r.group === 'AI'; });
      h += sect('ai.ref', 'Reference', aiRefs.length, cards(aiRefs, refCard));
    } else if (isLld) {
      var lp = lldProblems();
      h += sect('lld.build', 'Read &amp; build', lp.length, cards(lp, problemCard));
      var lr = C.refs.filter(function (r) { return r.group === 'LLD' || r.group === 'Start here'; });
      h += sect('lld.ref', 'Reference', lr.length, cards(lr, refCard));
    } else {
      var basics = ref('HLD-BASICS');
      if (basics) h += sect('hld.basics', 'New to HLD? Start here', '', refCard(basics));
      var rounds = C.refs.filter(function (r) { return r.group === 'HLD rounds'; });
      h += sect('hld.rounds', 'The rounds', rounds.length, cards(rounds, refCard));
      var comp = lldProblems().filter(function (p) {
        return p.docs.some(function (d) { return d.key === 'hld'; });
      });
      h += sect('hld.comp', 'Per-problem HLD companions', comp.length, cards(comp, function (p) {
        var st = state.docs[docKey('p', p.id, 'hld')];
        return '<button class="card" data-go="#/p/' + p.id + '/hld"><div class="card-row">'
          + '<div class="num' + (st && st.done ? ' done' : '') + '">'
          + (st && st.done ? '&#10003;' : p.num) + '</div>'
          + '<div class="body"><h3>' + esc(p.title) + '</h3>'
          + '<div class="meta">the HLD side of the same problem</div></div></div></button>';
      }));
      var hr = C.refs.filter(function (r) { return r.group === 'HLD' && r.id !== 'HLD-BASICS'; });
      h += sect('hld.ref', 'Reference', hr.length, cards(hr, refCard));
    }

    var ms = trackMocks(name);
    h += sect(track + '.mocks', 'Mock it', ms.length ? ms.length + ' rounds' : '',
              cards(ms, mockCard));
    h += '</div>';
    render(h, name, isAi ? 'LLM systems' : (isLld ? 'one machine' : 'many machines'),
      true, { back: true, backTo: '#/', actions: collapseAllBtn() });
  }

  function collapseAllBtn() {
    return '<button class="iconbtn" data-collapse aria-label="Expand or collapse all sections">'
      + '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9"'
      + ' stroke-linecap="round" stroke-linejoin="round">'
      + '<path d="M8 9l4-4 4 4"/><path d="M16 15l-4 4-4-4"/></svg></button>';
  }

  function refCard(r) {
    var st = state.docs[docKey('r', r.id)];
    return '<button class="card" data-go="#/r/' + r.id + '"><div class="card-row">'
      + '<div class="num' + (st && st.done ? ' done' : '') + '" style="font-size:1rem">'
      + (st && st.done ? '&#10003;' : '&#9776;') + '</div>'
      + '<div class="body"><h3>' + esc(r.title) + '</h3>'
      + '<div class="meta">' + r.mins + ' min read</div></div></div></button>';
  }

  function problemCard(p) {
    var total = p.docs.length;
    var dots = p.docs.map(function (d) {
      var st = state.docs[docKey('p', p.id, d.key)];
      var cls = st && st.done ? 'on' : (st && st.p > 0.08 ? 'half' : '');
      return '<i class="dot ' + cls + '"></i>';
    }).join('');
    var done = p.docs.filter(function (d) {
      var st = state.docs[docKey('p', p.id, d.key)];
      return st && st.done;
    }).length;
    return '<button class="card" data-go="#/p/' + p.id + '/' + p.docs[0].key + '"><div class="card-row">'
      + '<div class="num' + (done === total ? ' done' : '') + '">' + (done === total ? '&#10003;' : p.num) + '</div>'
      + '<div class="body"><h3>' + esc(p.title) + (state.star[p.id] ? ' <span style="color:var(--warn)">&#9733;</span>' : '') + '</h3>'
      + '<div class="meta">' + p.mins + ' min &middot; ' + total + ' sections</div>'
      + (p.tags.length ? '<div class="tags">' + p.tags.map(function (t) {
        return '<span class="tag accent">' + esc(t) + '</span>';
      }).join('') + '</div>' : '')
      + '<div class="dots">' + dots + '</div>'
      + '</div></div></button>';
  }

  /* 51 reference docs in one flat scroll meant hunting. Now: a filter row so
     one track's material is all you see, groups that fold, and on a wide
     screen the cards lay out in columns instead of one tall ribbon. */
  var conceptFilter = 'all';

  /* Regrouped by PURPOSE. The old grouping was by source folder, which is an
     artefact of where files live and told a reader nothing about when to open
     one. Method vs Reference vs Last pass answers "which of these do I need
     right now", which is the only question this tab exists to serve. */
  var CONCEPT_ORDER = ['Method', 'Reference', 'Last pass', 'More'];

  var CONCEPT_PURPOSE = {
    // how to approach a round - read before you practise
    'ai-README': 'Method', 'ai-AI-defense-process': 'Method',
    'ai-AI-metrics-discipline': 'Method', 'ai-AI-scaling-rubric': 'Method',
    'README': 'Method', 'LLD-HLD-process': 'Method',
    'LLD-entity-playbook': 'Method', 'HLD-revision': 'Method',
    'HLD-method-bank': 'Method', 'HLD-BASICS': 'Method',
    // look things up mid-problem
    'ai-AI-architecture-diagrams': 'Reference', 'ai-AI-concepts-glossary': 'Reference',
    'ai-AI-general-question-bank': 'Reference', 'ai-AI-design-scenarios': 'Reference',
    'ai-AI-design-scenarios-2': 'Reference', 'ai-AI-design-scenarios-3': 'Reference',
    'LLD-patterns': 'Reference', 'LLD-pain-to-pattern': 'Reference',
    'python-classes-cheatsheet': 'Reference', 'HLD-reference': 'Reference',
    // the night before
    'ai-AI-fast-revision': 'Last pass', 'ai-AI-behavioral-honesty': 'Last pass'
  };

  /* Mock companions are the SAME documents the Mock tab lists as rounds, and
     INDEX/FORMAT document the authoring file format. Neither belongs in a
     browse-the-material tab; together they were 27 of 51 entries. */
  function isBrowsable(r) {
    if (r.group === 'AI rounds' || r.group === 'HLD rounds') return false;
    if (r.id === 'INDEX' || r.id === 'FORMAT'
        || r.id === 'ai-INDEX' || r.id === 'ai-FORMAT') return false;
    return true;
  }

  function purposeOf(r) { return CONCEPT_PURPOSE[r.id] || 'More'; }

  function conceptGroups() {
    var groups = {};
    C.refs.filter(isBrowsable).forEach(function (r) {
      var g = purposeOf(r);
      (groups[g] = groups[g] || []).push(r);
    });
    var keys = Object.keys(groups).sort(function (a, b) {
      var ia = CONCEPT_ORDER.indexOf(a), ib = CONCEPT_ORDER.indexOf(b);
      return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib);
    });
    return { groups: groups, keys: keys };
  }

  /* Track of a single reference. Groups no longer map one-to-one to tracks now
     that grouping is by purpose, so this reads the id and the source group. */
  function refTrack(r) {
    if (r.id.indexOf('ai-') === 0 || r.group === 'AI') return 'AI';
    if (r.id.indexOf('HLD') === 0 || r.group === 'HLD') return 'HLD';
    return 'LLD';
  }

  function conceptCard(r) {
    var st = state.docs[docKey('r', r.id)];
    return '<button class="card" data-go="#/r/' + r.id + '"><div class="card-row">'
      + '<div class="num' + (st && st.done ? ' done' : '') + '" style="font-size:1rem">'
      + (st && st.done ? '&#10003;' : '&#9776;') + '</div>'
      + '<div class="body"><h3>' + esc(r.title) + '</h3>'
      + '<div class="meta">' + r.mins + ' min read</div>'
      + (st && st.p > 0.08 && !st.done ? bar(st.p) : '')
      + '</div></div></button>';
  }

  function viewConcepts() {
    setNav('concepts');
    var g = conceptGroups();

    var browsable = C.refs.filter(isBrowsable);
    var tracks = ['all'];
    var counts = { all: browsable.length };
    browsable.forEach(function (r) {
      var t = refTrack(r);
      if (tracks.indexOf(t) < 0) tracks.push(t);
      counts[t] = (counts[t] || 0) + 1;
    });
    if (tracks.indexOf(conceptFilter) < 0) conceptFilter = 'all';

    var h = '<div class="view">';
    h += '<div class="chips chips-wrap" role="tablist" aria-label="Filter references">'
      + tracks.map(function (t) {
          var on = t === conceptFilter;
          return '<button class="chip' + (on ? ' on' : '') + '" role="tab"'
            + ' aria-selected="' + (on ? 'true' : 'false') + '"'
            + ' data-cfilter="' + t + '">' + (t === 'all' ? 'All' : t)
            + '<span class="chip-n">' + (counts[t] || 0) + '</span></button>';
        }).join('')
      + '</div>';

    /* A purpose group spans tracks, so filter the CARDS rather than the group. */
    var shown = 0;
    g.keys.forEach(function (k) {
      var list = g.groups[k].filter(function (r) {
        return conceptFilter === 'all' || refTrack(r) === conceptFilter;
      });
      if (!list.length) return;
      shown += list.length;
      h += sect('c.' + k, esc(k), list.length, list.map(conceptCard).join(''));
    });
    if (!shown) h += '<p class="empty">Nothing in this filter.</p>';
    h += '</div>';
    render(h, 'Concepts', browsable.length + ' references', true,
           { actions: collapseAllBtn() });
  }

  // ------------------------------------------------------------- reader

  var currentDoc = null;

  function viewDoc(kind, id, sub, query) {
    var item = kind === 'p' ? problem(id) : ref(id);
    if (!item) return go('#/');
    var d = kind === 'p' ? docOf(item, sub) : { key: '', label: 'Reference', md: item.md };
    var key = docKey(kind, id, kind === 'p' ? d.key : '');
    var toc = [];
    var body = md2html(d.md, { ctx: { kind: kind, id: id }, toc: toc });

    var tabs = '';
    if (kind === 'p') {
      tabs = '<div class="tabs">' + item.docs.map(function (x) {
        var st = state.docs[docKey('p', id, x.key)];
        return '<button class="tab' + (x.key === d.key ? ' on' : '') + '" data-tab="' + x.key + '">'
          + esc(x.label) + (st && st.done ? ' <span class="tick">&#10003;</span>' : '') + '</button>';
      }).join('') + '</div>';
    }

    var st = doc(key);
    var h = tabs + '<div class="view reader"><div class="prose">' + body + '</div>'
      + '<div style="height:70px"></div></div>';

    var title = kind === 'p' ? item.title : item.title;
    var subtitle = kind === 'p' ? (posLabel(item) + ' &middot; ' + d.label) : item.group;
    render(h, esc(title), subtitle, false, {
      back: true,
      actions: '<button class="iconbtn" data-go="#/" aria-label="Home">'
        + icon('home') + '</button>'
        + (kind === 'p'
        ? '<button class="iconbtn' + (state.star[id] ? ' on' : '') + '" data-star aria-label="Star this problem" aria-pressed="'
          + (state.star[id] ? 'true' : 'false') + '">' + icon('star') + '</button>'
        : '')
        + (toc.length ? '<button class="iconbtn" data-toc aria-label="Table of contents">' + icon('list') + '</button>' : '')
    });
    setNav(null);
    document.body.classList.add('reading');

    currentDoc = { kind: kind, id: id, sub: kind === 'p' ? d.key : '', key: key, toc: toc, item: item, docObj: d };

    // reader footer
    var foot = document.createElement('div');
    foot.className = 'readerbar';
    var nav = kind === 'p' ? neighbours(item, d.key) : null;
    foot.innerHTML =
      (nav && nav.prev ? '<button class="btn" data-goto="' + nav.prev.route + '">&#8592; ' + esc(nav.prev.label) + '</button>' : '')
      + '<button class="btn ' + (st.done ? 'ok' : 'primary') + '" data-done>'
      + (st.done ? icon('check') + ' Revised' : 'Mark revised') + '</button>'
      + (nav && nav.next ? '<button class="btn" data-goto="' + nav.next.route + '">' + esc(nav.next.label) + ' &#8594;</button>' : '');
    document.body.appendChild(foot);

    var line = document.createElement('div');
    line.className = 'progressline';
    document.body.appendChild(line);

    /* Explained runs past 3,000 words, so the heading you are under scrolls
       out of sight long before the section ends. Pin it; tapping it opens
       the full contents. */
    var crumb = null, crumbAt = null;
    var heads = $$('.prose h2, .prose h3');
    if (heads.length > 2) {
      crumb = document.createElement('button');
      crumb.className = 'crumb';
      crumb.setAttribute('data-toc', '');
      crumb.setAttribute('aria-label', 'Current section - open contents');
      document.body.appendChild(crumb);
      /* sit directly under whichever bars this view actually has */
      var anchor = $('.tabs') || $('.appbar');
      if (anchor) crumb.style.top = Math.round(anchor.getBoundingClientRect().bottom) + 'px';
    }

    // highlight search terms and jump to the first one
    if (query) {
      highlight($('.prose'), query);
      var first = $('mark.jump');
      if (first) setTimeout(function () { first.scrollIntoView({ block: 'center' }); }, 60);
    } else if (st.p > 0.02 && st.p < 0.98) {
      setTimeout(function () {
        window.scrollTo(0, st.p * (document.body.scrollHeight - window.innerHeight));
      }, 30);
    } else {
      window.scrollTo(0, 0);
    }

    st.t = Date.now();
    state.last = {
      route: location.hash, book: kind + ':' + id, title: title,
      sub: kind === 'p' ? d.label : item.group, p: st.p
    };
    save();

    scrollSaver = function () {
      /* every measurement first, then the writes - mixing them forces a
         layout on each scroll event */
      var max = document.body.scrollHeight - window.innerHeight;
      var p = max > 0 ? clamp(window.scrollY / max, 0, 1) : 1;
      var cur = '';
      if (crumb) {
        for (var hi = 0; hi < heads.length; hi++) {
          if (heads[hi].getBoundingClientRect().top < 96) cur = heads[hi].textContent;
          else break;
        }
        if (cur !== crumbAt) {
          crumbAt = cur;
          crumb.textContent = cur;
          crumb.classList.toggle('on', !!cur);
        }
      }
      line.style.width = (p * 100) + '%';
      st.p = p;
      if (p > 0.94 && !st.done) markDone(true, true);
      if (state.last) state.last.p = p;
      save();
    };
    scrollSaver();
  }

  function neighbours(p, key) {
    var i = p.docs.findIndex(function (d) { return d.key === key; });
    var out = {};
    if (i > 0) out.prev = { route: '#/p/' + p.id + '/' + p.docs[i - 1].key, label: p.docs[i - 1].label };
    if (i < p.docs.length - 1) out.next = { route: '#/p/' + p.id + '/' + p.docs[i + 1].key, label: p.docs[i + 1].label };
    /* Roll over the ends of a problem into its neighbour in the SAME track
       and section, so reading straight through never dumps you in LLD. */
    var sib = siblings(p), si = sib.indexOf(p);
    if (!out.prev && si > 0) {
      var pp = sib[si - 1], pd = pp.docs[pp.docs.length - 1];
      out.prev = { route: '#/p/' + pp.id + '/' + pd.key, label: unitName(pp) + ' ' + pp.num };
    }
    if (!out.next && si > -1 && si < sib.length - 1) {
      var np = sib[si + 1];
      out.next = { route: '#/p/' + np.id + '/' + np.docs[0].key, label: unitName(np) + ' ' + np.num };
    }
    return out;
  }

  function openToc() {
    if (!currentDoc || !currentDoc.toc.length) return;
    sheet('<h4>Sections</h4><div class="toc">' + currentDoc.toc.map(function (x) {
      return '<a href="#' + x.id + '" data-tocjump="' + x.id + '" class="h' + x.lvl + '">' + esc(x.text) + '</a>';
    }).join('') + '</div>');
  }

  /* These keys already worked; nothing ever said so. */
  var KEYS = [
    ['j&nbsp;/&nbsp;k', 'Scroll down / up'],
    ['n&nbsp;/&nbsp;p', 'Next / previous section, rolling into the next problem'],
    ['&rarr;&nbsp;/&nbsp;&larr;', 'The same, on the arrow keys'],
    [']&nbsp;/&nbsp;[', 'Skip a whole problem forward / back'],
    ['m', 'Mark revised'],
    ['t', 'Contents of this page'],
    ['/', 'Search everything'],
    ['Space', 'Flip a flashcard'],
    ['1&nbsp;/&nbsp;2', 'Grade it: again / good'],
    ['Esc', 'Close a sheet or a full-screen diagram'],
    ['?', 'This list']
  ];

  function shortcutSheet() {
    sheet('<h4>Keyboard</h4><div class="keys">'
      + KEYS.map(function (k) {
        return '<div><kbd>' + k[0] + '</kbd><span>' + k[1] + '</span></div>';
      }).join('')
      + '</div>');
  }

  function markDone(val, silent) {
    if (!currentDoc) return;
    var st = doc(currentDoc.key);
    var fresh = val && !st.done;
    st.done = val ? 1 : 0;
    if (fresh) bump();
    save();
    var btn = $('.readerbar [data-done]');
    if (btn) {
      btn.className = 'btn ' + (st.done ? 'ok' : 'primary');
      btn.innerHTML = st.done ? icon('check') + ' Revised' : 'Mark revised';
    }
    if (!silent) toast(st.done ? 'Marked revised' : 'Unmarked');
  }

  function highlight(root, q) {
    var terms = q.toLowerCase().split(/\s+/).filter(function (t) { return t.length > 1; });
    if (!terms.length) return;
    var re = new RegExp('(' + terms.map(function (t) {
      return t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    }).join('|') + ')', 'gi');
    var probe = new RegExp(re.source, 'i');
    var first = true;
    var walk = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, null);
    var nodes = [], n;
    while ((n = walk.nextNode())) if (probe.test(n.nodeValue)) nodes.push(n);
    nodes.forEach(function (node) {
      var span = document.createElement('span');
      span.innerHTML = esc(node.nodeValue).replace(re, function (m) {
        var cls = first ? 'jump' : '';
        first = false;
        return '<mark class="' + cls + '">' + m + '</mark>';
      });
      node.parentNode.replaceChild(span, node);
    });
  }

  // ------------------------------------------------------------- search

  var index = null;
  /* What to index.

     Mermaid blocks are 7% of the corpus and mostly syntax, so indexing them
     raw means "flowchart" returns forty diagram files and every node id
     competes with a real word. But 55% of a mermaid block is quoted LABEL
     text - "Input guard, under 20 ms" - which is prose worth finding. So keep
     the labels, drop the syntax.

     Every other fence stays. A solution doc is entirely one python fence:
     stripping fences wholesale reduced all 46 of them to zero characters and
     made them unsearchable, which is how this comment came to exist. */
  function searchText(md) {
    return md.replace(/```mermaid\n([\s\S]*?)```/g, function (_, body) {
      var labels = body.match(/"[^"]{3,}"/g) || [];
      return ' ' + labels.join(' ').replace(/<br\s*\/?>/g, ' ').replace(/"/g, '') + ' ';
    });
  }

  function headingText(md) {
    var out = [];
    md.replace(/^#{1,4}\s+(.+)$/gm, function (_, t) { out.push(t); return ''; });
    return out.join(' ');
  }

  function indexEntry(title, sub, route, md, group) {
    var body = searchText(md);
    return {
      title: title, sub: sub, route: route, group: group,
      md: body, low: body.toLowerCase(),
      heads: headingText(body).toLowerCase(),
      len: body.length
    };
  }

  function buildIndex() {
    if (index) return index;
    index = [];
    C.problems.forEach(function (p) {
      p.docs.forEach(function (d) {
        index.push(indexEntry(p.title, 'Problem ' + p.num + ' - ' + d.label,
                              '#/p/' + p.id + '/' + d.key, d.md, 'p:' + p.id));
      });
    });
    C.refs.forEach(function (r) {
      index.push(indexEntry(r.title, r.group, '#/r/' + r.id, r.md, 'r:' + r.id));
    });
    MEDIAN_LEN = index.map(function (e) { return e.len; })
      .sort(function (a, b) { return a - b; })[Math.floor(index.length / 2)] || 1;
    return index;
  }

  var MEDIAN_LEN = 1;

  var PER_GROUP = 2;      // sections of one problem allowed on the results page
  var SHOWN = 30;

  function search(q) {
    var idx = buildIndex();
    var terms = q.toLowerCase().split(/\s+/).filter(Boolean);
    if (!terms.length) return { rows: [], total: 0 };

    var hits = [];
    idx.forEach(function (e) {
      var score = 0, spots = [], missing = false;
      terms.forEach(function (t) {
        var at = e.low.indexOf(t), count = 0;
        while (at > -1 && count < 200) {
          if (spots.length < 3) spots.push(at);
          count++;
          at = e.low.indexOf(t, at + t.length);
        }
        if (!count) { missing = true; return; }
        /* Saturating term frequency: the fortieth mention is not worth forty
           times the first, and raw counts let a long rambling document beat a
           short exact one. */
        var tf = count / (count + 2);
        /* Length normalisation against the median document. Without it the
           longest file in the corpus wins nearly every query. */
        var norm = Math.sqrt(MEDIAN_LEN / Math.max(e.len, 400));
        score += tf * norm * 40;
        if (e.title.toLowerCase().indexOf(t) > -1) score += 30;
        if (e.heads.indexOf(t) > -1) score += 12;
      });
      if (missing || score <= 0) return;
      hits.push({
        entry: e, score: score,
        snips: spots.slice(0, 2).map(function (at) { return snippet(e.md, at, terms); })
      });
    });

    hits.sort(function (a, b) { return b.score - a.score; });

    /* Diversity. Five sections of one problem are five near-identical rows that
       push every other problem off the page - the same crowding that generated
       code causes in a code search. Keep the best few per problem and say how
       many more there are. */
    var seen = {}, rows = [];
    hits.forEach(function (r) {
      var g = r.entry.group;
      seen[g] = (seen[g] || 0) + 1;
      if (seen[g] <= PER_GROUP) rows.push(r);
      else if (seen[g] === PER_GROUP + 1) rows[rows.length - 1].more = 0;
      if (seen[g] > PER_GROUP) {
        for (var i = rows.length - 1; i >= 0; i--) {
          if (rows[i].entry.group === g) { rows[i].more = (rows[i].more || 0) + 1; break; }
        }
      }
    });
    return { rows: rows.slice(0, SHOWN), total: hits.length, shown: Math.min(rows.length, SHOWN) };
  }

  function snippet(md, at, terms) {
    var start = Math.max(0, at - 70), end = Math.min(md.length, at + 110);
    var text = md.slice(start, end).replace(/[\n`#>*|]+/g, ' ').replace(/\s{2,}/g, ' ').trim();
    var re = new RegExp('(' + terms.map(function (t) {
      return t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    }).join('|') + ')', 'gi');
    return (start > 0 ? '...' : '') + esc(text).replace(re, '<mark>$1</mark>') + (end < md.length ? '...' : '');
  }

  function viewSearch(q) {
    setNav('search');
    var h = '<div class="view">'
      + '<div class="searchbox">' + icon('search')
      + '<input id="q" type="search" placeholder="Search all notes..." aria-label="Search all notes" '
      + 'autocomplete="off" autocapitalize="off" spellcheck="false" value="' + esc(q || '') + '">'
      + '<button class="iconbtn" data-clear aria-label="Clear search" style="width:28px;height:28px">' + icon('x') + '</button></div>'
      + '<div id="results"></div></div>';
    render(h, 'Search', 'Every problem and reference', true);

    var input = $('#q');
    var box = $('#results');

    function run() {
      var val = input.value.trim();
      if (val.length < 2) {
        box.innerHTML = '<div class="empty">' + icon('search')
          + '<div>Type at least 2 characters.</div>'
          + '<div style="margin-top:6px;font-size:.8rem">Try <b>TOCTOU</b>, <b>strategy</b>, <b>idempotent</b>, <b>sharding</b>.</div></div>';
        return;
      }
      var res = search(val);
      if (!res.rows.length) {
        box.innerHTML = '<div class="empty">No matches for "' + esc(val) + '"</div>';
        return;
      }
      var head = res.total + ' match' + (res.total > 1 ? 'es' : '')
        + (res.total > res.shown ? ' &middot; showing ' + res.shown : '');
      box.innerHTML = '<h2 class="eyebrow">' + head + '</h2>'
        + res.rows.map(function (r) {
          return '<button class="hit" data-go="' + r.entry.route + '?q=' + encodeURIComponent(val) + '">'
            + '<div class="where">' + esc(r.entry.title) + ' &middot; ' + esc(r.entry.sub)
            + (r.more ? '<span class="more">+' + r.more + ' more section'
                        + (r.more > 1 ? 's' : '') + '</span>' : '')
            + '</div>'
            + r.snips.map(function (s) { return '<div class="snip">' + s + '</div>'; }).join('')
            + '</button>';
        }).join('');
    }

    var t;
    input.addEventListener('input', function () { clearTimeout(t); t = setTimeout(run, 120); });
    input.addEventListener('keydown', function (e) { if (e.key === 'Enter') { e.preventDefault(); input.blur(); run(); } });
    $('[data-clear]').addEventListener('click', function () { input.value = ''; input.focus(); run(); });
    run();
    if (!q) setTimeout(function () { input.focus(); }, 120);
  }

  // ---------------------------------------------------------- flashcards

  var BOX_DAYS = [0, 1, 3, 7, 21];

  function cardState(id) { return state.cards[id] || { box: -1, due: 0, n: 0 }; }

  function dueCards(deck) {
    var now = Date.now();
    return deck.cards.filter(function (c) {
      var s = cardState(c.id);
      return s.box < 0 || s.due <= now;
    });
  }

  var reviseFilter = 'all';

  function reviseDecks() {
    return C.decks.filter(function (d) {
      return reviseFilter === 'all' || (d.track || 'LLD') === reviseFilter;
    });
  }

  function viewRevise() {
    setNav('revise');
    var pool = reviseDecks();
    var totalDue = 0, totalNew = 0, learned = 0, total = 0;
    pool.forEach(function (d) {
      d.cards.forEach(function (c) {
        var s = cardState(c.id);
        total++;
        if (s.box < 0) totalNew++;
        else if (s.due <= Date.now()) totalDue++;
        if (s.box >= 3) learned++;
      });
    });

    var h = '<div class="view">'
      + '<div class="hero"><div class="label">Ready now</div>'
      + '<div class="big">' + (totalDue + totalNew) + ' <span style="color:var(--dim);font-weight:600;font-size:.9rem">cards</span></div>'
      + bar(total ? learned / total : 0)
      + '<div class="stats">'
      + '<div class="stat"><b>' + totalNew + '</b><span>new</span></div>'
      + '<div class="stat"><b>' + totalDue + '</b><span>due</span></div>'
      + '<div class="stat"><b>' + learned + '</b><span>learned</span></div>'
      + '</div>';
    if (totalDue + totalNew) {
      h += '<div style="margin-top:12px"><button class="btn primary" style="width:100%" data-go="#/revise/all">Start mixed session</button></div>';
    }
    h += '</div>';

    h += '<div class="chips" role="tablist" aria-label="Filter decks">'
      + ['all', 'AI', 'LLD', 'HLD'].map(function (t) {
          var ds = C.decks.filter(function (d) {
            return t === 'all' || (d.track || 'LLD') === t;
          });
          var nn = ds.reduce(function (a, d) { return a + d.cards.length; }, 0);
          var on = t === reviseFilter;
          return '<button class="chip' + (on ? ' on' : '') + '" role="tab"'
            + ' aria-selected="' + (on ? 'true' : 'false') + '"'
            + ' data-rfilter="' + t + '">' + (t === 'all' ? 'All' : t)
            + '<span class="chip-n">' + nn + '</span></button>';
        }).join('')
      + '</div>';

    h += '<h2 class="eyebrow">Decks</h2><div class="deckwrap">';

    pool.forEach(function (d) {
      var due = dueCards(d).length;
      var known = d.cards.filter(function (c) { return cardState(c.id).box >= 3; }).length;
      h += '<button class="card" data-go="#/revise/' + d.id + '"><div class="deck">'
        + '<div style="color:var(--text)">' + ring(d.cards.length ? known / d.cards.length : 0, 42) + '</div>'
        + '<div class="body"><h3>' + esc(d.title) + '</h3>'
        + '<div class="cnt">' + esc(d.subtitle) + ' &middot; ' + d.cards.length + ' cards</div></div>'
        + (due ? '<span class="pill due">' + due + ' due</span>' : '<span class="pill done">rested</span>')
        + '</div></button>';
    });
    if (!pool.length) h += '<p class="empty">Nothing in this filter.</p>';
    h += '</div></div>';
    render(h, 'Revise', C.decks.reduce(function (a, d) { return a + d.cards.length; }, 0)
           + ' cards over your notes', true);
  }

  var session = null;

  function viewSession(deckId) {
    var pool = [];
    if (deckId === 'all') {
      /* honour the Revise filter - a mixed session started from the AI view
         that deals LLD cards is not what anyone asked for */
      reviseDecks().forEach(function (d) {
        dueCards(d).forEach(function (c) { pool.push({ card: c, deck: d }); });
      });
    } else {
      var deck = C.decks.filter(function (d) { return d.id === deckId; })[0];
      if (!deck) return go('#/revise');
      pool = dueCards(deck).map(function (c) { return { card: c, deck: deck }; });
      if (!pool.length) pool = deck.cards.map(function (c) { return { card: c, deck: deck }; });
    }
    if (!pool.length) { toast('Nothing due - well done'); return go('#/revise'); }

    for (var i = pool.length - 1; i > 0; i--) {           // shuffle
      var j = Math.floor(Math.random() * (i + 1));
      var t = pool[i]; pool[i] = pool[j]; pool[j] = t;
    }
    session = { queue: pool, i: 0, done: 0, again: 0, total: pool.length };
    setNav(null);
    drawCard();
  }

  function drawCard() {
    if (!session || session.i >= session.queue.length) return sessionDone();
    var it = session.queue[session.i];
    var s = cardState(it.card.id);
    var h = '<div class="view">'
      + '<div class="counter"><span>' + (session.i + 1) + ' / ' + session.total + '</span>'
      + bar(session.i / session.total)
      + '<span class="pill ' + (s.box < 0 ? 'new' : 'due') + '">' + (s.box < 0 ? 'new' : 'box ' + (s.box + 1)) + '</span></div>'
      + '<div class="flash"><div class="side">' + esc(it.card.tag || it.deck.title) + '</div>'
      + '<div class="prose">' + md2html(it.card.front) + '</div>'
      + '<div id="ans"></div></div>'
      + '<div class="flashbar" id="fbar"><button class="btn primary" style="flex:1" data-show>Show answer</button></div>'
      + '<div style="height:24px"></div></div>';
    render(h, it.deck.title, 'Recall it before you flip', false, { back: true, backTo: '#/revise' });
    setNav(null);
    window.scrollTo(0, 0);
  }

  function showAnswer() {
    var it = session.queue[session.i];
    $('#ans').innerHTML = '<div class="answer"><div class="side">Answer</div>'
      + '<div class="prose">' + md2html(it.card.back) + '</div></div>';
    $('#fbar').innerHTML =
      '<button class="btn" data-grade="again">Again</button>'
      + '<button class="btn ok" data-grade="good">Got it</button>';
  }

  function grade(kind) {
    var it = session.queue[session.i];
    var s = cardState(it.card.id);
    var box = kind === 'good' ? clamp((s.box < 0 ? 0 : s.box) + 1, 0, 4) : 0;
    state.cards[it.card.id] = {
      box: box,
      due: Date.now() + BOX_DAYS[box] * 86400000,
      n: (s.n || 0) + 1
    };
    bump();
    if (kind === 'good') session.done++; else { session.again++; session.queue.push(it); }
    session.i++;
    save();
    drawCard();
  }

  function sessionDone() {
    var s = session || { done: 0, again: 0 };
    var h = '<div class="view"><div class="hero" style="text-align:center">'
      + '<div style="font-size:2rem">&#127881;</div>'
      + '<div class="big">Session complete</div>'
      + '<div class="label">' + s.done + ' recalled &middot; ' + s.again + ' to repeat</div>'
      + '<div style="margin-top:14px"><button class="btn primary" style="width:100%" data-go="#/revise">Back to decks</button></div>'
      + '</div></div>';
    session = null;
    render(h, 'Done', 'Spaced repetition', true);
    setNav('revise');
  }

  // ------------------------------------------------------------- settings

  function openSettings() {
    var s = state.settings;
    var sizes = ['XS', 'S', 'M', 'L', 'XL'];
    var used = 0;
    try { used = (localStorage.getItem(KEY) || '').length / 1024; } catch (e) { }
    var h = '<h4>Settings</h4>'
      + '<div class="setrow"><div class="lab">Theme<small>Follows the phone by default</small></div>'
      + '<div class="seg" data-seg="theme">'
      + ['system', 'light', 'dark'].map(function (t) {
        return '<button data-val="' + t + '" class="' + (s.theme === t ? 'on' : '') + '">' + t + '</button>';
      }).join('') + '</div></div>'
      + '<div class="setrow"><div class="lab">Text size</div>'
      + '<div class="seg" data-seg="size">'
      + sizes.map(function (t, i) {
        return '<button data-val="' + i + '" class="' + (s.size === i ? 'on' : '') + '">' + t + '</button>';
      }).join('') + '</div></div>'
      + '<div class="setrow"><div class="lab">Daily goal<small>Sections or cards that count as a day</small></div>'
      + '<div class="seg" data-seg="goal">'
      + GOALS.map(function (g) {
        return '<button data-val="' + g + '" class="' + (goalN() === g ? 'on' : '') + '">' + g + '</button>';
      }).join('') + '</div></div>'
      + '<div class="setrow"><div class="lab">Interview date<small>Get a days-left countdown and the pace to finish</small></div>'
      + '<input type="date" id="interviewDate" class="dateinput" value="' + esc(s.interviewDate || '') + '"></div>'
      + '<div class="setrow"><div class="lab">Keep screen on<small>While the app is open</small></div>'
      + '<div class="seg" data-seg="wake">'
      + '<button data-val="0" class="' + (!s.wake ? 'on' : '') + '">off</button>'
      + '<button data-val="1" class="' + (s.wake ? 'on' : '') + '">on</button></div></div>'
      + '<div class="setrow"><div class="lab">Progress<small>'
      + (storageOk
          ? used.toFixed(1) + ' KB saved on this device'
          : 'NOT being saved - this browser is blocking storage')
      + '</small></div>'
      + '<button class="btn danger" data-reset>Reset</button></div>'
      + '<div class="setrow"><div class="lab">Backup<small>Copy your progress out, or restore it</small></div>'
      + '<button class="btn" data-backup>Backup</button></div>'
      + '<div class="setrow"><div class="lab">The book<small>LLM fundamentals through production agents, 35 chapters</small></div>'
      + '<a class="btn" href="book.html" target="_blank" rel="noopener">Read</a></div>'
      + '<div class="setrow"><div class="lab">Keyboard<small>Shortcuts for reading on a laptop</small></div>'
      + '<button class="btn" data-keys>Shortcuts</button></div>'
      + '<div class="setrow"><div class="lab">App cache<small>Refetch the app files if a change did not show up. '
      + 'Your progress is not touched.</small></div>'
      + '<button class="btn" data-refresh>Force refresh</button></div>'
      + (installPrompt ? '<div class="setrow"><div class="lab">Install<small>Add to home screen</small></div>'
        + '<button class="btn primary" data-install>Install app</button></div>' : '')
      + '<div class="setrow"><div class="lab" style="color:var(--dim);font-size:.78rem">'
      + 'Content built ' + esc(C.built || '') + ' &middot; v' + esc(C.version || '') + '<br>'
      + C.problems.length + ' problems, ' + C.refs.length + ' references, '
      + C.decks.reduce(function (n, d) { return n + d.cards.length; }, 0) + ' cards</div></div>';
    var el = sheet(h);
    var di = el.querySelector('#interviewDate');
    if (di) di.addEventListener('change', function () {
      state.settings.interviewDate = di.value || '';
      save();
    });
  }

  // --------------------------------------------------------------- backup

  /* Progress lives in this device's local storage. That survives closing the app and
     restarting the phone, but not clearing browser data or uninstalling - so there is
     a way to carry it out as text. A textarea rather than a file download, because a
     WebView inside an APK cannot start a download. */
  /* The worker is cache-first and matches with ignoreSearch, so a query-string
     bust does nothing while it is in charge. Combined with skipWaiting there is
     a window where a live page holds a new app.js against an old styles.css,
     which looks exactly like the CSS broke. This is the way out of that without
     opening devtools. Caches only - localStorage, and so your progress, stays. */
  function forceRefresh() {
    var jobs = [];
    if (window.caches && caches.keys) {
      jobs.push(caches.keys().then(function (ks) {
        return Promise.all(ks.map(function (k) { return caches.delete(k); }));
      }));
    }
    if (navigator.serviceWorker && navigator.serviceWorker.getRegistrations) {
      jobs.push(navigator.serviceWorker.getRegistrations().then(function (rs) {
        return Promise.all(rs.map(function (r) { return r.unregister(); }));
      }));
    }
    writeNow();                      // flush progress before the page goes away
    toast('Clearing app cache');
    Promise.all(jobs).catch(function () { }).then(function () {
      setTimeout(function () { location.reload(); }, 250);
    });
  }

  /* Every key that carries progress. Listing them rather than assigning the
     whole parsed object keeps a malformed file from introducing fields the app
     never expects - and, more usefully, makes it obvious when a new bit of
     state is added and not backed up. mock and diag were already being dropped
     silently on restore before this list existed. */
  var BACKUP_KEYS = ['settings', 'docs', 'star', 'cards',
                     'open', 'diag', 'mock', 'streak', 'last', 'lastPath'];

  function summarise(st) {
    var done = 0, runs = 0, k;
    for (k in (st.docs || {})) if (st.docs[k] && st.docs[k].done) done++;
    for (k in (st.mock || {})) runs += (st.mock[k] && st.mock[k].runs) || 0;
    return { done: done, cards: Object.keys(st.cards || {}).length, runs: runs };
  }

  function plural(n, word) { return n + ' ' + word + (n === 1 ? '' : 's'); }

  function tally(c) {
    return plural(c.done, 'section') + ', ' + plural(c.cards, 'card')
      + (c.runs ? ', ' + plural(c.runs, 'mock run') : '');
  }

  function backupName() { return 'interview-prep-' + today() + '.json'; }

  /* Progress lives in this device's local storage. That survives closing the app
     and restarting the phone, but not clearing browser data or uninstalling. A
     file is the obvious way out; the textarea stays because a WebView inside an
     APK cannot always start a download, and losing the only escape hatch on the
     platform most likely to need it would be a poor trade. */
  function openBackup() {
    var c = summarise(state);
    sheet('<h4>Backup and restore</h4>'
      + '<div class="bknote">' + tally(c) + ' on this device.</div>'
      + '<div class="flashbar">'
      + '<button class="btn primary" data-bkexport>Download .json</button>'
      + '<button class="btn" data-bkimport>Import file</button>'
      + '</div>'
      + '<details class="bkpaste"><summary>Or copy and paste the text</summary>'
      + '<div class="bknote">Use this if the download is blocked - some in-app '
      + 'browsers do not allow one.</div>'
      + '<textarea class="backup" id="bk" spellcheck="false" autocapitalize="off">'
      + esc(JSON.stringify(state)) + '</textarea>'
      + '<div class="flashbar">'
      + '<button class="btn" data-bkcopy>Copy</button>'
      + '<button class="btn" data-bkrestore>Restore from text</button>'
      + '</div></details>');
  }

  function exportFile() {
    try {
      var blob = new Blob([JSON.stringify(state, null, 2)], { type: 'application/json' });
      var url = URL.createObjectURL(blob);
      var a = document.createElement('a');
      a.href = url;
      a.download = backupName();
      document.body.appendChild(a);
      a.click();
      setTimeout(function () { URL.revokeObjectURL(url); a.remove(); }, 1000);
      toast('Saved ' + backupName());
    } catch (e) {
      toast('Download blocked here - use Copy instead');
    }
  }

  function importFile() {
    var input = document.createElement('input');
    input.type = 'file';
    input.accept = 'application/json,.json';
    input.style.display = 'none';
    document.body.appendChild(input);
    input.addEventListener('change', function () {
      var f = input.files && input.files[0];
      input.remove();
      if (!f) return;
      var r = new FileReader();
      r.onload = function () { confirmRestore(String(r.result), f.name); };
      r.onerror = function () { toast('Could not read that file'); };
      r.readAsText(f);
    });
    input.click();
  }

  function parseBackup(text) {
    var data;
    try { data = JSON.parse(text); } catch (e) { return null; }
    if (!data || typeof data !== 'object' || (!data.docs && !data.cards)) return null;
    return data;
  }

  /* Restoring replaces everything and cannot be undone, so it takes two taps
     and shows you both sides of the trade first. */
  var pending = null;

  function confirmRestore(text, label) {
    var data = parseBackup(text);
    if (!data) { toast('That does not look like a backup'); return; }
    pending = data;
    var mine = summarise(state), theirs = summarise(data);
    sheet('<h4>Replace your progress?</h4>'
      + '<div class="bkdiff">'
      + '<div><span>on this device</span><b>' + tally(mine) + '</b></div>'
      + '<div><span>in ' + esc(label || 'the backup') + '</span><b>' + tally(theirs) + '</b></div>'
      + '</div>'
      + '<div class="bknote">This replaces what is on the device. It cannot be undone.</div>'
      + '<div class="flashbar">'
      + '<button class="btn" data-bkcancel>Cancel</button>'
      + '<button class="btn danger" data-bkconfirm>Replace</button>'
      + '</div>');
  }

  function applyBackup(data) {
    BACKUP_KEYS.forEach(function (k) {
      if (!(k in data)) return;
      if (k === 'settings') { state.settings = Object.assign(state.settings, data.settings || {}); }
      else if (k === 'last') { state.last = data.last || null; }
      else if (k === 'lastPath') { state.lastPath = data.lastPath || null; }
      else { state[k] = data[k] || {}; }
    });
    writeNow();
    closeSheet();
    applyTheme();
    applySize();
    applyWake();
    route();
    toast('Restored ' + tally(summarise(state)));
  }

  function restoreFromText() {
    var box = document.getElementById('bk');
    confirmRestore(box ? box.value : '', 'the pasted text');
  }

  // ---------------------------------------------------------------- sheet

  function sheet(html) {
    closeSheet();
    var back = document.createElement('div');
    back.className = 'sheet-backdrop';
    var el = document.createElement('div');
    el.className = 'sheet';
    el.innerHTML = '<div class="grabber"></div>' + html;
    document.body.appendChild(back);
    document.body.appendChild(el);
    requestAnimationFrame(function () { back.classList.add('in'); el.classList.add('in'); });
    back.addEventListener('click', closeSheet);
    return el;
  }

  function closeSheet() {
    $$('.sheet, .sheet-backdrop').forEach(function (el) {
      el.classList.remove('in');
      setTimeout(function () { el.remove(); }, 200);
    });
  }

  // --------------------------------------------------------------- shell

  function render(html, title, sub, showNav, opts) {
    opts = opts || {};
    $$('.readerbar, .progressline, .crumb').forEach(function (e) { e.remove(); });
    document.body.classList.remove('reading');
    closeSheet();
    scrollSaver = null;
    currentDoc = null;
    var barHtml = '<header class="appbar">'
      + (opts.back ? '<button class="iconbtn" data-back aria-label="Back">' + icon('back') + '</button>' : '')
      + '<h1 tabindex="-1">' + title + (sub ? '<span class="sub">' + sub + '</span>' : '') + '</h1>'
      + (opts.actions || '')
      + (showNav ? '<button class="iconbtn" data-settings aria-label="Settings">' + icon('cog') + '</button>' : '')
      + '</header>';
    app.innerHTML = barHtml + html;
    if (opts.backTo) $('[data-back]').dataset.backTo = opts.backTo;
    if (showNav) window.scrollTo(0, 0);
    // move focus to the new view's heading so a screen reader announces the
    // route change; tabindex=-1 keeps it out of normal tab order otherwise.
    var h1 = $('.appbar h1');
    if (h1) h1.focus({ preventScroll: true });
  }

  // ----------------------------------------------------------- mock mode
  /* A mock runs the way the real round does: the prompt only, a clock, and one
     step at a time. Checkpoints stay hidden until you have said your answer out
     loud - revealing them first turns the exercise into reading. You then tick
     what you actually said, so the score is self-reported and the useful output
     is the "missed" list, not the number. */

  var run = null;          // the live attempt, null when not in one
  var tick;                // clock interval

  function mock(id) { return byId['m:' + id]; }

  /* An LLD mock is generated from a problem folder; an HLD one from a mock file
     that is also shipped as a reference doc. They read from different routes. */
  function docRoute(m) {
    return m.track === 'LLD' ? '#/p/' + m.id + '/problem' : '#/r/' + m.id;
  }

  function mockStat(id) {
    if (!state.mock[id]) {
      state.mock[id] = { best: 0, runs: 0, last: 0, missed: [], lastPct: 0, prev: 0 };
    }
    return state.mock[id];
  }

  function mockMins(m) {
    var t = String(m.time || '').match(/(\d+)/);
    return t ? +t[1] : 0;
  }

  /* Not attempted / below target / solid. Readiness is what you want to see
     when choosing a round; track is a filter on top of it. */
  var MOCK_TARGET = 0.70;

  function readiness(m) {
    var st = mockStat(m.id);
    if (!st.runs) return 'todo';
    return st.best >= MOCK_TARGET ? 'solid' : 'weak';
  }

  function ago(ts) {
    if (!ts) return '';
    var d = Math.floor((Date.now() - ts) / 86400000);
    if (d <= 0) return 'today';
    if (d === 1) return 'yesterday';
    if (d < 30) return d + ' days ago';
    return Math.floor(d / 30) + ' mo ago';
  }

  function mmss(ms) {
    var s = Math.max(0, Math.round(ms / 1000));
    return Math.floor(s / 60) + ':' + ('0' + (s % 60)).slice(-2);
  }

  function totalPoints(m) {
    return m.clarify.length + m.steps.reduce(function (n, s) { return n + s.checkpoints.length; }, 0);
  }

  function scored() {
    return Object.keys(run.ticks).filter(function (k) { return run.ticks[k]; }).length;
  }

  function startClock() {
    clearInterval(tick);
    tick = setInterval(function () {
      var el = $('[data-mclock]');
      if (!el) { clearInterval(tick); return; }
      el.textContent = mmss(Date.now() - run.t0);
    }, 1000);
  }

  // ------------------------------------------------------------ mock list

  var mockFilter = 'all';

  function medianMins() {
    var xs = C.mocks.map(mockMins).filter(Boolean).sort(function (a, b) { return a - b; });
    return xs.length ? xs[Math.floor(xs.length / 2)] : 0;
  }

  function viewMock() {
    setNav('mock');
    clearInterval(tick);
    run = null;

    var done = C.mocks.filter(function (m) { return mockStat(m.id).runs; });
    var avg = done.length
      ? done.reduce(function (n, m) { return n + mockStat(m.id).best; }, 0) / done.length : 0;

    var h = '<div class="view">';
    h += '<div class="hero"><div class="label">Mock interviews</div>'
      + '<div class="big">' + done.length + ' <span style="color:var(--dim);font-weight:600;font-size:.9rem">of '
      + C.mocks.length + ' attempted</span></div>'
      + bar(C.mocks.length ? done.length / C.mocks.length : 0)
      + '<div class="stats">'
      + '<div class="stat"><b>' + Math.round(avg * 100) + '%</b><span>avg best</span></div>'
      + '<div class="stat"><b>' + C.mocks.reduce(function (n, m) { return n + m.checkpoints; }, 0)
      + '</b><span>checkpoints</span></div>'
      + '<div class="stat"><b>' + medianMins() + '</b><span>min, typical</span></div>'
      + '</div></div>';

    /* Track as a filter, readiness as the grouping - which round to attempt
       next is a readiness question, and the old grouping could not answer it. */
    var pool = C.mocks.filter(function (m) {
      return mockFilter === 'all' || m.track === mockFilter;
    });

    h += '<div class="chips" role="tablist" aria-label="Filter rounds">'
      + ['all', 'AI', 'LLD', 'HLD'].map(function (t) {
          var nn = t === 'all' ? C.mocks.length
            : C.mocks.filter(function (m) { return m.track === t; }).length;
          var on = t === mockFilter;
          return '<button class="chip' + (on ? ' on' : '') + '" role="tab"'
            + ' aria-selected="' + (on ? 'true' : 'false') + '"'
            + ' data-mfilter="' + t + '">' + (t === 'all' ? 'All' : t)
            + '<span class="chip-n">' + nn + '</span></button>';
        }).join('')
      + '</div>';

    var nxt = pool.filter(function (m) { return !mockStat(m.id).runs; })[0]
      || pool.slice().sort(function (a, b) {
           return mockStat(a.id).best - mockStat(b.id).best;
         })[0];
    if (nxt) {
      var why = mockStat(nxt.id).runs ? 'your weakest round so far' : 'next unattempted';
      h += '<h2 class="eyebrow">Start here</h2>'
        + '<button class="card nextup" data-go="#/mock/' + nxt.id + '"><div class="card-row">'
        + '<div class="num play">&#9654;</div>'
        + '<div class="body"><h3>' + esc(nxt.title) + '</h3>'
        + '<div class="meta">' + esc(nxt.time || '') + ' &middot; ' + why + '</div>'
        + '</div></div></button>';
    }

    var BUCKETS = [['todo', 'Not attempted'], ['weak', 'Attempted, below target'],
                   ['solid', 'Solid']];
    BUCKETS.forEach(function (b) {
      var list = pool.filter(function (m) { return readiness(m) === b[0]; });
      if (!list.length) return;
      h += sect('mock.' + b[0], b[1], list.length, list.map(mockCard).join(''));
    });
    if (!pool.length) h += '<p class="empty">Nothing in this filter.</p>';
    h += '</div>';
    render(h, 'Mock', C.mocks.length + ' rounds', true, { actions: collapseAllBtn() });
  }

  function mockCard(m) {
    var st = mockStat(m.id);
    var badge = st.runs
      ? Math.round(st.best * 100) + '<span style="font-size:.55em">%</span>'
      : ((String(m.id).match(/(\d+)/) || ['', '?'])[1]);
    var trend = '';
    if (st.runs > 1 && st.lastPct && st.prev) {
      var d = Math.round((st.lastPct - st.prev) * 100);
      trend = ' &middot; <span class="' + (d >= 0 ? 'up' : 'down') + '">'
        + (d >= 0 ? '&#9650;' : '&#9660;') + Math.abs(d) + '</span>';
    }
    return '<button class="card" data-go="#/mock/' + m.id + '"><div class="card-row">'
      + '<div class="num' + (st.best >= MOCK_TARGET ? ' done' : '') + '">' + badge + '</div>'
      + '<div class="body"><h3>' + esc(m.title) + '</h3>'
      + '<div class="meta">' + esc(m.time || m.difficulty) + ' &middot; '
      + m.checkpoints + ' checkpoints'
      + (st.runs ? ' &middot; ' + st.runs + (st.runs > 1 ? ' runs' : ' run')
                   + ', ' + ago(st.last) : '')
      + trend + '</div>'
      + (m.tags.length ? '<div class="tags">' + m.tags.slice(0, 3).map(function (t) {
        return '<span class="tag accent">' + esc(t) + '</span>';
      }).join('') + '</div>' : '')
      + '</div></div></button>';
  }

  // ------------------------------------------------------------- the run

  function viewRun(id) {
    var m = mock(id);
    if (!m) return viewMock();
    setNav(null);
    if (!run || run.id !== id) run = { id: id, stage: 'intro', si: 0, ticks: {}, open: {}, shown: false, t0: 0 };

    if (run.stage === 'intro') return runIntro(m);
    if (run.stage === 'clarify') return runClarify(m);
    if (run.stage === 'done') return runResult(m);
    return runStep(m);
  }

  function clock() {
    return '<span class="mclock" data-mclock>' + mmss(run.t0 ? Date.now() - run.t0 : 0) + '</span>';
  }

  function runIntro(m) {
    var st = mockStat(m.id);
    var h = '<div class="view">';
    h += '<div class="mck-prompt"><h2 class="eyebrow" style="margin-top:0">The interviewer says</h2>'
      + '<div class="prose">' + md2html(m.prompt) + '</div></div>';
    h += '<div class="mck-note">You get ' + esc(m.time) + '. Talk out loud. Nothing is revealed until '
      + 'you have answered &mdash; that is the whole point.'
      + (st.runs ? ' Your best so far is <b>' + Math.round(st.best * 100) + '%</b>.' : '')
      + '</div>';
    if (m.why) h += '<div class="mck-note dim">' + md2html(m.why) + '</div>';
    h += '<button class="mck-go" data-mstart>Start the clock</button>';
    h += '<button class="mck-alt" data-go="' + docRoute(m) + '">Just read it instead</button>';
    h += '</div>';
    render(h, esc(m.title), '', false, { back: true, backTo: '#/mock',
      actions: '<button class="iconbtn" data-go="#/" aria-label="Home">' + icon('home') + '</button>' });
  }

  function runClarify(m) {
    var h = '<div class="view">';
    h += '<div class="mck-bar"><span>Clarify</span>' + clock() + '</div>';
    h += '<div class="mck-note">Ask these before designing anything. Tick the ones you actually asked, '
      + 'then tap to see the answer you should have got.</div>';
    m.clarify.forEach(function (c, i) {
      var k = 'c' + i, on = run.ticks[k], open = run.open[k];
      h += '<div class="mck-item' + (on ? ' on' : '') + '">'
        + '<button class="mck-tick" role="checkbox" aria-checked="' + (on ? 'true' : 'false')
        + '" aria-labelledby="mq-' + k + '" data-mtick="' + k + '">' + (on ? icon('check') : '') + '</button>'
        + '<div class="mck-txt"><button class="mck-q" id="mq-' + k + '" data-mopen="' + k + '">' + md2html(c.q) + '</button>'
        + (open ? '<div class="mck-a">' + md2html(c.a) + '</div>' : '') + '</div></div>';
    });
    h += '<button class="mck-go" data-mnext>Scope is set &rarr; start designing</button>';
    h += '</div>';
    render(h, esc(m.title), 'Clarify', false, { back: true, backTo: '#/mock',
      actions: '<button class="iconbtn" data-go="#/" aria-label="Home">' + icon('home') + '</button>' });
    startClock();
  }

  function runStep(m) {
    var s = m.steps[run.si];
    var h = '<div class="view">';
    h += '<div class="mck-bar"><span>Step ' + (run.si + 1) + ' of ' + m.steps.length + '</span>' + clock() + '</div>';
    h += bar((run.si + 1) / m.steps.length);
    h += '<h2 class="mck-h">' + esc(s.title) + '</h2>';
    if (s.body) h += '<div class="prose mck-body">' + md2html(s.body) + '</div>';

    if (!run.shown) {
      h += '<div class="mck-note">Say your answer out loud <b>first</b>. Only then reveal.</div>';
      h += '<button class="mck-go" data-mshow>I have answered &mdash; show the checkpoints</button>';
    } else {
      h += '<h2 class="eyebrow">Tick what you actually said</h2>';
      s.checkpoints.forEach(function (c, i) {
        var k = 's' + run.si + ':' + i, on = run.ticks[k];
        h += '<div class="mck-item' + (on ? ' on' : '') + '">'
          + '<button class="mck-tick" role="checkbox" aria-checked="' + (on ? 'true' : 'false')
          + '" aria-labelledby="mt-' + k + '" data-mtick="' + k + '">' + (on ? icon('check') : '') + '</button>'
          + '<div class="mck-txt" id="mt-' + k + '">' + md2html(c) + '</div></div>';
      });
      if (s.traps.length) {
        h += '<h2 class="eyebrow">Traps</h2><div class="mck-traps">'
          + s.traps.map(function (t) { return '<div>' + md2html(t) + '</div>'; }).join('') + '</div>';
      }
      if (s.followups.length) {
        h += '<h2 class="eyebrow">If they push</h2><div class="mck-follow">'
          + s.followups.map(function (t) { return '<div>' + md2html(t) + '</div>'; }).join('') + '</div>';
      }
      h += '<button class="mck-go" data-mnext>'
        + (run.si + 1 < m.steps.length ? 'Next step' : 'Finish &amp; score') + '</button>';
    }
    if (run.si > 0) h += '<button class="mck-alt" data-mprev>Back a step</button>';
    h += '</div>';
    render(h, esc(m.title), s.title.split('—')[0].trim(), false, { back: true, backTo: '#/mock' });
    startClock();
  }

  function runResult(m) {
    var total = totalPoints(m), got = scored(), pct = total ? got / total : 0;
    var st = mockStat(m.id);

    var missed = [];
    m.clarify.forEach(function (c, i) { if (!run.ticks['c' + i]) missed.push({ where: 'Clarify', what: c.q }); });
    m.steps.forEach(function (s, si) {
      s.checkpoints.forEach(function (c, i) {
        if (!run.ticks['s' + si + ':' + i]) missed.push({ where: s.title, what: c });
      });
    });

    if (!run.saved) {                       // only bank the first time we land here
      st.runs += 1;
      st.last = Date.now();
      st.prev = st.lastPct;                 // keep the previous score, for a trend
      st.lastPct = pct;                     // best alone cannot show improvement
      st.best = Math.max(st.best, pct);
      st.missed = missed.slice(0, 40).map(function (x) { return x.what; });
      bump();                               // a finished round is a unit of work
      run.saved = true;
      writeNow();
    }

    var verdict = pct >= 0.8 ? 'Strong hire signal' : pct >= 0.65 ? 'Hire signal'
      : pct >= 0.45 ? 'Mixed &mdash; the shape is there, the depth is not' : 'Needs another pass';

    var h = '<div class="view">';
    h += '<div class="hero"><div class="label">' + verdict + '</div>'
      + '<div class="big">' + Math.round(pct * 100) + '<span style="color:var(--dim);font-weight:600;font-size:.9rem">%</span></div>'
      + bar(pct)
      + '<div class="stats">'
      + '<div class="stat"><b>' + got + '/' + total + '</b><span>checkpoints</span></div>'
      + '<div class="stat"><b>' + mmss(Date.now() - run.t0) + '</b><span>taken</span></div>'
      + '<div class="stat"><b>' + Math.round(st.best * 100) + '%</b><span>your best</span></div>'
      + '</div></div>';

    if (missed.length) {
      h += '<h2 class="eyebrow">' + missed.length + ' missed &middot; this is the actual homework</h2>';
      var grouped = {};
      missed.forEach(function (x) { (grouped[x.where] = grouped[x.where] || []).push(x.what); });
      Object.keys(grouped).forEach(function (g) {
        h += '<div class="mck-miss"><h4>' + esc(g) + '</h4>'
          + grouped[g].map(function (t) { return '<div>' + md2html(t) + '</div>'; }).join('') + '</div>';
      });
    } else {
      h += '<div class="mck-note">Nothing missed. Run a harder one.</div>';
    }

    if (m.oneliner) {
      h += '<h2 class="eyebrow">The one line to remember</h2>'
        + '<div class="mck-one">' + md2html(m.oneliner) + '</div>';
    }
    if (m.rubric) h += '<h2 class="eyebrow">Rubric</h2><div class="prose">' + md2html(m.rubric) + '</div>';
    if (m.reference) h += '<h2 class="eyebrow">Reference answer</h2><div class="prose">' + md2html(m.reference) + '</div>';

    h += '<button class="mck-go" data-mretry>Run it again</button>';
    h += '<button class="mck-alt" data-go="' + docRoute(m) + '">Read the full write-up</button>';
    h += '<button class="mck-alt" data-go="#/mock">Back to the list</button>';
    h += '</div>';
    render(h, esc(m.title), 'Result', false, { back: true, backTo: '#/mock' });
    clearInterval(tick);
  }

  // --------------------------------------------------------- mock events

  function mockClick(t) {
    if (!run) return false;
    var m = mock(run.id);

    if (t.closest('[data-mstart]')) {
      run.t0 = Date.now();
      run.stage = m.clarify.length ? 'clarify' : 'step';
      return viewRun(run.id), true;
    }
    var tk = t.closest('[data-mtick]');
    if (tk) {
      var k = tk.dataset.mtick;
      run.ticks[k] = !run.ticks[k];
      return viewRun(run.id), true;
    }
    var op = t.closest('[data-mopen]');
    if (op) {
      var ok = op.dataset.mopen;
      run.open[ok] = !run.open[ok];
      return viewRun(run.id), true;
    }
    if (t.closest('[data-mshow]')) { run.shown = true; return viewRun(run.id), true; }
    if (t.closest('[data-mprev]')) {
      if (run.stage === 'step' && run.si > 0) { run.si -= 1; run.shown = true; }
      return viewRun(run.id), true;
    }
    if (t.closest('[data-mnext]')) {
      if (run.stage === 'clarify') { run.stage = 'step'; run.si = 0; run.shown = false; }
      else if (run.si + 1 < m.steps.length) { run.si += 1; run.shown = false; }
      else run.stage = 'done';
      window.scrollTo(0, 0);
      return viewRun(run.id), true;
    }
    if (t.closest('[data-mretry]')) {
      run = { id: run.id, stage: 'intro', si: 0, ticks: {}, open: {}, shown: false, t0: 0 };
      return viewRun(run.id), true;
    }
    return false;
  }

  // -------------------------------------------------------------- router

  function go(hash) { location.hash = hash; }

  function route() {
    var raw = location.hash.replace(/^#/, '') || '/';
    var qi = raw.indexOf('?');
    var query = null;
    if (qi > -1) {
      var qs = new URLSearchParams(raw.slice(qi + 1));
      query = qs.get('q');
      raw = raw.slice(0, qi);
    }
    var parts = raw.split('/').filter(Boolean);

    if (!parts.length) return viewHome();
    if (parts[0] === 't') {
      /* three tracks now - anything unrecognised falls back to LLD */
      var tr = (parts[1] === 'hld' || parts[1] === 'ai') ? parts[1] : 'lld';
      return viewTrack(tr);
    }
    switch (parts[0]) {
      case 'p':
        return viewDoc('p', parts[1], parts[2] || 'problem', query);
      case 'r':
        return viewDoc('r', parts[1], '', query);
      case 'path':
        return viewPath(parts[1]);
      case 'concepts':
        return viewConcepts();
      case 'revise':
        return parts[1] ? viewSession(parts[1]) : viewRevise();
      case 'mock':
        return parts[1] ? viewRun(parts[1]) : viewMock();
      case 'search':
        return viewSearch(query);
      default:
        return viewHome();
    }
  }

  // ------------------------------------------------------------- events

  /* 'toggle' does not bubble, so this has to capture. */
  document.addEventListener('toggle', function (e) {
    var d = e.target;
    if (d && d.tagName === 'DETAILS' && d.dataset && d.dataset.sect) {
      setSect(d.dataset.sect, d.open);
    }
  }, true);

  document.addEventListener('click', function (e) {
    var t = e.target;

    if (mockClick(t)) return;

    var cf = t.closest('[data-cfilter]');
    if (cf) { conceptFilter = cf.dataset.cfilter; viewConcepts(); return; }

    var coll = t.closest('[data-collapse]');
    if (coll) {
      var ds = $$('details.sect');
      var anyOpen = ds.some(function (d) { return d.open; });
      ds.forEach(function (d) {
        d.open = !anyOpen;
        if (d.dataset.sect) setSect(d.dataset.sect, !anyOpen);
      });
      return;
    }

    var go_ = t.closest('[data-go]');
    if (go_) { go(go_.dataset.go); return; }

    var goto_ = t.closest('[data-goto]');
    if (goto_) { go(goto_.dataset.goto); return; }

    var nav = t.closest('[data-nav]');
    if (nav) {
      var map = { home: '#/', path: '#/path', concepts: '#/concepts',
                  mock: '#/mock', revise: '#/revise', search: '#/search' };
      go(map[nav.dataset.nav]);
      return;
    }

    var tab = t.closest('[data-tab]');
    if (tab && currentDoc) { go('#/p/' + currentDoc.id + '/' + tab.dataset.tab); return; }

    if (t.closest('[data-back]')) {
      var to = t.closest('[data-back]').dataset.backTo;
      if (to) go(to);
      else if (history.length > 1) history.back();
      else go('#/');
      return;
    }

    if (t.closest('[data-settings]')) { openSettings(); return; }

    // scoped to the footer: a bare [data-done] would also catch anything in the page
    // that happens to carry that attribute
    if (currentDoc && t.closest('.readerbar [data-done]')) {
      markDone(!doc(currentDoc.key).done);
      return;
    }

    var star = t.closest('[data-star]');
    if (star && currentDoc) {
      if (state.star[currentDoc.id]) delete state.star[currentDoc.id];
      else state.star[currentDoc.id] = 1;
      star.classList.toggle('on');
      star.setAttribute('aria-pressed', state.star[currentDoc.id] ? 'true' : 'false');
      save();
      toast(state.star[currentDoc.id] ? 'Starred' : 'Unstarred');
      return;
    }

    if (t.closest('[data-toc]') && currentDoc) { openToc(); return; }

    if (t.closest('[data-keys]')) { shortcutSheet(); return; }

    var jump = t.closest('[data-tocjump]');
    if (jump) {
      e.preventDefault();
      closeSheet();
      var el = document.getElementById(jump.dataset.tocjump);
      if (el) setTimeout(function () { el.scrollIntoView({ behavior: 'smooth', block: 'start' }); }, 210);
      return;
    }

    var copy = t.closest('[data-copy]');
    if (copy) {
      var code = $('pre code', copy.parentNode);
      var text = code ? code.textContent : '';
      if (navigator.clipboard) navigator.clipboard.writeText(text).then(function () { toast('Copied'); });
      else toast('Clipboard unavailable');
      copy.textContent = 'Copied';
      setTimeout(function () { copy.textContent = 'Copy'; }, 1200);
      return;
    }

    if (t.closest('[data-fclose]')) { closeFull(); return; }
    var fz = t.closest('[data-fzoom]');
    if (fz) { fullZoom(fz.dataset.fzoom); return; }
    if (t.closest('[data-ffit]')) { fullZoom('fit'); return; }

    var diagram = t.closest('.diagram');
    if (diagram) {
      if (t.closest('[data-dfull]')) { openFull(diagram.dataset.src); return; }

      var seenBtn = t.closest('[data-dseen]');
      if (seenBtn) {
        var dk = diagram.dataset.dkey;
        if (state.diag[dk]) delete state.diag[dk];
        else state.diag[dk] = 1;
        var on = !!state.diag[dk];
        diagram.classList.toggle('seen', on);
        seenBtn.innerHTML = on ? '&#10003; got it' : 'got it';
        save();
        return;
      }
      if (t.closest('[data-src-toggle]')) {
        var host = $('.scroll', diagram);
        if (diagram.dataset.showing === 'src') {
          diagram.dataset.showing = '';
          drawDiagram(diagram);
        } else {
          diagram.dataset.showing = 'src';
          host.innerHTML = '<pre class="dsrc">' + esc(diagram.dataset.src) + '</pre>';
        }
        return;
      }
    }

    if (t.closest('[data-show]')) { showAnswer(); return; }

    var g = t.closest('[data-grade]');
    if (g) { grade(g.dataset.grade); return; }

    var seg = t.closest('[data-seg] button');
    if (seg) {
      var kind = seg.parentNode.dataset.seg;
      var val = seg.dataset.val;
      $$('button', seg.parentNode).forEach(function (b) { b.classList.toggle('on', b === seg); });
      if (kind === 'theme') { state.settings.theme = val; applyTheme(); }
      if (kind === 'size') { state.settings.size = +val; applySize(); }
      if (kind === 'wake') { state.settings.wake = val === '1'; applyWake(); }
      if (kind === 'goal') { state.settings.goal = +val; }
      save();
      return;
    }

    var mf = t.closest('[data-mfilter]');
    if (mf) { mockFilter = mf.dataset.mfilter; viewMock(); return; }

    var rf = t.closest('[data-rfilter]');
    if (rf) { reviseFilter = rf.dataset.rfilter; viewRevise(); return; }

    if (t.closest('[data-backup]')) { openBackup(); return; }

    if (t.closest('[data-bkexport]')) { exportFile(); return; }
    if (t.closest('[data-bkimport]')) { importFile(); return; }
    if (t.closest('[data-bkcancel]')) { pending = null; openBackup(); return; }
    if (t.closest('[data-bkconfirm]')) {
      if (pending) { applyBackup(pending); pending = null; }
      return;
    }

    if (t.closest('[data-refresh]')) { forceRefresh(); return; }

    if (t.closest('[data-bkcopy]')) {
      var box = document.getElementById('bk');
      if (box) {
        box.focus();
        box.select();
        if (navigator.clipboard) navigator.clipboard.writeText(box.value).then(function () { toast('Copied'); });
        else toast('Select all and copy');
      }
      return;
    }

    if (t.closest('[data-bkrestore]')) { restoreFromText(); return; }

    if (t.closest('[data-reset]')) {
      if (confirm('Clear all progress, stars and card scheduling on this device?')) {
        state = { settings: state.settings, docs: {}, star: {}, cards: {}, log: {}, last: null };
        save();
        closeSheet();
        route();
        toast('Progress cleared');
      }
      return;
    }

    if (t.closest('[data-install]') && installPrompt) {
      installPrompt.prompt();
      installPrompt = null;
      closeSheet();
      return;
    }
  });

  window.addEventListener('scroll', function () {
    if (scrollSaver) scrollSaver();
  }, { passive: true });

  /* the bars change height when a phone rotates, so the crumb re-measures */
  window.addEventListener('resize', function () {
    var c = $('.crumb'), a = $('.tabs') || $('.appbar');
    if (c && a) c.style.top = Math.round(a.getBoundingClientRect().bottom) + 'px';
  });

  window.addEventListener('hashchange', function () { closeFull(); route(); });

  // swipe between the doc tabs of a problem
  var tx = 0, ty = 0, tracking = false;
  document.addEventListener('touchstart', function (e) {
    if (!currentDoc || currentDoc.kind !== 'p' || e.touches.length !== 1) { tracking = false; return; }
    if (e.target.closest('pre, .tablewrap, .diagram, .tabs')) { tracking = false; return; }
    tx = e.touches[0].clientX; ty = e.touches[0].clientY; tracking = true;
  }, { passive: true });

  document.addEventListener('touchend', function (e) {
    if (!tracking || !currentDoc) return;
    tracking = false;
    var dx = e.changedTouches[0].clientX - tx;
    var dy = e.changedTouches[0].clientY - ty;
    if (Math.abs(dx) < 70 || Math.abs(dy) > Math.abs(dx) * 0.7) return;
    var p = currentDoc.item;
    var i = p.docs.findIndex(function (d) { return d.key === currentDoc.sub; });
    var next = dx < 0 ? i + 1 : i - 1;
    if (next >= 0 && next < p.docs.length) go('#/p/' + p.id + '/' + p.docs[next].key);
  }, { passive: true });

  document.addEventListener('keydown', function (e) {
    var tag = e.target.tagName;
    /* TEXTAREA matters: the backup sheet is one, and '/' used to yank you
       out of it into search mid-paste. */
    if (tag === 'INPUT' || tag === 'TEXTAREA' || e.target.isContentEditable) return;
    if (e.metaKey || e.ctrlKey || e.altKey) return;

    if (e.key === 'Escape') { closeFull(); closeSheet(); return; }
    if (e.key === '?') { e.preventDefault(); shortcutSheet(); return; }
    if (e.key === '/') { e.preventDefault(); go('#/search'); return; }

    if (session && $('#fbar')) {
      if (e.key === ' ' || e.key === 'Enter') { e.preventDefault(); if ($('[data-show]')) showAnswer(); return; }
      if (e.key === '1' && $('[data-grade]')) { grade('again'); return; }
      if (e.key === '2' && $('[data-grade]')) { grade('good'); return; }
    }
    if (!currentDoc) return;

    if (e.key === 'j' || e.key === 'k') {
      e.preventDefault();
      window.scrollBy({ top: (e.key === 'j' ? 1 : -1) * Math.round(window.innerHeight * 0.85),
                        behavior: 'smooth' });
      return;
    }
    if (e.key === 'm') { markDone(!doc(currentDoc.key).done); return; }
    if (e.key === 't') { openToc(); return; }
    if (currentDoc.kind !== 'p') return;

    /* n/p and the arrows walk sections and then roll on into the next
       problem; ] and [ skip a whole problem at a time. */
    var nb = neighbours(currentDoc.item, currentDoc.sub);
    if ((e.key === 'n' || e.key === 'ArrowRight') && nb.next) { go(nb.next.route); return; }
    if ((e.key === 'p' || e.key === 'ArrowLeft') && nb.prev) { go(nb.prev.route); return; }
    if (e.key === ']' || e.key === '[') {
      var sib = siblings(currentDoc.item), si = sib.indexOf(currentDoc.item);
      var hop = sib[si + (e.key === ']' ? 1 : -1)];
      if (hop) go('#/p/' + hop.id + '/' + hop.docs[0].key);
    }
  });

  // ------------------------------------------------------- theme / setup

  function resolvedTheme() {
    var t = state.settings.theme;
    if (t === 'system') {
      return window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
    }
    return t;
  }

  function applyTheme() {
    var t = resolvedTheme();
    document.documentElement.setAttribute('data-theme', t);
    var meta = $('meta[name="theme-color"]');
    if (meta) meta.setAttribute('content', t === 'dark' ? '#0b0f17' : '#f6f7fb');
  }

  function applySize() {
    var scale = [0.88, 0.94, 1, 1.09, 1.2][clamp(state.settings.size, 0, 4)];
    document.documentElement.style.setProperty('--fs', scale + 'rem');
  }

  var wakeLock = null;
  function applyWake() {
    if (state.settings.wake && 'wakeLock' in navigator) {
      navigator.wakeLock.request('screen').then(function (l) { wakeLock = l; }).catch(function () { });
    } else if (wakeLock) {
      wakeLock.release().catch(function () { });
      wakeLock = null;
    }
  }
  document.addEventListener('visibilitychange', function () {
    if (document.visibilityState === 'visible' && state.settings.wake) applyWake();
  });

  var installPrompt = null;
  window.addEventListener('beforeinstallprompt', function (e) {
    e.preventDefault();
    installPrompt = e;
  });

  window.matchMedia('(prefers-color-scheme: light)').addEventListener('change', function () {
    if (state.settings.theme === 'system') applyTheme();
  });

  applyTheme();
  applySize();
  applyWake();
  route();

  if ('serviceWorker' in navigator && location.protocol.indexOf('http') === 0 && !SINGLE) {
    window.addEventListener('load', function () {
      navigator.serviceWorker.register('sw.js').catch(function () { });
    });
    /* The worker calls skipWaiting(), so a new build claims this page as soon as it
       installs. Reload once when that happens - otherwise the tab keeps rendering the
       version it started with, which looks exactly like "my change did nothing". */
    var reloading = false;
    navigator.serviceWorker.addEventListener('controllerchange', function () {
      if (reloading) return;
      reloading = true;
      location.reload();
    });
  }
})();
