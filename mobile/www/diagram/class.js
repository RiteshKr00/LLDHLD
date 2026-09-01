/* classDiagram - UML class boxes with a layered, row-wrapping layout.
 *
 * Mobile first: a layer that would be wider than ROW_MAX is split into stacked
 * sub-rows, so eight classes become two rows of four instead of one 2000px line.
 * Edges are orthogonal polylines picked from a handful of candidate routes; the
 * first route that clears every other box wins, and if none does the edge is sent
 * round the outside of the drawing in a routing lane.
 *
 * ES5 only (exercised under Windows Script Host). Pure: string in, SVG out.
 */

(function () {
  'use strict';

  var D = window.LLDD;
  if (!D) return;

  // -------------------------------------------------------------------- sizes

  var NAME_SIZE = 13, NAME_LH = 17, NAME_MAXW = 210;
  var STER_SIZE = 10.5, STER_LH = 15;
  var MEM_SIZE = 11.5, MEM_LH = 16, MEM_MAXW = 210;
  var PADX = 13, HPAD_TOP = 10, HPAD_BOT = 9, CPAD = 8;
  var MINW = 104;
  var HGAP = 34, VGAP = 58, SUBGAP = 42;
  var ROW_MAX = 700;
  var LBL_SIZE = 11, LBL_MAXW = 150, CARD_SIZE = 10;
  var CLEAR = 6;                 // clearance margin when testing a route segment
  var LANE = 18;                 // gap between outside routing lanes
  var CORNER = 9;

  function trim(s) {
    return String(s === null || s === undefined ? '' : s).replace(/^\s+|\s+$/g, '');
  }

  /* mermaid writes generics as List~Cell~ - render them the way people read them. */
  function generics(s) { return String(s).replace(/~([^~]*)~/g, '<$1>'); }

  // ------------------------------------------------------------------ parsing

  var REL = new RegExp(
    '^([A-Za-z_][A-Za-z0-9_]*)\\s*(?:"([^"]*)"\\s*)?' +
    '(<\\|--|--\\|>|<\\|\\.\\.|\\.\\.\\|>|\\*--|--\\*|o--|--o|-->|<--|\\.\\.>|<\\.\\.|--|\\.\\.)' +
    '\\s*(?:"([^"]*)"\\s*)?([A-Za-z_][A-Za-z0-9_]*)\\s*$');

  /* op -> which side ends up on top, which end carries the marker, dashed or not.
     "up" is drawn above "down"; A <|-- B puts the hollow triangle on A. */
  var OPS = {
    '<|--': { top: 'L', mk: 'd-tri', at: 'up', dash: 0 },
    '--|>': { top: 'R', mk: 'd-tri', at: 'up', dash: 0 },
    '<|..': { top: 'L', mk: 'd-tri', at: 'up', dash: 1 },
    '..|>': { top: 'R', mk: 'd-tri', at: 'up', dash: 1 },
    '*--': { top: 'L', mk: 'd-dia', at: 'up', dash: 0 },
    '--*': { top: 'R', mk: 'd-dia', at: 'up', dash: 0 },
    'o--': { top: 'L', mk: 'd-diaO', at: 'up', dash: 0 },
    '--o': { top: 'R', mk: 'd-diaO', at: 'up', dash: 0 },
    '-->': { top: 'L', mk: 'd-arrow', at: 'down', dash: 0 },
    '<--': { top: 'R', mk: 'd-arrow', at: 'down', dash: 0 },
    '..>': { top: 'L', mk: 'd-arrow', at: 'down', dash: 1 },
    '<..': { top: 'R', mk: 'd-arrow', at: 'down', dash: 1 },
    '--': { top: 'L', mk: null, at: 'down', dash: 0 },
    '..': { top: 'L', mk: null, at: 'down', dash: 1 }
  };

  function camelParts(name) {
    var out = [], cur = '', i, c, prev;
    for (i = 0; i < name.length; i++) {
      c = name.charAt(i);
      prev = i ? name.charAt(i - 1) : '';
      if (cur && c >= 'A' && c <= 'Z' && !(prev >= 'A' && prev <= 'Z')) { out.push(cur); cur = c; }
      else cur += c;
    }
    if (cur) out.push(cur);
    if (!out.length) out.push(name);
    return out;
  }

  /* Long class names have no spaces, so wrap them on their camel-case seams. */
  function wrapName(name) {
    if (D.textWidth(name, NAME_SIZE, false) <= NAME_MAXW) return [name];
    var parts = camelParts(name), out = [], cur = '', i, next;
    for (i = 0; i < parts.length; i++) {
      next = cur + parts[i];
      if (cur && D.textWidth(next, NAME_SIZE, false) > NAME_MAXW) { out.push(cur); cur = parts[i]; }
      else cur = next;
    }
    if (cur) out.push(cur);
    return out;
  }

  /* Members are code, so they are monospaced and left aligned; over-long ones wrap
     with a hanging indent rather than stretching the box across the phone. */
  function wrapMember(t) {
    if (D.textWidth(t, MEM_SIZE, true) <= MEM_MAXW) return [t];
    var parts = D.wrapText(t, MEM_SIZE, MEM_MAXW, true), out = [parts[0]], i;
    for (i = 1; i < parts.length; i++) out.push('  ' + parts[i]);
    return out;
  }

  function makeNode(id) {
    return { id: id, name: id, stereo: null, fields: [], methods: [],
             x: 0, y: 0, w: 0, h: 0, layer: 0, row: 0, deg: 0, seq: 0, gk: '' };
  }

  function addMember(n, raw) {
    var t = trim(raw), m;
    if (!t) return;
    m = t.match(/^<<\s*(.+?)\s*>>$/);
    if (m) { n.stereo = m[1]; return; }
    t = generics(t);
    if (t.indexOf('(') >= 0) n.methods.push(t); else n.fields.push(t);
  }

  function parse(lines) {
    var nodes = [], byId = {}, edges = [], i, line, m, n, cur = null, ci, label, o;

    function nodeFor(id) {
      if (!byId[id]) { byId[id] = makeNode(id); byId[id].seq = nodes.length; nodes.push(byId[id]); }
      return byId[id];
    }

    for (i = 1; i < lines.length; i++) {
      line = lines[i];
      if (cur) {
        if (line.charAt(0) === '}') { cur = null; continue; }
        addMember(cur, line);
        continue;
      }
      m = line.match(/^class\s+([A-Za-z_][A-Za-z0-9_]*)\s*(\{)?\s*$/);
      if (m) { n = nodeFor(m[1]); if (m[2]) cur = n; continue; }
      if (/^(direction|note|click|style|classDef|cssClass|link|namespace|end)\b/i.test(line)) continue;

      label = '';
      ci = line.indexOf(':');
      if (ci >= 0) { label = D.label(trim(line.slice(ci + 1))); line = trim(line.slice(0, ci)); }
      m = line.match(REL);
      if (!m) {
        /* mermaid's block-free member form, "Animal : +int age". Without this the
           member - and often the class itself - is dropped without a trace. */
        if (ci >= 0 && /^[A-Za-z_][A-Za-z0-9_]*$/.test(line)) addMember(nodeFor(line), label);
        continue;
      }
      o = OPS[m[3]];
      if (!o) continue;
      var upN = o.top === 'L' ? nodeFor(m[1]) : nodeFor(m[5]);
      var dnN = o.top === 'L' ? nodeFor(m[5]) : nodeFor(m[1]);
      var upC = o.top === 'L' ? m[2] : m[4];
      var dnC = o.top === 'L' ? m[4] : m[2];
      edges.push({ from: upN.id, to: dnN.id, up: upN, down: dnN,
                   upCard: upC ? trim(upC) : '', downCard: dnC ? trim(dnC) : '',
                   mk: o.mk, at: o.at, dash: !!o.dash, label: label, back: false });
      upN.deg++; dnN.deg++;
    }
    if (!nodes.length) throw new Error('classDiagram: no classes found');
    return { nodes: nodes, byId: byId, edges: edges };
  }

  // ---------------------------------------------------------------- measuring

  function measure(n) {
    var i, w, lines;
    n.nameLines = wrapName(n.name);
    n.fLines = [];
    n.mLines = [];
    for (i = 0; i < n.fields.length; i++) {
      lines = wrapMember(n.fields[i]);
      n.fLines = n.fLines.concat(lines);
    }
    for (i = 0; i < n.methods.length; i++) {
      lines = wrapMember(n.methods[i]);
      n.mLines = n.mLines.concat(lines);
    }
    w = D.maxWidth(n.nameLines, NAME_SIZE, false) + 6;
    if (n.stereo) {
      var sw = D.textWidth('<<' + n.stereo + '>>', STER_SIZE, false);
      if (sw > w) w = sw;
    }
    var mw = D.maxWidth(n.fLines, MEM_SIZE, true);
    var mw2 = D.maxWidth(n.mLines, MEM_SIZE, true);
    if (mw2 > mw) mw = mw2;
    if (mw > w) w = mw;
    n.w = Math.max(MINW, Math.ceil(w + PADX * 2));

    n.hdr = HPAD_TOP + n.nameLines.length * NAME_LH + (n.stereo ? STER_LH : 0) + HPAD_BOT;
    n.fH = n.fLines.length ? CPAD * 2 + n.fLines.length * MEM_LH : 0;
    n.mH = n.mLines.length ? CPAD * 2 + n.mLines.length * MEM_LH : 0;
    n.h = Math.ceil(n.hdr + n.fH + n.mH);
  }

  // ------------------------------------------------------------------- layers

  /* Longest-path layering, then two corrections that matter a lot in practice:
     a source with children is pulled down to sit just above its highest child
     (otherwise a mixin declared first floats five layers away from what it mixes
     into), and a class with no relationships at all is parked in a final row. */
  function assignLayers(nodes, edges) {
    var i, e, live = [], layer = {}, hasIn = {}, kids = {}, id;

    for (i = 0; i < nodes.length; i++) {
      id = nodes[i].id;
      layer[id] = 0; hasIn[id] = false; kids[id] = [];
    }
    for (i = 0; i < edges.length; i++) {
      e = edges[i];
      if (e.back || e.from === e.to) continue;
      live.push(e);
      hasIn[e.to] = true;
      kids[e.from].push(e.to);
    }

    var pass, moved;
    for (pass = 0; pass <= nodes.length; pass++) {
      moved = false;
      for (i = 0; i < live.length; i++) {
        e = live[i];
        if (layer[e.to] < layer[e.from] + 1) { layer[e.to] = layer[e.from] + 1; moved = true; }
      }
      if (!moved) break;
    }

    // pull childless-parent sources down next to their children
    for (i = 0; i < nodes.length; i++) {
      id = nodes[i].id;
      if (hasIn[id] || !kids[id].length) continue;
      var lo = -1, j;
      for (j = 0; j < kids[id].length; j++) {
        if (lo < 0 || layer[kids[id][j]] < lo) lo = layer[kids[id][j]];
      }
      if (lo > 0) layer[id] = lo - 1;
    }

    // isolated classes (enums, value objects) go to the bottom, out of the way
    var maxL = -1, isolated = [];
    for (i = 0; i < nodes.length; i++) {
      id = nodes[i].id;
      if (!hasIn[id] && !kids[id].length) { isolated.push(id); continue; }
      if (layer[id] > maxL) maxL = layer[id];
    }
    for (i = 0; i < isolated.length; i++) layer[isolated[i]] = maxL + 1;

    // compact to 0..k
    var used = [], seen = {};
    for (i = 0; i < nodes.length; i++) {
      if (!seen[layer[nodes[i].id]]) { seen[layer[nodes[i].id]] = 1; used.push(layer[nodes[i].id]); }
    }
    used.sort(function (a, b) { return a - b; });
    var rank = {};
    for (i = 0; i < used.length; i++) rank[used[i]] = i;

    var layers = [];
    for (i = 0; i < used.length; i++) layers.push([]);
    for (i = 0; i < nodes.length; i++) {
      nodes[i].layer = rank[layer[nodes[i].id]];
      layers[nodes[i].layer].push(nodes[i]);
    }

    // barycentre ordering, to cut crossings
    var parents = {};
    for (i = 0; i < nodes.length; i++) parents[nodes[i].id] = [];
    for (i = 0; i < live.length; i++) parents[live[i].to].push(live[i].from);

    // a node's "family" is the set of classes it hangs off; a wrapped layer is cut
    // along family seams so a set of siblings is not split across two rows
    for (i = 0; i < nodes.length; i++) {
      var ps0 = parents[nodes[i].id].slice(0);
      ps0.sort();
      nodes[i].gk = ps0.join(',');
    }

    var pos = {}, j2, k;
    for (i = 0; i < layers.length; i++) {
      layers[i].sort(function (a, b) { return a.seq - b.seq; });
      for (j2 = 0; j2 < layers[i].length; j2++) pos[layers[i][j2].id] = j2;
    }
    for (k = 0; k < 4; k++) {
      for (i = 1; i < layers.length; i++) {
        var row = layers[i];
        for (j2 = 0; j2 < row.length; j2++) {
          var ps = parents[row[j2].id], sum = 0, cnt = 0, p;
          for (p = 0; p < ps.length; p++) {
            if (pos[ps[p]] !== undefined) { sum += pos[ps[p]]; cnt++; }
          }
          row[j2].bc = cnt ? sum / cnt : pos[row[j2].id];
        }
        row.sort(function (a, b) { return a.bc === b.bc ? a.seq - b.seq : a.bc - b.bc; });
        for (j2 = 0; j2 < row.length; j2++) pos[row[j2].id] = j2;
      }
    }
    return layers;
  }

  // ---------------------------------------------------------------- placement

  function rowWidth(list) {
    var w = 0, i;
    for (i = 0; i < list.length; i++) w += list[i].w + (i ? HGAP : 0);
    return w;
  }

  /* Split one layer into as few sub-rows as will fit the phone, balanced by count
     so a wrapped layer does not end up as "three boxes, then one lonely box". */
  function splitRow(list) {
    var greedy = [], cur = [], curW = 0, i, add;
    for (i = 0; i < list.length; i++) {
      add = (cur.length ? HGAP : 0) + list[i].w;
      if (cur.length && curW + add > ROW_MAX) { greedy.push(cur); cur = []; curW = 0; add = list[i].w; }
      cur.push(list[i]);
      curW += add;
    }
    if (cur.length) greedy.push(cur);
    if (greedy.length < 2) return greedy;

    var k = greedy.length, bounds = [], t, c;
    for (i = 1; i < k; i++) bounds.push(Math.round(i * list.length / k));
    for (i = 0; i < bounds.length; i++) {
      var tries = [bounds[i], bounds[i] - 1, bounds[i] + 1];
      for (t = 0; t < tries.length; t++) {
        c = tries[t];
        if (c <= 0 || c >= list.length) continue;
        if (i > 0 && c <= bounds[i - 1]) continue;
        if (i < bounds.length - 1 && c >= bounds[i + 1]) continue;
        if (list[c - 1].gk !== list[c].gk) { bounds[i] = c; break; }
      }
    }
    var even = [], start = 0, ok = true;
    for (i = 0; i <= bounds.length; i++) {
      var end = i < bounds.length ? bounds[i] : list.length;
      if (end > start) even.push(list.slice(start, end));
      start = end;
    }
    for (i = 0; i < even.length; i++) {
      if (even[i].length > 1 && rowWidth(even[i]) > ROW_MAX) { ok = false; break; }
    }
    return ok && even.length === k ? even : greedy;
  }

  function place(layers) {
    var rows = [], i, j, list, parts;
    for (i = 0; i < layers.length; i++) {
      parts = splitRow(layers[i]);
      for (j = 0; j < parts.length; j++) {
        rows.push({ nodes: parts[j], w: rowWidth(parts[j]), first: j === 0, top: 0, bottom: 0 });
      }
    }
    var contentW = 0;
    for (i = 0; i < rows.length; i++) if (rows[i].w > contentW) contentW = rows[i].w;

    var y = 0;
    for (i = 0; i < rows.length; i++) {
      if (i) y += rows[i].first ? VGAP : SUBGAP;
      var r = rows[i], x = (contentW - r.w) / 2, tall = 0;
      for (j = 0; j < r.nodes.length; j++) if (r.nodes[j].h > tall) tall = r.nodes[j].h;
      for (j = 0; j < r.nodes.length; j++) {
        var n = r.nodes[j];
        n.x = x;
        n.y = y + (tall - n.h) / 2;
        n.row = i;
        x += n.w + HGAP;
      }
      r.top = y;
      r.bottom = y + tall;
      y = r.bottom;
    }
    return { rows: rows, contentW: contentW, contentH: y };
  }

  // ------------------------------------------------------------------ routing

  function spans(a1, a2, b1, b2) {
    var lo = a1 < a2 ? a1 : a2, hi = a1 < a2 ? a2 : a1;
    return lo < b2 && hi > b1;
  }

  function vClear(x, y1, y2, boxes, A, B) {
    for (var i = 0; i < boxes.length; i++) {
      var b = boxes[i];
      if (b === A || b === B) continue;
      if (x > b.x - CLEAR && x < b.x + b.w + CLEAR && spans(y1, y2, b.y - CLEAR, b.y + b.h + CLEAR)) return false;
    }
    return true;
  }

  function hClear(y, x1, x2, boxes, A, B) {
    for (var i = 0; i < boxes.length; i++) {
      var b = boxes[i];
      if (b === A || b === B) continue;
      if (y > b.y - CLEAR && y < b.y + b.h + CLEAR && spans(x1, x2, b.x - CLEAR, b.x + b.w + CLEAR)) return false;
    }
    return true;
  }

  function chanAbove(rows, i) {
    return i > 0 ? (rows[i - 1].bottom + rows[i].top) / 2 : rows[i].top - 26;
  }
  function chanBelow(rows, i) {
    return i < rows.length - 1 ? (rows[i].bottom + rows[i + 1].top) / 2 : rows[i].bottom + 26;
  }

  /* Vertical corridors that a skipping edge might slip through: the margins of
     every row it has to cross, plus the gaps between boxes in those rows. */
  function corridors(rows, r1, r2, want) {
    var xs = [], i, j, ns;
    for (i = r1 + 1; i < r2; i++) {
      ns = rows[i].nodes;
      xs.push(ns[0].x - 19);
      for (j = 1; j < ns.length; j++) xs.push((ns[j - 1].x + ns[j - 1].w + ns[j].x) / 2);
      xs.push(ns[ns.length - 1].x + ns[ns.length - 1].w + 19);
    }
    xs.sort(function (a, b) { return Math.abs(a - want) - Math.abs(b - want); });
    return xs;
  }

  function P(x, y) { return { x: x, y: y }; }

  /* A downhill route from A (exiting its bottom) to B (entering its top).
     Horizontal runs are always placed in a channel between two rows, which is
     empty by construction; only the vertical drops need testing. */
  function routeDown(A, B, rows, boxes, lanes) {
    var ax = A.x + A.w / 2, bx = B.x + B.w / 2;
    var ay = A.y + A.h, by = B.y;
    var c1 = chanBelow(rows, A.row), c2 = chanAbove(rows, B.row);
    var i, xs, x;

    if (Math.abs(ax - bx) < 1.2 && vClear(ax, ay, by, boxes, A, B)) return [P(ax, ay), P(bx, by)];

    if (vClear(bx, c1, by, boxes, A, B) && hClear(c1, ax, bx, boxes, A, B)) {
      return [P(ax, ay), P(ax, c1), P(bx, c1), P(bx, by)];
    }
    if (c2 > c1 + 2 && vClear(ax, ay, c2, boxes, A, B) && hClear(c2, ax, bx, boxes, A, B)) {
      return [P(ax, ay), P(ax, c2), P(bx, c2), P(bx, by)];
    }
    if (c2 > c1 + 2) {
      xs = corridors(rows, A.row, B.row, (ax + bx) / 2);
      for (i = 0; i < xs.length; i++) {
        x = xs[i];
        if (vClear(x, c1, c2, boxes, A, B) && hClear(c1, ax, x, boxes, A, B) && hClear(c2, x, bx, boxes, A, B)) {
          return [P(ax, ay), P(ax, c1), P(x, c1), P(x, c2), P(bx, c2), P(bx, by)];
        }
      }
    }
    x = lanes.take((ax + bx) / 2, c1, c2);
    return [P(ax, ay), P(ax, c1), P(x, c1), P(x, c2), P(bx, c2), P(bx, by)];
  }

  /* Two boxes in the same row: dip below the row and come back up. */
  function routeSide(A, B, rows, lanes) {
    var ax = A.x + A.w / 2, bx = B.x + B.w / 2;
    var c = chanBelow(rows, A.row);
    return [P(ax, A.y + A.h), P(ax, c), P(bx, c), P(bx, B.y + B.h)];
  }

  function reverse(pts) {
    var out = [], i;
    for (i = pts.length - 1; i >= 0; i--) out.push(pts[i]);
    return out;
  }

  /* Mirror a downhill route so it climbs instead: used for the rare back edge. */
  function routeUp(A, B, rows, boxes, lanes) {
    var ax = A.x + A.w / 2, bx = B.x + B.w / 2;
    var c1 = chanAbove(rows, A.row), c2 = chanBelow(rows, B.row);
    var x = lanes.take((ax + bx) / 2, c2, c1);
    return [P(ax, A.y), P(ax, c1), P(x, c1), P(x, c2), P(bx, c2), P(bx, B.y + B.h)];
  }

  function makeLanes(contentW) {
    var right = [], left = [], mid = contentW / 2;
    return {
      minX: 0,
      maxX: contentW,
      take: function (want, y1, y2) {
        var lo = y1 < y2 ? y1 : y2, hi = y1 < y2 ? y2 : y1;
        var list = want >= mid ? right : left;
        var i, j, ok;
        for (i = 0; i < list.length; i++) {
          ok = true;
          for (j = 0; j < list[i].length; j++) {
            if (spans(lo, hi, list[i][j][0] - 8, list[i][j][1] + 8)) { ok = false; break; }
          }
          if (ok) { list[i].push([lo, hi]); return list[i].x; }
        }
        var band = [];
        band.push([lo, hi]);
        band.x = (want >= mid ? contentW + 22 + list.length * LANE : -22 - list.length * LANE);
        list.push(band);
        if (band.x > this.maxX) this.maxX = band.x;
        if (band.x < this.minX) this.minX = band.x;
        return band.x;
      }
    };
  }

  // ------------------------------------------------------------------ drawing

  function tidy(pts) {
    var out = [], i, p;
    for (i = 0; i < pts.length; i++) {
      p = pts[i];
      if (out.length && Math.abs(out[out.length - 1].x - p.x) < 0.4 &&
          Math.abs(out[out.length - 1].y - p.y) < 0.4) continue;
      out.push(p);
    }
    // drop collinear middles so the corner rounding never sees a zero-length arm
    var res = [out[0]], j;
    for (j = 1; j < out.length - 1; j++) {
      var a = res[res.length - 1], b = out[j], c = out[j + 1];
      var col = (Math.abs(a.x - b.x) < 0.4 && Math.abs(b.x - c.x) < 0.4) ||
                (Math.abs(a.y - b.y) < 0.4 && Math.abs(b.y - c.y) < 0.4);
      if (!col) res.push(b);
    }
    if (out.length > 1) res.push(out[out.length - 1]);
    return res;
  }

  function polyD(pts) {
    var R = D.round, i, d;
    if (pts.length < 2) return '';
    d = 'M' + R(pts[0].x) + ',' + R(pts[0].y);
    for (i = 1; i < pts.length - 1; i++) {
      var a = pts[i - 1], b = pts[i], c = pts[i + 1];
      var la = Math.abs(b.x - a.x) + Math.abs(b.y - a.y);
      var lc = Math.abs(c.x - b.x) + Math.abs(c.y - b.y);
      var r = Math.min(CORNER, la / 2, lc / 2);
      var p1 = P(b.x + (a.x - b.x) * (la ? r / la : 0), b.y + (a.y - b.y) * (la ? r / la : 0));
      var p2 = P(b.x + (c.x - b.x) * (lc ? r / lc : 0), b.y + (c.y - b.y) * (lc ? r / lc : 0));
      d += ' L' + R(p1.x) + ',' + R(p1.y) + ' Q' + R(b.x) + ',' + R(b.y) + ' ' + R(p2.x) + ',' + R(p2.y);
    }
    d += ' L' + R(pts[pts.length - 1].x) + ',' + R(pts[pts.length - 1].y);
    return d;
  }

  function fracPoint(pts, f) {
    var total = 0, segs = [], i, L;
    for (i = 1; i < pts.length; i++) {
      L = Math.abs(pts[i].x - pts[i - 1].x) + Math.abs(pts[i].y - pts[i - 1].y);
      segs.push(L);
      total += L;
    }
    var want = total * f, acc = 0, t;
    for (i = 0; i < segs.length; i++) {
      if (acc + segs[i] >= want) {
        t = segs[i] ? (want - acc) / segs[i] : 0;
        return P(pts[i].x + (pts[i + 1].x - pts[i].x) * t, pts[i].y + (pts[i + 1].y - pts[i].y) * t);
      }
      acc += segs[i];
    }
    return pts[pts.length - 1];
  }

  function lerp(a, b, t) { return P(a.x + (b.x - a.x) * t, a.y + (b.y - a.y) * t); }

  /* Where a relationship label could sit, best first. A fan of edges leaving one
     class shares its first vertical, so the arc midpoint would stack every label
     in the same spot; the middle of the longest leg spreads them out instead. */
  function anchorsFor(pts) {
    var out = [], i, k, best = -1, bl = 0, L;
    for (i = 1; i < pts.length; i++) {
      L = Math.abs(pts[i].x - pts[i - 1].x) + Math.abs(pts[i].y - pts[i - 1].y);
      if (L > bl) { bl = L; best = i; }
    }
    var ts = [0.5, 0.36, 0.64, 0.26, 0.74];
    if (best > 0 && bl > 34) {
      for (i = 0; i < ts.length; i++) out.push(lerp(pts[best - 1], pts[best], ts[i]));
    }
    out.push(fracPoint(pts, 0.5));
    for (i = 1; i < pts.length; i++) {                       // middle of every leg
      L = Math.abs(pts[i].x - pts[i - 1].x) + Math.abs(pts[i].y - pts[i - 1].y);
      if (i !== best && L > 26) out.push(lerp(pts[i - 1], pts[i], 0.5));
    }
    for (k = 2; k <= 8; k++) out.push(fracPoint(pts, k / 10));  // last resort sweep
    return out;
  }

  function labelBox(text) {
    var lines = D.wrapText(text, LBL_SIZE, LBL_MAXW);
    var lh = LBL_SIZE * 1.28;
    return { w: D.maxWidth(lines, LBL_SIZE) + 12, h: lines.length * lh + 5 };
  }

  function area(a1, a2, b1, b2) {
    var v = (a2 < b2 ? a2 : b2) - (a1 > b1 ? a1 : b1);
    return v > 0 ? v : 0;
  }

  /* How bad a label would be at (x,y): overlap with labels already placed, and
     with class boxes, which is worse because it hides real content. */
  function penalty(x, y, w, h, taken, nodes) {
    var i, t, p = 0;
    var x1 = x - w / 2, x2 = x + w / 2, y1 = y - h / 2, y2 = y + h / 2;
    for (i = 0; i < taken.length; i++) {
      t = taken[i];
      p += area(x1, x2, t.x - t.w / 2, t.x + t.w / 2) * area(y1, y2, t.y - t.h / 2, t.y + t.h / 2);
    }
    for (i = 0; i < nodes.length; i++) {
      t = nodes[i];
      p += 2 * area(x1, x2, t.x + 3, t.x + t.w - 3) * area(y1, y2, t.y + 3, t.y + t.h - 3);
    }
    return p;
  }

  function drawBox(n) {
    var out = '', cx = n.x + n.w / 2, y = n.y + HPAD_TOP, i;
    var isAbstract = n.stereo && /^(abstract|isAbstract|interface|protocol)$/i.test(n.stereo);
    var enumish = n.stereo && /^enum/i.test(n.stereo);

    out += D.rect(n.x, n.y, n.w, n.h, { rx: 9, fill: D.C.node, stroke: isAbstract ? D.C.accent : D.C.line });
    for (i = 0; i < n.nameLines.length; i++) {
      out += D.text(cx, y + NAME_SIZE * 0.8, n.nameLines[i],
                    { size: NAME_SIZE, weight: 600, fill: isAbstract ? D.C.accent : D.C.text });
      y += NAME_LH;
    }
    if (n.stereo) {
      out += D.text(cx, y + STER_SIZE * 0.82, '<<' + n.stereo + '>>',
                    { size: STER_SIZE, fill: D.C.dim, italic: true });
      y += STER_LH;
    }

    var tx = n.x + PADX, top = n.y + n.hdr, k;
    function compartment(list, startY) {
      var s = D.el('line', { x1: n.x, y1: startY, x2: n.x + n.w, y2: startY,
                             stroke: D.C.line, 'stroke-width': 1 });
      var yy = startY + CPAD;
      for (k = 0; k < list.length; k++) {
        var bare = !/^[+\-#~]/.test(list[k]) && list[k].charAt(0) !== ' ';
        s += D.text(tx, yy + MEM_SIZE * 0.82, list[k], {
          size: MEM_SIZE, mono: true, anchor: 'start',
          fill: (bare && !enumish) ? D.C.dim : D.C.text
        });
        yy += MEM_LH;
      }
      return s;
    }
    if (n.fLines.length) { out += compartment(n.fLines, top); top += n.fH; }
    if (n.mLines.length) { out += compartment(n.mLines, top); }
    return out;
  }

  // -------------------------------------------------------------------- entry

  D.renderers.classDiagram = function (lines, head) {
    var model = parse(lines);
    var nodes = model.nodes, edges = model.edges, i, j, e, n;

    for (i = 0; i < nodes.length; i++) measure(nodes[i]);

    // core's layered pass is used for one thing only: marking the edges that close
    // a cycle, so the layer maths below cannot spin. Its placement is then redone
    // here, because a phone needs rows that wrap.
    D.layered(nodes, edges, {});

    var layers = assignLayers(nodes, edges);
    var pl = place(layers);
    var rows = pl.rows;
    var lanes = makeLanes(pl.contentW);

    var minX = 0, maxX = pl.contentW, minY = 0, maxY = pl.contentH;
    function note(x, y) {
      if (x < minX) minX = x;
      if (x > maxX) maxX = x;
      if (y < minY) minY = y;
      if (y > maxY) maxY = y;
    }

    // edges first, boxes over them, labels last: an arrowhead touching a border
    // then reads as touching it, not as poking into the box.
    var body = '', boxes = '', later = '', taken = [];
    for (i = 0; i < nodes.length; i++) boxes += drawBox(nodes[i]);

    /* A multiplicity hugs its own end of the line. Several edges routinely share an
       endpoint - every composition into one class arrives at the same point - so the
       spot is scored against what is already on the page rather than being fixed:
       otherwise two "many"s land on the identical pixel and one is simply lost, or a
       later edge's opaque label chip is painted straight over it. */
    function card(str, p, q) {
      var cw = D.textWidth(str, CARD_SIZE) + 4, ch = CARD_SIZE + 3;
      var dir = q.y > p.y ? 1 : -1;                 // does the line leave p going down?
      var cands = [], k, dy, i, pen;
      for (k = 0; k < 4; k++) {
        dy = (dir > 0 ? 13 : -6) + dir * k * (ch + 3);
        cands.push(P(p.x + 7, p.y + dy));
        cands.push(P(p.x - 7 - cw, p.y + dy));
      }
      var best = cands[0], bp = -1;
      for (i = 0; i < cands.length; i++) {
        pen = penalty(cands[i].x + cw / 2, cands[i].y - CARD_SIZE * 0.4, cw, ch, taken, nodes) + i * 0.4;
        if (bp < 0 || pen < bp) { bp = pen; best = cands[i]; }
        if (bp <= i * 0.4) break;                   // already clear of everything
      }
      later += D.text(best.x, best.y, str, { size: CARD_SIZE, fill: D.C.dim, anchor: 'start' });
      taken.push({ x: best.x + cw / 2, y: best.y - CARD_SIZE * 0.4, w: cw, h: ch });
      note(best.x + cw, best.y + 4);
      note(best.x, best.y - CARD_SIZE);
    }

    for (i = 0; i < edges.length; i++) {
      e = edges[i];
      var A = e.up, B = e.down;
      var pts;
      if (A === B) {
        var loop = D.selfLoop(A, { out: 30 });
        later += D.path(loop.d, { stroke: D.C.dim, dash: e.dash ? '5 4' : null, markerEnd: e.mk || null });
        note(A.x + A.w + 44, loop.mid.y);
        if (e.label) {
          var slb = labelBox(e.label), sx = loop.mid.x + 26;
          later += D.edgeLabel(sx, loop.mid.y, e.label, { maxWidth: LBL_MAXW });
          taken.push({ x: sx, y: loop.mid.y, w: slb.w + 6, h: slb.h + 4 });
          note(sx - slb.w / 2, loop.mid.y - slb.h / 2);
          note(sx + slb.w / 2, loop.mid.y + slb.h / 2);
        }
        continue;
      }
      if (A.row < B.row) pts = routeDown(A, B, rows, nodes, lanes);
      else if (A.row > B.row) pts = routeUp(A, B, rows, nodes, lanes);
      else pts = routeSide(A, B, rows, lanes);
      pts = tidy(pts);
      if (pts.length < 2) continue;

      // cardinalities hug their own end of the line, before any reversal
      var p0 = pts[0], p1 = pts[1], pz = pts[pts.length - 1], py = pts[pts.length - 2];
      if (e.upCard) card(e.upCard, p0, p1);
      if (e.downCard) card(e.downCard, pz, py);

      var draw = e.at === 'up' ? reverse(pts) : pts;
      body += D.path(polyD(draw), {
        stroke: D.C.dim, sw: 1.3,
        dash: e.dash ? '5 4' : null,
        markerEnd: e.mk || null
      });
      for (j = 0; j < pts.length; j++) note(pts[j].x, pts[j].y);

      if (e.label) {
        var lb = labelBox(e.label);
        var cands = anchorsFor(pts), spot = cands[0], bestP = -1, pen;
        for (j = 0; j < cands.length; j++) {
          pen = penalty(cands[j].x, cands[j].y, lb.w, lb.h, taken, nodes) + j * 0.5;
          if (bestP < 0 || pen < bestP) { bestP = pen; spot = cands[j]; }
          if (bestP <= j * 0.5) break;                       // already clear
        }
        later += D.edgeLabel(spot.x, spot.y, e.label, { maxWidth: LBL_MAXW });
        taken.push({ x: spot.x, y: spot.y, w: lb.w + 6, h: lb.h + 4 });
        note(spot.x - lb.w / 2, spot.y - lb.h / 2);
        note(spot.x + lb.w / 2, spot.y + lb.h / 2);
      }
    }

    var w = maxX - minX, h = maxY - minY;
    var g = D.el('g', { transform: 'translate(' + D.round(-minX) + ',' + D.round(-minY) + ')' },
                 body + boxes + later);
    return D.frame(w, h, g, { pad: 14 });
  };
})();
