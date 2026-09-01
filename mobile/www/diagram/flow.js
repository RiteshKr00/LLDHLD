/* flowchart / graph  -  a top-down flow of steps, decisions and retry loops.
 *
 * Layout: D.layered() gives the layer assignment, the in-row ordering and the
 * cycle break; everything below is the routing on top of it.
 *
 *   - a step is a box, a decision is a real rhombus sized so its text fits inside
 *   - forward edges leave the bottom of a node and enter the top of the next one,
 *     turning inside the clear band between the two rows
 *   - an edge that skips layers (an error branch rejoining at the end) is routed
 *     down a side lane clear of every box instead of cutting through the middle
 *   - the edge closing a cycle (a retry loop) comes back up a gutter on the right
 *   - branch labels are chips placed on their own edge, nudged along it until they
 *     collide with nothing
 *
 * ES5 only, no DOM, no measuring: string in, SVG string out.
 */
(function () {
  'use strict';

  var D = window.LLDD;
  if (!D || !D.renderers) return;

  // ------------------------------------------------------------------ metrics

  var SIZE = 13;                    // text inside a node
  var LH = SIZE * 1.32;
  var ESIZE = 11;                   // text on an edge
  var PADX = 14, PADY = 11;         // padding inside a box
  var DIA_PADX = 11, DIA_PADY = 20; // clearance from the text to the rhombus edge
  var NODE_MAXW = 220;              // wrap width inside a box
  var DIA_MAXW = 145;               // wrap width inside a rhombus (they cost width)
  var LABEL_MAXW = 76;              // narrow: two branch chips must fit side by side
  var HGAP = 32;                    // between siblings in a row
  var VGAP_MIN = 54;                // between rows
  var CORNER = 9;                   // elbow radius
  var LANE = 30;                    // side lane for a layer-skipping edge
  var GUTTER = 28;                  // return lane for a back edge

  function trim(s) { return String(s == null ? '' : s).replace(/^\s+|\s+$/g, ''); }
  function rr(v) { return D.round(v); }

  // ------------------------------------------------------------------ parsing

  /* prefix, suffix, shape - longest pairs first so "((x))" wins over "(x)" */
  var SHAPES = [
    ['((', '))', 'circle'],
    ['([', '])', 'round'],
    ['[[', ']]', 'rect'],
    ['[(', ')]', 'round'],
    ['{{', '}}', 'rect'],
    ['[/', '/]', 'rect'],
    ['[', ']', 'rect'],
    ['{', '}', 'diamond'],
    ['(', ')', 'round'],
    ['>', ']', 'rect']
  ];

  /* -->  -.->  ==>  ---  : only ever recognised at bracket depth 0, so the ">="
     in "{len map >= capacity?}" cannot be mistaken for part of a link. */
  var ARROW_RX = /^(?:-{2,}>|-\.+-*>|={2,}>|-{3,}|-\.+-)/;

  /* mermaid's other way of labelling a link, "A-- text -->B" / "A== text ==>B" /
     "A-. text .->B". Tried only after ARROW_RX has failed, and only at depth 0, so a
     plain "-->" still wins outright and a hyphen inside an id ("c-d") matches neither.
     Without this the label AND the source node's own bracket label are both lost. */
  var OPEN_RX = /^(?:-{2}|={2}|-\.)/;
  var CLOSE_RX = /(-{2,}>|={2,}>|\.-+>|\.-+|-{3,}|={3,})/;

  /* What the link looks like: mermaid's dots mean dashed and "---" means no
     arrowhead at all, so drawing every link as a solid arrow loses the distinction. */
  var PLAIN = { dash: null, arrow: true, sw: 1.4 };

  function linkKind(tok) {
    return {
      dash: tok.indexOf('.') >= 0 ? '5 4' : null,
      arrow: tok.charAt(tok.length - 1) === '>',
      sw: tok.indexOf('=') >= 0 ? 2.2 : 1.4
    };
  }

  function tokenize(line) {
    var segs = [], arrows = [], kinds = [], buf = '', depth = 0, quoted = false;
    var i = 0, m, mo, mc, j, k, lab, rest, after;
    while (i < line.length) {
      var c = line.charAt(i);
      if (c === '"') { quoted = !quoted; buf += c; i++; continue; }
      if (!quoted && depth === 0 && (c === '-' || c === '=')) {
        rest = line.slice(i);
        m = ARROW_RX.exec(rest);
        if (m) {
          segs.push(buf);
          buf = '';
          i += m[0].length;
          lab = null;
          j = i;
          while (j < line.length && line.charAt(j) === ' ') j++;
          if (line.charAt(j) === '|') {
            k = line.indexOf('|', j + 1);
            if (k > 0) { lab = line.slice(j + 1, k); i = k + 1; }
          }
          arrows.push(lab);
          kinds.push(linkKind(m[0]));
          continue;
        }
        mo = OPEN_RX.exec(rest);
        if (mo) {
          after = rest.slice(mo[0].length);
          mc = CLOSE_RX.exec(after);
          if (mc && mc.index > 0) {
            segs.push(buf);
            buf = '';
            arrows.push(trim(after.slice(0, mc.index)) || null);
            kinds.push(linkKind(mo[0] + mc[0]));
            i += mo[0].length + mc.index + mc[0].length;
            continue;
          }
        }
      }
      if (!quoted) {
        if (c === '[' || c === '{' || c === '(') depth++;
        else if (c === ']' || c === '}' || c === ')') { if (depth > 0) depth--; }
      }
      buf += c;
      i++;
    }
    segs.push(buf);
    return { segs: segs, arrows: arrows, kinds: kinds };
  }

  /* Node ids come from the note, so a map lookup must never reach Object.prototype
     ("toString" is a legal mermaid id). Call through Object.prototype rather than the
     map: a node called "hasOwnProperty" shadows the method on the map itself. */
  var hasOwn = Object.prototype.hasOwnProperty;

  function own(map, k) {
    return hasOwn.call(map, k) ? map[k] : null;
  }

  function addNode(G, id, label, shape) {
    var n = own(G.byId, id);
    if (!n) {
      n = { id: id, label: label === null ? id : label,
            shape: shape || 'rect', named: label !== null };
      G.byId[id] = n;
      G.nodes.push(n);
    } else if (label !== null && !n.named) {
      // the first definition carries the label; a bare mention just reuses it
      n.label = label;
      if (shape) n.shape = shape;
      n.named = true;
    }
    return n;
  }

  function parseSeg(G, txt) {
    var t = trim(txt);
    if (!t) return null;
    var m = /^([A-Za-z0-9_.\-]+)\s*/.exec(t);
    if (!m) return null;
    var rest = trim(t.slice(m[0].length));
    var label = null, shape = null, i, pre, suf;
    for (i = 0; i < SHAPES.length && rest; i++) {
      pre = SHAPES[i][0];
      suf = SHAPES[i][1];
      if (rest.slice(0, pre.length) === pre &&
          rest.length >= pre.length + suf.length &&
          rest.slice(rest.length - suf.length) === suf) {
        label = D.label(rest.slice(pre.length, rest.length - suf.length));
        shape = SHAPES[i][2];
        break;
      }
    }
    return addNode(G, m[1], label, shape);
  }

  function parseStyle(s) {
    var out = {}, parts = String(s).split(','), i, kv, k, v;
    for (i = 0; i < parts.length; i++) {
      kv = parts[i].split(':');
      if (kv.length < 2) continue;
      k = trim(kv[0]).toLowerCase();
      v = trim(kv.slice(1).join(':'));
      if (!v) continue;
      if (k === 'fill') out.fill = v;
      else if (k === 'color') out.color = v;
      else if (k === 'stroke') out.stroke = v;
    }
    return out;
  }

  var SKIP_RX = /^(subgraph|end|direction|click|linkStyle|classDef|class)\b/;

  function parse(lines) {
    var G = { nodes: [], byId: {}, edges: [], styles: {} }, i, p, st, tk, prev, node, line;
    for (i = 1; i < lines.length; i++) {
      line = lines[i];
      st = /^style\s+([A-Za-z0-9_.\-]+)\s+(.+)$/.exec(line);
      if (st) { G.styles[st[1]] = parseStyle(st[2]); continue; }
      if (SKIP_RX.test(line)) continue;   // containers flattened, decoration ignored
      tk = tokenize(line);
      prev = null;
      for (p = 0; p < tk.segs.length; p++) {
        node = parseSeg(G, tk.segs[p]);
        if (node && prev) {
          G.edges.push({ from: prev.id, to: node.id,
                         label: tk.arrows[p - 1] || null,
                         kind: tk.kinds[p - 1] || PLAIN });
        }
        if (node) prev = node;
      }
    }
    for (i = 0; i < G.nodes.length; i++) {
      if (own(G.styles, G.nodes[i].id)) G.nodes[i].style = G.styles[G.nodes[i].id];
    }
    return G;
  }

  // ------------------------------------------------------------------- sizing

  function size(n) {
    var maxw = n.shape === 'diamond' ? DIA_MAXW : NODE_MAXW;
    n.lines = D.wrapText(n.label, SIZE, maxw);
    var tw = D.maxWidth(n.lines, SIZE);
    var th = n.lines.length * LH;
    if (n.shape === 'diamond') {
      /* A tw x th rectangle only fits inside a W x H rhombus when
         W >= (tw + 2*pad) * H / (H - th) - the sloping sides eat the width. */
      var h = th + 2 * DIA_PADY;
      n.w = Math.ceil((tw + 2 * DIA_PADX) * h / (h - th));
      n.h = Math.ceil(h);
      if (n.w < 92) n.w = 92;
    } else {
      n.w = Math.ceil(tw + 2 * PADX);
      n.h = Math.ceil(th + 2 * PADY);
      if (n.shape === 'circle') { n.w += 14; n.h += 8; }
      if (n.w < 76) n.w = 76;
      if (n.h < 38) n.h = 38;
    }
  }

  function chipSize(text) {
    var ls = D.wrapText(text, ESIZE, LABEL_MAXW);
    var lh = ESIZE * 1.28;
    return { w: D.maxWidth(ls, ESIZE) + 12, h: ls.length * lh + 5 };
  }

  // ------------------------------------------------------------------ drawing

  function len(a, b) {
    var dx = b.x - a.x, dy = b.y - a.y;
    return Math.sqrt(dx * dx + dy * dy);
  }

  function toward(from, to, dist) {
    var l = len(from, to);
    if (l < 0.001) return { x: from.x, y: from.y };
    return { x: from.x + (to.x - from.x) * dist / l,
             y: from.y + (to.y - from.y) * dist / l };
  }

  /** An orthogonal polyline with rounded corners. Degenerate points are dropped. */
  function poly(pts) {
    var p = [], i, q, last;
    for (i = 0; i < pts.length; i++) {
      q = pts[i];
      last = p.length ? p[p.length - 1] : null;
      if (last && Math.abs(last.x - q.x) < 0.6 && Math.abs(last.y - q.y) < 0.6) continue;
      p.push({ x: q.x, y: q.y });
    }
    if (p.length < 2) return '';
    var d = 'M' + rr(p[0].x) + ',' + rr(p[0].y), a, c, b, r, p1, p2;
    for (i = 1; i < p.length - 1; i++) {
      a = p[i - 1];
      c = p[i];
      b = p[i + 1];
      r = Math.min(CORNER, len(a, c) / 2, len(c, b) / 2);
      p1 = toward(c, a, r);
      p2 = toward(c, b, r);
      d += ' L' + rr(p1.x) + ',' + rr(p1.y) +
           ' Q' + rr(c.x) + ',' + rr(c.y) + ' ' + rr(p2.x) + ',' + rr(p2.y);
    }
    d += ' L' + rr(p[p.length - 1].x) + ',' + rr(p[p.length - 1].y);
    return d;
  }

  function diamondPath(n) {
    var cx = n.x + n.w / 2, cy = n.y + n.h / 2;
    return 'M' + rr(cx) + ',' + rr(n.y) +
           ' L' + rr(n.x + n.w) + ',' + rr(cy) +
           ' L' + rr(cx) + ',' + rr(n.y + n.h) +
           ' L' + rr(n.x) + ',' + rr(cy) + ' Z';
  }

  /* A note's own "style ... fill:#5c1a1a" can be darker or lighter than the theme,
     so pick a readable text colour when the note did not name one. */
  function contrast(hex) {
    var h = trim(hex).replace(/^#/, '');
    if (h.length === 3) {
      h = h.charAt(0) + h.charAt(0) + h.charAt(1) + h.charAt(1) + h.charAt(2) + h.charAt(2);
    }
    if (!/^[0-9a-fA-F]{6}$/.test(h)) return null;
    var r = parseInt(h.slice(0, 2), 16),
        g = parseInt(h.slice(2, 4), 16),
        b = parseInt(h.slice(4, 6), 16);
    return (0.299 * r + 0.587 * g + 0.114 * b) > 150 ? '#101418' : '#ffffff';
  }

  function drawNode(n) {
    var st = n.style || {};
    var fill = st.fill || (n.shape === 'diamond' ? D.C.node2 : D.C.node);
    var stroke = st.stroke || D.C.line;
    var color = st.color || (st.fill ? contrast(st.fill) : null) || D.C.text;
    var out, rx;
    if (n.shape === 'diamond') {
      out = D.path(diamondPath(n), { fill: fill, stroke: stroke, sw: 1.2 });
    } else {
      rx = n.shape === 'circle' ? n.h / 2 : (n.shape === 'round' ? Math.min(n.h / 2, 18) : 8);
      out = D.rect(n.x, n.y, n.w, n.h, { rx: rx, fill: fill, stroke: stroke });
    }
    return out + D.textBlock(n.x + n.w / 2, n.y + n.h / 2, n.lines,
                             { size: SIZE, fill: color, lh: LH });
  }

  // ----------------------------------------------------------- label placement

  function hits(r, list) {
    for (var i = 0; i < list.length; i++) {
      var o = list[i];
      if (r.x < o.x + o.w + 2 && o.x < r.x + r.w + 2 &&
          r.y < o.y + o.h + 2 && o.y < r.y + r.h + 2) return true;
    }
    return false;
  }

  /* Candidate spots for a chip, as [segment index, fraction along it] pairs read
     off the edge's own polyline - so wherever it ends up it still sits on its line. */
  function segCands(pts, order) {
    var out = [], i, si, t, a, b;
    for (i = 0; i < order.length; i++) {
      si = order[i][0];
      t = order[i][1];
      if (si < 0) si += pts.length - 1;
      if (si < 0 || si + 1 >= pts.length) continue;
      a = pts[si];
      b = pts[si + 1];
      if (Math.abs(a.x - b.x) < 0.6 && Math.abs(a.y - b.y) < 0.6) continue;
      out.push({ x: a.x + (b.x - a.x) * t, y: a.y + (b.y - a.y) * t });
    }
    if (!out.length) out.push({ x: pts[0].x, y: pts[0].y });
    return out;
  }

  /** Candidates for a path with no obvious "middle": longest segments first. */
  function autoCands(pts) {
    var segs = [], order = [], i;
    for (i = 0; i + 1 < pts.length; i++) segs.push({ i: i, L: len(pts[i], pts[i + 1]) });
    segs.sort(function (a, b) { return b.L - a.L; });
    for (i = 0; i < segs.length; i++) order.push([segs[i].i, 0.5]);
    for (i = 0; i < segs.length; i++) order.push([segs[i].i, 0.3]);
    for (i = 0; i < segs.length; i++) order.push([segs[i].i, 0.7]);
    return segCands(pts, order);
  }

  function chipRect(at, chip) {
    return { x: at.x - chip.w / 2, y: at.y - chip.h / 2, w: chip.w, h: chip.h };
  }

  /** First candidate point along the edge where the chip touches nothing. */
  function place(cands, chip, taken) {
    for (var i = 0; i < cands.length; i++) {
      var r = chipRect(cands[i], chip);
      if (!hits(r, taken)) return { at: cands[i], rect: r };
    }
    return { at: cands[0], rect: chipRect(cands[0], chip) };
  }

  // ------------------------------------------------------------------- render

  D.renderers.flowchart = function (lines, head) {
    var G = parse(lines);
    if (!G.nodes.length) throw new Error('flowchart: no nodes in ' + String(head).slice(0, 24));

    var i, j, k, e, n;
    for (i = 0; i < G.nodes.length; i++) size(G.nodes[i]);

    var maxChip = 0;
    for (i = 0; i < G.edges.length; i++) {
      e = G.edges[i];
      if (!e.label) continue;
      e.chip = chipSize(e.label);
      if (e.chip.h > maxChip) maxChip = e.chip.h;
    }
    var vGap = Math.max(VGAP_MIN, maxChip + 30);

    var lay = D.layered(G.nodes, G.edges, { vGap: vGap, hGap: HGAP });

    // the clear horizontal band between two rows: every turn happens inside one
    var rowTop = [], rowBot = [];
    for (i = 0; i < lay.layers.length; i++) {
      var t = 1e9, b = -1e9;
      for (j = 0; j < lay.layers[i].length; j++) {
        n = lay.layers[i][j];
        if (n.y < t) t = n.y;
        if (n.y + n.h > b) b = n.y + n.h;
      }
      rowTop.push(t);
      rowBot.push(b);
    }
    function band(li) {
      if (li + 1 < rowTop.length) return (rowBot[li] + rowTop[li + 1]) / 2;
      return rowBot[li] + vGap / 2;
    }

    var fwd = [], backs = [], selfs = [], na, nb;
    for (i = 0; i < G.edges.length; i++) {
      e = G.edges[i];
      na = own(G.byId, e.from);
      nb = own(G.byId, e.to);
      if (!na || !nb) continue;
      e.a = na;
      e.b = nb;
      if (na === nb) selfs.push(e);
      else if (e.back) backs.push(e);
      else fwd.push(e);
    }

    /* An edge that skips a layer would otherwise turn inside another row, so it
       gets a lane outside the boxes. A lane is reused when the spans are disjoint. */
    var lanesL = [], lanesR = [];
    for (i = 0; i < fwd.length; i++) {
      e = fwd[i];
      if (e.b.layer - e.a.layer <= 1) continue;
      var y0 = band(e.a.layer), y1 = e.b.y + e.b.h / 2;
      var left = (e.a.x + e.a.w / 2) <= lay.width / 2;
      var pool = left ? lanesL : lanesR;
      var idx = -1;
      for (j = 0; j < pool.length; j++) {
        var free = true;
        for (k = 0; k < pool[j].length; k++) {
          if (y0 < pool[j][k][1] - 2 && pool[j][k][0] < y1 - 2) { free = false; break; }
        }
        if (free) { idx = j; break; }
      }
      if (idx < 0) { pool.push([]); idx = pool.length - 1; }
      pool[idx].push([y0, y1]);
      e.lane = { side: left ? -1 : 1, idx: idx };
    }
    function laneX(l) {
      return l.side < 0 ? -(l.idx + 1) * LANE : lay.width + (l.idx + 1) * LANE;
    }

    /* Two lanes arriving at the same box would otherwise land on the same point and
       draw their last run on top of each other: spread them down its side instead. */
    var arrive = {}, key, grp, step;
    for (i = 0; i < fwd.length; i++) {
      e = fwd[i];
      if (!e.lane) continue;
      key = e.b.id + '|' + e.lane.side;
      if (!own(arrive, key)) arrive[key] = [];
      arrive[key].push(e);
    }
    for (key in arrive) {
      if (!hasOwn.call(arrive, key)) continue;
      grp = arrive[key];
      grp.sort(function (p, q) { return p.lane.idx - q.lane.idx; });
      step = Math.min(11, (grp[0].b.h - 14) / grp.length);
      for (i = 0; i < grp.length; i++) {
        grp[i].entryDY = grp.length > 1 ? (i - (grp.length - 1) / 2) * step : 0;
      }
    }
    var gutterBase = lay.width + lanesR.length * LANE + GUTTER;

    /* Every retry loop gets its own return gutter unless it can share one. */
    var backLanes = [];
    for (i = 0; i < backs.length; i++) {
      e = backs[i];
      var g0 = Math.min(e.a.y, e.b.y) - 4, g1 = Math.max(e.a.y + e.a.h, e.b.y + e.b.h) + 4;
      var gi = -1;
      for (j = 0; j < backLanes.length; j++) {
        var okg = true;
        for (k = 0; k < backLanes[j].length; k++) {
          if (g0 < backLanes[j][k][1] && backLanes[j][k][0] < g1) { okg = false; break; }
        }
        if (okg) { gi = j; break; }
      }
      if (gi < 0) { backLanes.push([]); gi = backLanes.length - 1; }
      backLanes[gi].push([g0, g1]);
      e.gidx = gi;
    }

    function rightmost(n) {
      var row = lay.layers[n.layer], q;
      for (q = 0; q < row.length; q++) if (row[q].x > n.x) return false;
      return true;
    }

    // is another box in the target's own row between the lane and the target?
    function blocked(node, side, y) {
      var row = lay.layers[node.layer], q, m;
      for (q = 0; q < row.length; q++) {
        m = row[q];
        if (m === node) continue;
        if (y <= m.y || y >= m.y + m.h) continue;
        if (side < 0 && m.x < node.x) return true;
        if (side > 0 && m.x > node.x) return true;
      }
      return false;
    }

    var obstacles = [];
    for (i = 0; i < G.nodes.length; i++) {
      n = G.nodes[i];
      obstacles.push({ x: n.x, y: n.y, w: n.w, h: n.h });
    }

    var draw = [];
    var minX = 0, maxX = lay.width, minY = 0, maxY = lay.height;
    function extend(x, y) {
      if (x < minX) minX = x;
      if (x > maxX) maxX = x;
      if (y < minY) minY = y;
      if (y > maxY) maxY = y;
    }
    /* Every routed point, not just the ones we remembered to name: a back edge that
       leaves the bottom of a node in the LAST row turns below every box, which is
       outside lay.height and would otherwise be clipped off the canvas. */
    function extendPts(pts) {
      for (var q = 0; q < pts.length; q++) extend(pts[q].x, pts[q].y);
    }

    for (i = 0; i < fwd.length; i++) {
      e = fwd[i];
      var exit = D.anchor(e.a, 'bottom');
      var by = band(e.a.layer);
      var pts, cands, top;
      if (e.lane) {
        var lx = laneX(e.lane);
        var ey = e.b.y + e.b.h / 2 + (e.entryDY || 0);
        extend(lx, by);
        if (!blocked(e.b, e.lane.side, ey)) {
          var ent = { x: e.lane.side < 0 ? e.b.x : e.b.x + e.b.w, y: ey };
          pts = [exit, { x: exit.x, y: by }, { x: lx, y: by }, { x: lx, y: ey }, ent];
          cands = segCands(pts, [[1, 0.5], [2, 0.22], [2, 0.5], [3, 0.5],
                                 [1, 0.3], [1, 0.72], [0, 0.6], [2, 0.78]]);
        } else {
          var by2 = band(e.b.layer - 1);
          top = D.anchor(e.b, 'top');
          pts = [exit, { x: exit.x, y: by }, { x: lx, y: by },
                 { x: lx, y: by2 }, { x: top.x, y: by2 }, top];
          cands = segCands(pts, [[1, 0.5], [2, 0.22], [2, 0.5], [3, 0.5], [4, 0.5],
                                 [1, 0.3], [0, 0.6], [2, 0.78]]);
        }
      } else {
        top = D.anchor(e.b, 'top');
        if (Math.abs(exit.x - top.x) < 3) {
          pts = [{ x: top.x, y: exit.y }, top];
          cands = segCands(pts, [[0, 0.5], [0, 0.72], [0, 0.3], [0, 0.86], [0, 0.14]]);
        } else {
          pts = [exit, { x: exit.x, y: by }, { x: top.x, y: by }, top];
          cands = segCands(pts, [[1, 0.5], [2, 0.55], [2, 0.8], [1, 0.28], [1, 0.72],
                                 [0, 0.6], [0, 0.85], [2, 0.3], [1, 0.12], [1, 0.88]]);
        }
      }
      extendPts(pts);
      draw.push({ d: poly(pts), cands: cands, label: e.label, chip: e.chip, kind: e.kind });
    }

    for (i = 0; i < backs.length; i++) {
      e = backs[i];
      var gx = gutterBase + e.gidx * GUTTER;
      extend(gx + 2, e.b.y);
      if (rightmost(e.a) && rightmost(e.b)) {
        // the clean case: both ends already face the gutter
        var bk = D.connectBack(e.a, e.b, gx);
        extend(gx + 2, D.anchor(e.a, 'right').y);
        extend(gx + 2, D.anchor(e.b, 'right').y);
        draw.push({ d: bk.d, label: e.label, chip: e.chip, kind: e.kind,
                    cands: [{ x: gx, y: bk.mid.y },
                            { x: gx, y: bk.mid.y - 28 },
                            { x: gx, y: bk.mid.y + 28 },
                            { x: gx, y: bk.mid.y - 56 },
                            { x: gx, y: bk.mid.y + 56 }] });
      } else {
        // a box sits between an end and the gutter: leave underneath, return on top
        var bp = [];
        if (rightmost(e.a)) {
          bp.push(D.anchor(e.a, 'right'));
        } else {
          var bx = D.anchor(e.a, 'bottom');
          bp.push(bx, { x: bx.x, y: band(e.a.layer) });
        }
        bp.push({ x: gx, y: bp[bp.length - 1].y });
        if (rightmost(e.b)) {
          var br = D.anchor(e.b, 'right');
          bp.push({ x: gx, y: br.y }, { x: br.x + 1.5, y: br.y });
        } else {
          var bt = D.anchor(e.b, 'top');
          var bby = e.b.layer > 0 ? band(e.b.layer - 1) : e.b.y - vGap / 2;
          bp.push({ x: gx, y: bby }, { x: bt.x, y: bby }, bt);
        }
        extendPts(bp);
        draw.push({ d: poly(bp), label: e.label, chip: e.chip, kind: e.kind,
                    cands: autoCands(bp) });
      }
    }

    for (i = 0; i < selfs.length; i++) {
      e = selfs[i];
      var sl = D.selfLoop(e.a, { out: 30 });
      /* The chip goes BESIDE the loop, not on it: centred on the curve it hides the
         whole loop and, on a narrow node, spills back over the box. */
      var sx = e.a.x + e.a.w + 30;
      var scw = e.chip ? e.chip.w : 40;
      var scx = sx + scw / 2 + 6;
      extend(sx + 4, e.a.y);
      extend(sx + 4, e.a.y + e.a.h);
      draw.push({ d: sl.d, label: e.label, chip: e.chip, kind: e.kind,
                  cands: [{ x: scx, y: sl.mid.y },
                          { x: scx, y: e.a.y - 14 },
                          { x: scx, y: e.a.y + e.a.h + 14 },
                          { x: scx + scw, y: sl.mid.y }] });
    }

    var edgeMarkup = '', labelMarkup = '', nodeMarkup = '', pl, kind;
    for (i = 0; i < draw.length; i++) {
      if (draw[i].d) {
        kind = draw[i].kind || PLAIN;
        edgeMarkup += D.path(draw[i].d, { stroke: D.C.dim, sw: kind.sw, dash: kind.dash,
                                          markerEnd: kind.arrow ? 'd-arrow' : null });
      }
    }
    for (i = 0; i < draw.length; i++) {
      if (!draw[i].label) continue;
      pl = place(draw[i].cands, draw[i].chip, obstacles);
      obstacles.push(pl.rect);
      extend(pl.rect.x, pl.rect.y);
      extend(pl.rect.x + pl.rect.w, pl.rect.y + pl.rect.h);
      labelMarkup += D.edgeLabel(pl.at.x, pl.at.y, draw[i].label,
                                 { size: ESIZE, maxWidth: LABEL_MAXW });
    }
    for (i = 0; i < G.nodes.length; i++) nodeMarkup += drawNode(G.nodes[i]);

    var body = D.el('g', { transform: 'translate(' + rr(-minX) + ',' + rr(-minY) + ')' },
                    edgeMarkup + nodeMarkup + labelMarkup);
    return D.frame(maxX - minX, maxY - minY, body);
  };
})();
