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
      settings: { theme: 'system', size: 2, wake: false },
      docs: {},     // docKey -> {p: scroll 0..1, done: 1|0, t: last opened }
      star: {},     // problem id -> 1
      cards: {},    // card id -> {box, due, n}
      log: {},      // 'YYYY-MM-DD' -> cards graded that day
      diag: {},     // diagram hash -> 1 once you have been through it
      mock: {},     // mock id -> {best, runs, last, missed}
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

  function today() { return new Date().toISOString().slice(0, 10); }

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

  function allDocKeys() {
    var keys = [];
    C.problems.forEach(function (p) {
      p.docs.forEach(function (d) { keys.push(docKey('p', p.id, d.key)); });
    });
    C.refs.forEach(function (r) { keys.push(docKey('r', r.id)); });
    return keys;
  }

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
      search: '<circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/>',
      book: '<path d="M4 5.5A2.5 2.5 0 016.5 3H19v15H6.5A2.5 2.5 0 004 20.5z"/><path d="M4 15.5h15"/>',
      layers: '<path d="M12 3l9 5-9 5-9-5 9-5z"/><path d="M3 13l9 5 9-5"/>',
      cards: '<rect x="3" y="6" width="14" height="12" rx="2"/><path d="M8 3h11a2 2 0 012 2v11"/>',
      list: '<path d="M4 6h16M4 12h16M4 18h11"/>',
      cog: '<circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M5 5l2 2M17 17l2 2M19 5l-2 2M7 17l-2 2"/>',
      star: '<path d="M12 3l2.6 5.6 6 .8-4.4 4.2 1.1 6-5.3-2.9-5.3 2.9 1.1-6L3.4 9.4l6-.8z"/>',
      check: '<path d="M20 6L9 17l-5-5"/>',
      x: '<path d="M18 6L6 18M6 6l12 12"/>'
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
      p.docs.forEach(function (d) {
        if (d.key !== 'hld') keys.push(docKey('p', p.id, d.key));
      });
    });
    return keys;
  }

  function hldDocKeys() {
    var keys = [];
    C.problems.forEach(function (p) {
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

  function viewHome() {
    setNav('home');
    var lld = lldDocKeys(), hld = hldDocKeys();
    var dueCount = C.decks.reduce(function (n, d) { return n + dueCards(d).length; }, 0);
    var all = lld.length + hld.length;
    var done = Math.round(doneRatio(lld) * lld.length + doneRatio(hld) * hld.length);

    var h = '<div class="view">';
    h += '<div class="hero"><div class="label">Coverage</div>'
      + '<div class="big">' + done + ' <span style="color:var(--dim);font-weight:600;font-size:.9rem">of '
      + all + ' sections revised</span></div>'
      + bar(all ? done / all : 0)
      + '<div class="stats">'
      + '<div class="stat"><b>' + C.mocks.length + '</b><span>mocks</span></div>'
      + '<div class="stat"><b>' + dueCount + '</b><span>cards due</span></div>'
      + '<div class="stat"><b>' + (state.log[today()] || 0) + '</b><span>done today</span></div>'
      + '</div></div>';

    if (state.last && byId[state.last.book]) {
      var L = state.last;
      h += '<button class="card" data-go="' + esc(L.route) + '"><div class="card-row">'
        + '<div class="num" style="color:var(--accent)">&#9654;</div>'
        + '<div class="body"><h3>Continue: ' + esc(L.title) + '</h3>'
        + '<div class="meta">' + esc(L.sub) + ' &middot; ' + Math.round((L.p || 0) * 100) + '% in</div>'
        + '</div></div></button>';
    }

    h += '<h2 class="eyebrow">Pick a track</h2>';
    h += trackTile('LLD', 'One machine. Classes, responsibilities, patterns, working code.', lld);
    h += trackTile('HLD', 'Many machines. Scale, storage, tradeoffs, failure.', hld);

    var starred = C.problems.filter(function (p) { return state.star[p.id]; });
    if (starred.length) {
      h += '<h2 class="eyebrow">Starred</h2>';
      starred.forEach(function (p) { h += problemCard(p); });
    }
    h += '</div>';
    render(h, 'System Design', C.problems.length + ' LLD &middot; ' + trackMocks('HLD').length + ' HLD', true);
  }

  function viewTrack(track) {
    setNav('home');
    var isLld = track === 'lld';
    var h = '<div class="view">';

    if (isLld) {
      h += '<h2 class="eyebrow">Read &amp; build</h2>';
      C.problems.forEach(function (p) { h += problemCard(p); });
      h += '<h2 class="eyebrow">Reference</h2>';
      C.refs.filter(function (r) { return r.group === 'LLD' || r.group === 'Start here'; })
        .forEach(function (r) { h += refCard(r); });
    } else {
      var basics = ref('HLD-BASICS');
      if (basics) {
        h += '<h2 class="eyebrow">New to HLD? Start here</h2>' + refCard(basics);
      }
      h += '<h2 class="eyebrow">The 10 rounds</h2>';
      C.refs.filter(function (r) { return r.group === 'HLD rounds'; })
        .forEach(function (r) { h += refCard(r); });
      h += '<h2 class="eyebrow">Per-problem HLD companions</h2>';
      C.problems.forEach(function (p) {
        if (!p.docs.some(function (d) { return d.key === 'hld'; })) return;
        var st = state.docs[docKey('p', p.id, 'hld')];
        h += '<button class="card" data-go="#/p/' + p.id + '/hld"><div class="card-row">'
          + '<div class="num' + (st && st.done ? ' done' : '') + '">' + (st && st.done ? '&#10003;' : p.num) + '</div>'
          + '<div class="body"><h3>' + esc(p.title) + '</h3>'
          + '<div class="meta">the HLD side of the same problem</div></div></div></button>';
      });
      h += '<h2 class="eyebrow">Reference</h2>';
      C.refs.filter(function (r) { return r.group === 'HLD' && r.id !== 'HLD-BASICS'; })
        .forEach(function (r) { h += refCard(r); });
    }

    var ms = trackMocks(isLld ? 'LLD' : 'HLD');
    if (ms.length) {
      h += '<h2 class="eyebrow">Mock it &middot; ' + ms.length + ' rounds</h2>';
      ms.forEach(function (m) { h += mockCard(m); });
    }
    h += '</div>';
    render(h, isLld ? 'LLD' : 'HLD',
      isLld ? 'one machine' : 'many machines', true, { back: true, backTo: '#/' });
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

  function viewConcepts() {
    setNav('concepts');
    var h = '<div class="view">';
    var groups = {};
    C.refs.forEach(function (r) { (groups[r.group] = groups[r.group] || []).push(r); });
    Object.keys(groups).forEach(function (g) {
      h += '<h2 class="eyebrow">' + esc(g) + '</h2>';
      groups[g].forEach(function (r) {
        var st = state.docs[docKey('r', r.id)];
        h += '<button class="card" data-go="#/r/' + r.id + '"><div class="card-row">'
          + '<div class="num' + (st && st.done ? ' done' : '') + '" style="font-size:1rem">'
          + (st && st.done ? '&#10003;' : '&#9776;') + '</div>'
          + '<div class="body"><h3>' + esc(r.title) + '</h3>'
          + '<div class="meta">' + r.mins + ' min read</div>'
          + (st && st.p > 0.08 && !st.done ? bar(st.p) : '')
          + '</div></div></button>';
      });
    });
    h += '</div>';
    render(h, 'Concepts', 'Frameworks & references', true);
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
    var subtitle = kind === 'p' ? ('Problem ' + item.num + ' &middot; ' + d.label) : item.group;
    render(h, esc(title), subtitle, false, {
      back: true,
      actions: (kind === 'p'
        ? '<button class="iconbtn' + (state.star[id] ? ' on' : '') + '" data-star aria-label="Star this problem" aria-pressed="'
          + (state.star[id] ? 'true' : 'false') + '">' + icon('star') + '</button>'
        : '')
        + (toc.length ? '<button class="iconbtn" data-toc aria-label="Table of contents">' + icon('list') + '</button>' : '')
    });
    setNav(null);

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
      var max = document.body.scrollHeight - window.innerHeight;
      var p = max > 0 ? clamp(window.scrollY / max, 0, 1) : 1;
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
    if (!out.next) {
      var pi = C.problems.indexOf(p);
      if (pi > -1 && pi < C.problems.length - 1) {
        var np = C.problems[pi + 1];
        out.next = { route: '#/p/' + np.id + '/' + np.docs[0].key, label: np.title.split(' ')[0] };
      }
    }
    return out;
  }

  function markDone(val, silent) {
    if (!currentDoc) return;
    var st = doc(currentDoc.key);
    st.done = val ? 1 : 0;
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
  function buildIndex() {
    if (index) return index;
    index = [];
    C.problems.forEach(function (p) {
      p.docs.forEach(function (d) {
        index.push({
          title: p.title, sub: 'Problem ' + p.num + ' - ' + d.label,
          route: '#/p/' + p.id + '/' + d.key, md: d.md, low: d.md.toLowerCase()
        });
      });
    });
    C.refs.forEach(function (r) {
      index.push({ title: r.title, sub: r.group, route: '#/r/' + r.id, md: r.md, low: r.md.toLowerCase() });
    });
    return index;
  }

  function search(q) {
    var idx = buildIndex();
    var terms = q.toLowerCase().split(/\s+/).filter(Boolean);
    if (!terms.length) return [];
    var results = [];
    idx.forEach(function (e) {
      var score = 0, spots = [];
      terms.forEach(function (t) {
        var at = e.low.indexOf(t), count = 0;
        while (at > -1 && count < 40) {
          if (spots.length < 3) spots.push(at);
          count++;
          at = e.low.indexOf(t, at + t.length);
        }
        if (count) score += count + (e.title.toLowerCase().indexOf(t) > -1 ? 25 : 0);
        else score -= 1000;
      });
      if (score > 0) {
        results.push({
          entry: e, score: score,
          snips: spots.slice(0, 2).map(function (at) { return snippet(e.md, at, terms); })
        });
      }
    });
    results.sort(function (a, b) { return b.score - a.score; });
    return results.slice(0, 40);
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
      if (!res.length) {
        box.innerHTML = '<div class="empty">No matches for "' + esc(val) + '"</div>';
        return;
      }
      box.innerHTML = '<h2 class="eyebrow">' + res.length + ' result' + (res.length > 1 ? 's' : '') + '</h2>'
        + res.map(function (r) {
          return '<button class="hit" data-go="' + r.entry.route + '?q=' + encodeURIComponent(val) + '">'
            + '<div class="where">' + esc(r.entry.title) + ' &middot; ' + esc(r.entry.sub) + '</div>'
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

  function viewRevise() {
    setNav('revise');
    var totalDue = 0, totalNew = 0, learned = 0, total = 0;
    C.decks.forEach(function (d) {
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
    h += '</div><h2 class="eyebrow">Decks</h2><div class="deckwrap">';

    C.decks.forEach(function (d) {
      var due = dueCards(d).length;
      var known = d.cards.filter(function (c) { return cardState(c.id).box >= 3; }).length;
      h += '<button class="card" data-go="#/revise/' + d.id + '"><div class="deck">'
        + '<div style="color:var(--text)">' + ring(d.cards.length ? known / d.cards.length : 0, 42) + '</div>'
        + '<div class="body"><h3>' + esc(d.title) + '</h3>'
        + '<div class="cnt">' + esc(d.subtitle) + ' &middot; ' + d.cards.length + ' cards</div></div>'
        + (due ? '<span class="pill due">' + due + ' due</span>' : '<span class="pill done">rested</span>')
        + '</div></button>';
    });
    h += '</div></div>';
    render(h, 'Revise', 'Spaced repetition over your notes', true);
  }

  var session = null;

  function viewSession(deckId) {
    var pool = [];
    if (deckId === 'all') {
      C.decks.forEach(function (d) {
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
    var d = today();
    state.log[d] = (state.log[d] || 0) + 1;
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
      + '<div class="setrow"><div class="lab">Progress recovery<small>Download or upload progress JSON</small></div>'
      + '<div style="display:flex;gap:8px">'
      + '<button class="btn" data-download-backup>Download JSON</button>'
      + '<label class="btn primary" style="cursor:pointer;margin:0">Upload JSON<input type="file" id="upload-backup-file" accept=".json" style="display:none"></label>'
      + '</div></div>'
      + (installPrompt ? '<div class="setrow"><div class="lab">Install<small>Add to home screen</small></div>'
        + '<button class="btn primary" data-install>Install app</button></div>' : '')
      + '<div class="setrow"><div class="lab" style="color:var(--dim);font-size:.78rem">'
      + 'Content built ' + esc(C.built || '') + ' &middot; v' + esc(C.version || '') + '<br>'
      + C.problems.length + ' problems, ' + C.refs.length + ' references, '
      + C.decks.reduce(function (n, d) { return n + d.cards.length; }, 0) + ' cards</div></div>';
    sheet(h);
  }

  // --------------------------------------------------------------- backup

  function downloadBackup() {
    var json = JSON.stringify(state, null, 2);
    var blob = new Blob([json], { type: 'application/json' });
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url;
    a.download = 'lld-hld-progress.json';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    toast('Download started');
  }

  function uploadBackup(file) {
    if (!file) return;
    var reader = new FileReader();
    reader.onload = function(e) {
      var data;
      try {
        data = JSON.parse(e.target.result);
      } catch (err) {
        toast('That is not a valid JSON file');
        return;
      }
      if (!data || typeof data !== 'object' || (!data.docs && !data.cards)) {
        toast('That backup does not look right');
        return;
      }
      state.docs = data.docs || {};
      state.cards = data.cards || {};
      state.star = data.star || {};
      state.log = data.log || {};
      state.last = data.last || null;
      if (data.settings) state.settings = Object.assign(state.settings, data.settings);
      writeNow();
      closeSheet();
      applyTheme();
      applySize();
      route();
      toast('Progress restored');
    };
    reader.readAsText(file);
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
    $$('.readerbar, .progressline').forEach(function (e) { e.remove(); });
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
    if (!state.mock[id]) state.mock[id] = { best: 0, runs: 0, last: 0, missed: [] };
    return state.mock[id];
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
      + '<div class="stat"><b>45</b><span>min each</span></div>'
      + '</div></div>';

    var basics = ref('HLD-BASICS');
    if (basics) {
      h += '<button class="card" data-go="#/r/HLD-BASICS"><div class="card-row">'
        + '<div class="num" style="font-size:1rem">&#9776;</div>'
        + '<div class="body"><h3>New to HLD? Read this first</h3>'
        + '<div class="meta">The 6 building blocks, the numbers, the 9 steps</div>'
        + '</div></div></button>';
    }

    ['LLD', 'HLD'].forEach(function (track) {
      var list = C.mocks.filter(function (m) { return m.track === track; });
      if (!list.length) return;
      var att = list.filter(function (m) { return mockStat(m.id).runs; }).length;
      h += '<h2 class="eyebrow">' + track + ' &middot; ' + list.length + ' rounds'
        + (att ? ' &middot; ' + att + ' attempted' : '') + '</h2>';
      list.forEach(function (m) { h += mockCard(m); });
    });
    h += '</div>';
    render(h, 'Mock', C.mocks.length + ' rounds', true);
  }

  function mockCard(m) {
    var st = mockStat(m.id);
    var badge = st.runs
      ? Math.round(st.best * 100) + '<span style="font-size:.55em">%</span>'
      : (m.track === 'LLD' ? m.id.slice(0, 2) : m.id.slice(4, 6));
    return '<button class="card" data-go="#/mock/' + m.id + '"><div class="card-row">'
      + '<div class="num' + (st.best >= 0.7 ? ' done' : '') + '">' + badge + '</div>'
      + '<div class="body"><h3>' + esc(m.title) + '</h3>'
      + '<div class="meta">' + esc(m.difficulty || m.time) + ' &middot; '
      + m.steps.length + ' steps &middot; ' + m.checkpoints + ' checkpoints'
      + (st.runs ? ' &middot; ' + st.runs + (st.runs > 1 ? ' runs' : ' run') : '') + '</div>'
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
    render(h, esc(m.title), '', false, { back: true, backTo: '#/mock' });
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
    render(h, esc(m.title), 'Clarify', false, { back: true, backTo: '#/mock' });
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
      st.best = Math.max(st.best, pct);
      st.missed = missed.slice(0, 40).map(function (x) { return x.what; });
      state.log[today()] = (state.log[today()] || 0) + 1;
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
    if (parts[0] === 't') return viewTrack(parts[1] === 'hld' ? 'hld' : 'lld');
    switch (parts[0]) {
      case 'p':
        return viewDoc('p', parts[1], parts[2] || 'problem', query);
      case 'r':
        return viewDoc('r', parts[1], '', query);
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

  document.addEventListener('change', function (e) {
    var t = e.target;
    if (t.id === 'upload-backup-file') {
      uploadBackup(t.files[0]);
    }
  });

  document.addEventListener('click', function (e) {
    var t = e.target;

    if (mockClick(t)) return;

    var go_ = t.closest('[data-go]');
    if (go_) { go(go_.dataset.go); return; }

    var goto_ = t.closest('[data-goto]');
    if (goto_) { go(goto_.dataset.goto); return; }

    var nav = t.closest('[data-nav]');
    if (nav) {
      var map = { home: '#/', concepts: '#/concepts', mock: '#/mock', revise: '#/revise', search: '#/search' };
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

    if (t.closest('[data-toc]') && currentDoc) {
      sheet('<h4>Sections</h4><div class="toc">' + currentDoc.toc.map(function (x) {
        return '<a href="#' + x.id + '" data-tocjump="' + x.id + '" class="h' + x.lvl + '">' + esc(x.text) + '</a>';
      }).join('') + '</div>');
      return;
    }

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
      save();
      return;
    }

    if (t.closest('[data-download-backup]')) { downloadBackup(); return; }

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

    if (t.closest('[data-bkrestore]')) { restoreBackup(); return; }

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
    if (e.target.tagName === 'INPUT' || e.metaKey || e.ctrlKey) return;
    if (e.key === '/') { e.preventDefault(); go('#/search'); return; }
    if (session && $('#fbar')) {
      if (e.key === ' ' || e.key === 'Enter') { e.preventDefault(); if ($('[data-show]')) showAnswer(); return; }
      if (e.key === '1' && $('[data-grade]')) { grade('again'); return; }
      if (e.key === '2' && $('[data-grade]')) { grade('good'); return; }
    }
    if (currentDoc && currentDoc.kind === 'p') {
      var p = currentDoc.item;
      var i = p.docs.findIndex(function (d) { return d.key === currentDoc.sub; });
      if (e.key === 'ArrowRight' && i < p.docs.length - 1) go('#/p/' + p.id + '/' + p.docs[i + 1].key);
      if (e.key === 'ArrowLeft' && i > 0) go('#/p/' + p.id + '/' + p.docs[i - 1].key);
    }
    if (e.key === 'Escape') { closeFull(); closeSheet(); }
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
