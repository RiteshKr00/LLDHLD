/* Diagram core - shared machinery for the four diagram renderers.
 *
 * Everything here is a pure string -> string transform: no DOM, no measuring, no
 * async. That is deliberate. It means diagrams render synchronously on the phone,
 * and it means the whole renderer can be tested offline without a browser.
 *
 * ES5 only (it is exercised under Windows Script Host by mobile/test/).
 *
 * Colours are emitted as CSS var() references, so a rendered diagram follows the
 * app's light/dark theme with no re-render.
 */

(function () {
  'use strict';

  var D = window.LLDD = window.LLDD || {};
  D.renderers = D.renderers || {};

  // ------------------------------------------------------------------ colours

  D.C = {
    surface: 'var(--surface, #121826)',
    node: 'var(--surface-2, #1a2233)',
    node2: 'var(--surface-3, #222c40)',
    line: 'var(--line, #253048)',
    text: 'var(--text, #e7ecf6)',
    dim: 'var(--dim, #93a1b8)',
    faint: 'var(--faint, #64748b)',
    accent: 'var(--accent, #6ea8fe)',
    accent2: 'var(--accent-2, #a78bfa)',
    ok: 'var(--ok, #34d399)',
    warn: 'var(--warn, #fbbf24)',
    danger: 'var(--danger, #f87171)'
  };

  D.FONT = '-apple-system,BlinkMacSystemFont,\'Segoe UI\',Roboto,Helvetica,Arial,sans-serif';
  D.MONO = 'ui-monospace,SFMono-Regular,Menlo,Consolas,\'Liberation Mono\',monospace';

  // ------------------------------------------------------------------ metrics

  /* Helvetica advance widths (units per 1000em). System sans faces differ a little,
     so callers get a small safety factor on top - a diagram that is 3% too wide is
     invisible, one that is 3% too narrow clips its own text. */
  var W = {};
  (function () {
    var groups = [
      [' ', 278], ['!', 278], ['"', 355], ['#', 556], ['$', 556], ['%', 889], ['&', 667],
      ['\'', 191], ['(', 333], [')', 333], ['*', 389], ['+', 584], [',', 278], ['-', 333],
      ['.', 278], ['/', 278], [':', 278], [';', 278], ['<', 584], ['=', 584], ['>', 584],
      ['?', 556], ['@', 1015], ['[', 278], ['\\', 278], [']', 278], ['^', 469], ['_', 556],
      ['`', 333], ['{', 334], ['|', 260], ['}', 334], ['~', 584]
    ];
    var i;
    for (i = 0; i < groups.length; i++) W[groups[i][0]] = groups[i][1];
    for (i = 0; i <= 9; i++) W[String(i)] = 556;

    var upper = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ';
    var upperW = [667, 667, 722, 722, 667, 611, 778, 722, 278, 500, 667, 556, 833,
                  722, 778, 667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611];
    for (i = 0; i < upper.length; i++) W[upper.charAt(i)] = upperW[i];

    var lower = 'abcdefghijklmnopqrstuvwxyz';
    var lowerW = [556, 556, 500, 556, 556, 278, 556, 556, 222, 222, 500, 222, 833,
                  556, 556, 556, 556, 333, 500, 278, 556, 500, 722, 500, 500, 500];
    for (i = 0; i < lower.length; i++) W[lower.charAt(i)] = lowerW[i];
  })();

  var SAFETY = 1.03;

  /** Width of a string in px. `mono` uses a fixed advance, which is exact. */
  D.textWidth = function (text, size, mono) {
    text = String(text == null ? '' : text);
    if (mono) return text.length * size * 0.6;
    var total = 0;
    for (var i = 0; i < text.length; i++) {
      var c = text.charAt(i);
      var w = W[c];
      if (w === undefined) {
        // unknown glyph (emoji, box drawing, accented): assume a wide-ish default
        w = text.charCodeAt(i) > 0x2000 ? 1000 : 556;
      }
      total += w;
    }
    return (total / 1000) * size * SAFETY;
  };

  /** Split on explicit <br/> and then greedily wrap to maxWidth. Returns lines. */
  D.wrapText = function (text, size, maxWidth, mono) {
    var out = [];
    var hard = String(text == null ? '' : text).split(/<br\s*\/?>/i);
    for (var h = 0; h < hard.length; h++) {
      var words = hard[h].replace(/\s+/g, ' ').replace(/^ | $/g, '').split(' ');
      var line = '';
      for (var i = 0; i < words.length; i++) {
        var word = words[i];
        if (word === '') continue;
        var next = line ? line + ' ' + word : word;
        if (line && D.textWidth(next, size, mono) > maxWidth) {
          out.push(line);
          line = word;
        } else {
          line = next;
        }
      }
      out.push(line);
    }
    // a single trailing empty line adds nothing but height
    while (out.length > 1 && out[out.length - 1] === '') out.pop();
    if (!out.length) out.push('');
    return out;
  };

  D.maxWidth = function (lines, size, mono) {
    var m = 0;
    for (var i = 0; i < lines.length; i++) {
      var w = D.textWidth(lines[i], size, mono);
      if (w > m) m = w;
    }
    return m;
  };

  // ------------------------------------------------------------------- markup

  D.esc = function (s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  };

  D.attrs = function (o) {
    var out = '';
    for (var k in o) {
      if (!o.hasOwnProperty(k)) continue;
      var v = o[k];
      if (v === null || v === undefined || v === false) continue;
      if (typeof v === 'number') v = D.round(v);
      out += ' ' + k + '="' + D.esc(v) + '"';
    }
    return out;
  };

  D.round = function (n) {
    if (typeof n !== 'number' || !isFinite(n)) return 0;
    return Math.round(n * 100) / 100;
  };

  D.el = function (name, attrs, inner) {
    var open = '<' + name + D.attrs(attrs || {});
    if (inner === undefined || inner === null || inner === '') return open + '/>';
    return open + '>' + inner + '</' + name + '>';
  };

  D.rect = function (x, y, w, h, o) {
    o = o || {};
    return D.el('rect', {
      x: x, y: y, width: Math.max(0, w), height: Math.max(0, h),
      rx: o.rx === undefined ? 8 : o.rx,
      fill: o.fill || D.C.node,
      stroke: o.stroke || D.C.line,
      'stroke-width': o.sw || 1,
      'stroke-dasharray': o.dash || null
    });
  };

  /** One line of text. `anchor` is start|middle|end. */
  D.text = function (x, y, str, o) {
    o = o || {};
    return D.el('text', {
      x: x, y: y,
      fill: o.fill || D.C.text,
      'font-family': o.mono ? D.MONO : D.FONT,
      'font-size': o.size || 13,
      'font-weight': o.weight || null,
      'font-style': o.italic ? 'italic' : null,
      'text-anchor': o.anchor || 'middle',
      'dominant-baseline': o.baseline || null
    }, D.esc(str));
  };

  /** Several lines, vertically centred on cy. Returns markup. */
  D.textBlock = function (cx, cy, lines, o) {
    o = o || {};
    var size = o.size || 13;
    var lh = o.lh || (size * 1.32);
    var top = cy - ((lines.length - 1) * lh) / 2;
    var out = '';
    for (var i = 0; i < lines.length; i++) {
      out += D.text(cx, top + i * lh + size * 0.35, lines[i], o);
    }
    return out;
  };

  D.path = function (d, o) {
    o = o || {};
    return D.el('path', {
      d: d,
      fill: o.fill || 'none',
      stroke: o.stroke === null ? null : (o.stroke || D.C.dim),
      'stroke-width': o.sw || 1.4,
      'stroke-dasharray': o.dash || null,
      'stroke-linecap': 'round',
      'stroke-linejoin': 'round',
      'marker-end': o.markerEnd ? 'url(#' + o.markerEnd + ')' : null,
      'marker-start': o.markerStart ? 'url(#' + o.markerStart + ')' : null
    });
  };

  // ------------------------------------------------------------------ markers

  /* Arrowheads. Mermaid's vocabulary, drawn once into <defs>:
       arrow      open arrow      -->   association / flow
       tri        hollow triangle <|--  inheritance
       dia        filled diamond  *--   composition
       diaO       hollow diamond  o--   aggregation
       arrowD     open arrow      ..>   dependency (the line is dashed, not the head)  */
  D.defs = function () {
    function marker(id, w, h, refX, refY, body) {
      return D.el('marker', {
        id: id, markerWidth: w, markerHeight: h, refX: refX, refY: refY,
        orient: 'auto', markerUnits: 'userSpaceOnUse'
      }, body);
    }
    var out = '';
    out += marker('d-arrow', 10, 10, 9.5, 5,
      D.el('path', { d: 'M0,0.6 L10,5 L0,9.4', fill: 'none', stroke: D.C.dim, 'stroke-width': 1.5,
                     'stroke-linecap': 'round', 'stroke-linejoin': 'round' }));
    out += marker('d-arrow-accent', 10, 10, 9.5, 5,
      D.el('path', { d: 'M0,0.6 L10,5 L0,9.4', fill: 'none', stroke: D.C.accent, 'stroke-width': 1.5,
                     'stroke-linecap': 'round', 'stroke-linejoin': 'round' }));
    out += marker('d-tri', 13, 13, 12, 6.5,
      D.el('path', { d: 'M0.8,0.8 L12,6.5 L0.8,12.2 Z', fill: D.C.surface, stroke: D.C.dim, 'stroke-width': 1.4,
                     'stroke-linejoin': 'round' }));
    out += marker('d-dia', 15, 11, 14, 5.5,
      D.el('path', { d: 'M0.6,5.5 L7,1 L13.8,5.5 L7,10 Z', fill: D.C.dim, stroke: D.C.dim, 'stroke-width': 1.2,
                     'stroke-linejoin': 'round' }));
    out += marker('d-diaO', 15, 11, 14, 5.5,
      D.el('path', { d: 'M0.6,5.5 L7,1 L13.8,5.5 L7,10 Z', fill: D.C.surface, stroke: D.C.dim, 'stroke-width': 1.3,
                     'stroke-linejoin': 'round' }));
    out += marker('d-dot', 9, 9, 4.5, 4.5,
      D.el('circle', { cx: 4.5, cy: 4.5, r: 3.4, fill: D.C.text }));
    return D.el('defs', {}, out);
  };

  // ------------------------------------------------------------------- layout

  /**
   * Layered top-down layout for a directed graph.
   *
   * nodes: [{id, w, h}]  (mutated: gains x, y - the top-left corner)
   * edges: [{from, to, ...}] (mutated: gains `back` when it points against the flow)
   * opts:  {vGap, hGap, align}
   *
   * Cycles are broken by depth-first search: an edge that closes a cycle is marked
   * `back` and ignored while assigning layers, then drawn as a return path. Without
   * this, a retry loop ("code taken -> generate again") would never terminate.
   */
  D.layered = function (nodes, edges, opts) {
    opts = opts || {};
    var vGap = opts.vGap === undefined ? 46 : opts.vGap;
    var hGap = opts.hGap === undefined ? 26 : opts.hGap;

    var byId = {}, i, j, n, e;
    for (i = 0; i < nodes.length; i++) byId[nodes[i].id] = nodes[i];

    var out = {}, incoming = {};
    for (i = 0; i < nodes.length; i++) { out[nodes[i].id] = []; incoming[nodes[i].id] = []; }
    for (i = 0; i < edges.length; i++) {
      e = edges[i];
      e.back = false;
      if (!byId[e.from] || !byId[e.to] || e.from === e.to) { e.self = e.from === e.to; continue; }
      out[e.from].push(e);
    }

    // mark back edges with an iterative DFS (recursion would risk deep graphs)
    var state = {};                                  // 0 unvisited, 1 on stack, 2 done
    for (i = 0; i < nodes.length; i++) state[nodes[i].id] = 0;
    for (i = 0; i < nodes.length; i++) {
      if (state[nodes[i].id] !== 0) continue;
      var stack = [{ id: nodes[i].id, k: 0 }];
      state[nodes[i].id] = 1;
      while (stack.length) {
        var top = stack[stack.length - 1];
        var list = out[top.id];
        if (top.k >= list.length) { state[top.id] = 2; stack.pop(); continue; }
        e = list[top.k++];
        var s = state[e.to];
        if (s === 1) e.back = true;                  // closes a cycle
        else if (s === 0) { state[e.to] = 1; stack.push({ id: e.to, k: 0 }); }
      }
    }

    var forward = [];
    for (i = 0; i < edges.length; i++) {
      e = edges[i];
      if (e.back || e.self || !byId[e.from] || !byId[e.to]) continue;
      forward.push(e);
      incoming[e.to].push(e.from);
    }

    // layer = longest path from any source, relaxed until stable
    var layer = {};
    for (i = 0; i < nodes.length; i++) layer[nodes[i].id] = 0;
    for (var pass = 0; pass < nodes.length + 1; pass++) {
      var moved = false;
      for (i = 0; i < forward.length; i++) {
        e = forward[i];
        if (layer[e.to] < layer[e.from] + 1) { layer[e.to] = layer[e.from] + 1; moved = true; }
      }
      if (!moved) break;
    }

    var layers = [];
    for (i = 0; i < nodes.length; i++) {
      n = nodes[i];
      var L = layer[n.id];
      while (layers.length <= L) layers.push([]);
      layers[L].push(n);
      n.layer = L;
    }

    // order within each layer by the average position of its parents (barycentre),
    // which is a cheap and effective way to cut edge crossings
    var pos = {};
    for (i = 0; i < layers.length; i++) {
      for (j = 0; j < layers[i].length; j++) pos[layers[i][j].id] = j;
    }
    for (var sweep = 0; sweep < 4; sweep++) {
      for (i = 1; i < layers.length; i++) {
        var row = layers[i];
        for (j = 0; j < row.length; j++) {
          var parents = incoming[row[j].id];
          var sum = 0, cnt = 0;
          for (var p = 0; p < parents.length; p++) {
            if (pos[parents[p]] !== undefined) { sum += pos[parents[p]]; cnt++; }
          }
          row[j]._bc = cnt ? sum / cnt : pos[row[j].id];
        }
        row.sort(function (a, b) { return a._bc - b._bc; });
        for (j = 0; j < row.length; j++) pos[row[j].id] = j;
      }
    }

    // place: each layer is a centred row
    var y = 0, width = 0;
    var rowWidths = [];
    for (i = 0; i < layers.length; i++) {
      var w = 0;
      for (j = 0; j < layers[i].length; j++) w += layers[i][j].w + (j ? hGap : 0);
      rowWidths.push(w);
      if (w > width) width = w;
    }
    for (i = 0; i < layers.length; i++) {
      var x = (width - rowWidths[i]) / 2;
      var tallest = 0;
      for (j = 0; j < layers[i].length; j++) {
        n = layers[i][j];
        n.x = x;
        n.y = y;
        x += n.w + hGap;
        if (n.h > tallest) tallest = n.h;
      }
      for (j = 0; j < layers[i].length; j++) {
        // centre shorter boxes against the tallest in the row
        layers[i][j].y = y + (tallest - layers[i][j].h) / 2;
      }
      y += tallest + vGap;
    }

    return { width: width, height: Math.max(0, y - vGap), layers: layers };
  };

  // -------------------------------------------------------------------- edges

  D.centre = function (n) { return { x: n.x + n.w / 2, y: n.y + n.h / 2 }; };

  /** Where an edge should leave/enter a box, given a side. */
  D.anchor = function (n, side) {
    var c = D.centre(n);
    if (side === 'top') return { x: c.x, y: n.y };
    if (side === 'bottom') return { x: c.x, y: n.y + n.h };
    if (side === 'left') return { x: n.x, y: c.y };
    return { x: n.x + n.w, y: c.y };
  };

  /**
   * A top-to-bottom connector between two boxes: straight when they line up,
   * otherwise a rounded elbow through the middle of the gap.
   */
  D.connect = function (from, to, opts) {
    opts = opts || {};
    var inset = opts.inset || 0;
    var a = D.anchor(from, 'bottom');
    var b = D.anchor(to, 'top');
    b = { x: b.x, y: b.y - inset };

    if (Math.abs(a.x - b.x) < 1.5) {
      return { d: 'M' + D.round(a.x) + ',' + D.round(a.y) + ' L' + D.round(b.x) + ',' + D.round(b.y),
               mid: { x: a.x, y: (a.y + b.y) / 2 } };
    }
    var my = (a.y + b.y) / 2;
    var r = Math.min(10, Math.abs(b.x - a.x) / 2, Math.abs(my - a.y), Math.abs(b.y - my));
    var dir = b.x > a.x ? 1 : -1;
    var d = 'M' + D.round(a.x) + ',' + D.round(a.y)
      + ' L' + D.round(a.x) + ',' + D.round(my - r)
      + ' Q' + D.round(a.x) + ',' + D.round(my) + ' ' + D.round(a.x + r * dir) + ',' + D.round(my)
      + ' L' + D.round(b.x - r * dir) + ',' + D.round(my)
      + ' Q' + D.round(b.x) + ',' + D.round(my) + ' ' + D.round(b.x) + ',' + D.round(my + r)
      + ' L' + D.round(b.x) + ',' + D.round(b.y);
    return { d: d, mid: { x: (a.x + b.x) / 2, y: my } };
  };

  /** A return path for an edge that points back up the graph, routed clear on the right. */
  D.connectBack = function (from, to, gutterX, opts) {
    opts = opts || {};
    var a = D.anchor(from, 'right');
    var b = D.anchor(to, 'right');
    var r = 10;
    var d = 'M' + D.round(a.x) + ',' + D.round(a.y)
      + ' L' + D.round(gutterX - r) + ',' + D.round(a.y)
      + ' Q' + D.round(gutterX) + ',' + D.round(a.y) + ' ' + D.round(gutterX) + ',' + D.round(a.y - r)
      + ' L' + D.round(gutterX) + ',' + D.round(b.y + r)
      + ' Q' + D.round(gutterX) + ',' + D.round(b.y) + ' ' + D.round(gutterX - r) + ',' + D.round(b.y)
      + ' L' + D.round(b.x + 2) + ',' + D.round(b.y);
    return { d: d, mid: { x: gutterX, y: (a.y + b.y) / 2 } };
  };

  /** A self-loop hanging off the right edge of a box. */
  D.selfLoop = function (n, opts) {
    opts = opts || {};
    var out = opts.out || 30;
    var x = n.x + n.w, y1 = n.y + n.h * 0.32, y2 = n.y + n.h * 0.68;
    var d = 'M' + D.round(x) + ',' + D.round(y1)
      + ' C' + D.round(x + out) + ',' + D.round(y1 - 6) + ' '
      + D.round(x + out) + ',' + D.round(y2 + 6) + ' '
      + D.round(x + 2) + ',' + D.round(y2);
    return { d: d, mid: { x: x + out * 0.78, y: (y1 + y2) / 2 } };
  };

  /** A label chip that sits on top of an edge without the line showing through. */
  D.edgeLabel = function (cx, cy, text, opts) {
    opts = opts || {};
    var size = opts.size || 11;
    var lines = D.wrapText(text, size, opts.maxWidth || 170);
    var w = D.maxWidth(lines, size) + 12;
    var lh = size * 1.28;
    var h = lines.length * lh + 5;
    return D.rect(cx - w / 2, cy - h / 2, w, h, {
      rx: 5, fill: opts.fill || D.C.surface, stroke: opts.stroke || 'none', sw: 0
    }) + D.textBlock(cx, cy, lines, { size: size, fill: opts.color || D.C.dim, lh: lh });
  };

  // -------------------------------------------------------------------- frame

  /**
   * Wrap body markup in an <svg>. Width/height are the natural size; the page
   * scrolls horizontally rather than shrinking text to nothing on a phone.
   */
  D.frame = function (width, height, body, opts) {
    opts = opts || {};
    var pad = opts.pad === undefined ? 12 : opts.pad;
    var w = Math.max(1, Math.ceil(width + pad * 2));
    var h = Math.max(1, Math.ceil(height + pad * 2));
    return D.el('svg', {
      xmlns: 'http://www.w3.org/2000/svg',
      viewBox: '0 0 ' + w + ' ' + h,
      width: w, height: h,
      'class': 'lldd',
      role: 'img'
    }, D.defs() + D.el('g', { transform: 'translate(' + pad + ',' + pad + ')' }, body));
  };

  // ------------------------------------------------------------------ parsing

  /** Strip comments and blank lines, keeping indentation-free trimmed lines. */
  D.lines = function (src) {
    var raw = String(src).replace(/\r\n?/g, '\n').split('\n');
    var out = [];
    for (var i = 0; i < raw.length; i++) {
      var t = raw[i].replace(/^\s+|\s+$/g, '');
      if (!t) continue;
      if (t.indexOf('%%') === 0) continue;           // mermaid comment
      out.push(t);
    }
    return out;
  };

  /** Turn a mermaid label into display text: unescape quotes, keep <br/> markers. */
  D.label = function (s) {
    if (s === undefined || s === null) return '';
    s = String(s).replace(/^\s+|\s+$/g, '');
    if ((s.charAt(0) === '"' && s.charAt(s.length - 1) === '"') ||
        (s.charAt(0) === "'" && s.charAt(s.length - 1) === "'")) {
      s = s.slice(1, -1);
    }
    return s.replace(/#quot;/g, '"').replace(/#35;/g, '#');
  };

  /**
   * Entry point used by the app. Picks a renderer from the first meaningful line
   * and returns SVG markup, or throws so the caller can fall back to the source.
   */
  D.render = function (src) {
    var lines = D.lines(src);
    if (!lines.length) throw new Error('empty diagram');
    var head = lines[0];
    var kind = null;
    if (/^classDiagram/.test(head)) kind = 'classDiagram';
    else if (/^stateDiagram(-v2)?/.test(head)) kind = 'stateDiagram';
    else if (/^(flowchart|graph)\b/.test(head)) kind = 'flowchart';
    else if (/^sequenceDiagram/.test(head)) kind = 'sequenceDiagram';
    if (!kind || !D.renderers[kind]) throw new Error('unsupported diagram: ' + head.slice(0, 24));
    return D.renderers[kind](lines, head);
  };
})();
