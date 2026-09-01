/* stateDiagram / stateDiagram-v2 renderer.
 *
 * Layout, in one paragraph: states become rounded boxes and are placed by the shared
 * layered() top-down engine, but each node is laid out in a *slot* as wide as the
 * widest label on an edge coming into it - so a transition label can sit centred on
 * the drop into its target without ever touching a sibling's label. Vertical gaps are
 * then recomputed boundary by boundary from the real height of the labels crossing
 * them, so a three-line label gets room and a bare arrow does not waste any.
 *
 * The right-hand margin is a set of lanes: self-transitions hang off the LEFT of their
 * state (the right side is needed for return paths), then one gutter per back edge,
 * then the notes column. That keeps "X --> X", "EXPIRED --> ACTIVE" and
 * "note right of HELD" from ever being drawn on top of one another.
 *
 * ES5/ES3 only - this file is exercised under Windows Script Host.
 */

(function () {
  'use strict';

  var D = window.LLDD;
  if (!D) return;

  var FS = 13;            // state name
  var LFS = 11;           // transition label
  var NFS = 12;           // note text
  var LH = LFS * 1.28;    // label line height - must match D.edgeLabel
  var NLH = 16;           // note line height
  var LMAX = 155;         // transition label wrap width
  var NMAX = 240;         // note wrap width
  var SMAX = 150;         // state name wrap width
  var PS = 20;            // bounding box of a [*] marker
  var LOOP = 28;          // self-transition bulge
  var LANE = 24;          // space between right-hand lanes

  function trim(s) { return String(s == null ? '' : s).replace(/^\s+|\s+$/g, ''); }
  function r(n) { return D.round(n); }

  /* Geometry of the chip D.edgeLabel will draw for this text. Kept in lockstep with
     that helper (same size, same wrap width, same line height) so the space reserved
     and the space used are the same number. */
  function chipOf(text) {
    var ls = D.wrapText(text, LFS, LMAX);
    return { w: D.maxWidth(ls, LFS) + 12, h: ls.length * LH + 5 };
  }

  function drawChip(cx, cy, text) {
    return D.edgeLabel(cx, cy, text, { size: LFS, maxWidth: LMAX });
  }

  // --------------------------------------------------------------------- parsing

  function parse(lines) {
    var st = {}, order = [], edges = [], notes = [];
    var endN = 0, i, m, t;

    function ensure(id, kind) {
      if (!st[id]) {
        st[id] = { id: id, label: id, kind: kind || 'state', kids: null };
        order.push(id);
      }
      if (kind && st[id].kind === 'state') st[id].kind = kind;
      return st[id];
    }

    /* "[*]" is the start marker when it is a source and a terminal marker when it is a
       target. One shared start (a machine has one entry point) but a separate terminal
       per incoming edge, so each ending sits directly under the state that reaches it
       instead of every branch converging on one far-away dot. */
    function nodeFor(token, isTarget) {
      if (token === '[*]' || token === '[ * ]') {
        if (isTarget) {
          endN++;
          ensure('@end' + endN, 'end');
          return '@end' + endN;
        }
        ensure('@start', 'start');
        return '@start';
      }
      ensure(token);
      return token;
    }

    function kidsOf(comp, raw) {
      var line = trim(raw), a = line.indexOf('-->'), parts, p, q, name;
      if (a > 0) parts = [trim(line.substring(0, a)), trim(line.substring(a + 3))];
      else parts = [line];
      for (p = 0; p < parts.length; p++) {
        name = parts[p];
        q = name.indexOf(':');
        if (q >= 0) name = trim(name.substring(0, q));
        if (!name || name === '[*]') continue;
        if (!/^[A-Za-z_][\w.-]*$/.test(name)) continue;
        var dup = false;
        for (q = 0; q < comp.kids.length; q++) if (comp.kids[q] === name) dup = true;
        if (!dup) comp.kids.push(name);
      }
    }

    for (i = 1; i < lines.length; i++) {
      t = lines[i];
      if (t === '}' || t === '{') continue;
      if (/^direction\b/i.test(t)) continue;
      if (/^(classDef|class|style|linkStyle|accTitle|accDescr)\b/.test(t)) continue;

      // note right|left of X   ...   end note
      m = t.match(/^note\s+(right|left)\s+of\s+([^\s:]+)\s*:?\s*(.*)$/i);
      if (m) {
        var body = [];
        if (trim(m[3])) {
          body.push(trim(m[3]));
        } else {
          i++;
          while (i < lines.length && !/^end(\s+note)?$/i.test(lines[i])) {
            body.push(lines[i]);
            i++;
          }
        }
        ensure(m[2]);
        notes.push({ target: m[2], side: m[1].toLowerCase(), lines: body });
        continue;
      }
      if (/^note\b/i.test(t)) continue;               // "note as N" and friends

      // state "long description" as X
      m = t.match(/^state\s+"([^"]*)"\s+as\s+([^\s{]+)/);
      if (m) { ensure(m[2]).label = D.label(m[1]); continue; }

      // composite:  state X {  ...  }
      m = t.match(/^state\s+([^\s{"]+)\s*\{\s*$/);
      if (m) {
        var comp = ensure(m[1], 'composite');
        comp.kind = 'composite';
        if (!comp.kids) comp.kids = [];
        var depth = 1;
        i++;
        while (i < lines.length && depth > 0) {
          var inner = lines[i];
          if (inner.indexOf('}') >= 0) {
            depth--;
            if (depth <= 0) break;
          }
          if (/\{\s*$/.test(inner)) depth++;
          kidsOf(comp, inner);
          i++;
        }
        continue;
      }

      // A --> B : label
      var ai = t.indexOf('-->');
      if (ai > 0) {
        var left = trim(t.substring(0, ai));
        var rest = t.substring(ai + 3);
        var ci = rest.indexOf(':');
        var to = ci >= 0 ? trim(rest.substring(0, ci)) : trim(rest);
        var lab = ci >= 0 ? D.label(rest.substring(ci + 1)) : '';
        if (!left || !to) continue;
        edges.push({ from: nodeFor(left, false), to: nodeFor(to, true), label: lab });
        continue;
      }

      // X : description
      var ci2 = t.indexOf(':');
      if (ci2 > 0) {
        var nid = trim(t.substring(0, ci2));
        if (/^[A-Za-z_][\w.-]*$/.test(nid)) { ensure(nid).label = D.label(t.substring(ci2 + 1)); continue; }
      }

      // a state on its own line
      if (/^[A-Za-z_][\w.-]*$/.test(t)) { ensure(t); continue; }
    }

    // ---- size every node ----
    var nodes = [], byId = {}, s, kw, z;
    for (i = 0; i < order.length; i++) {
      s = st[order[i]];
      var n = { id: s.id, kind: s.kind, label: s.label, tl: [], kids: s.kids || [] };
      if (s.kind === 'start' || s.kind === 'end') {
        n.bw = PS;
        n.bh = PS;
      } else if (s.kind === 'composite') {
        n.tl = D.wrapText(s.label, FS, SMAX);
        kw = 0;
        for (z = 0; z < n.kids.length; z++) {
          var cw = D.textWidth(n.kids[z], NFS);
          if (cw > kw) kw = cw;
        }
        n.bw = Math.max(104, D.maxWidth(n.tl, FS) + 34, kw + 40);
        n.bh = 30 + (n.kids.length ? n.kids.length * NLH + 14 : 16);
      } else {
        n.tl = D.wrapText(s.label, FS, SMAX);
        n.bw = Math.max(76, D.maxWidth(n.tl, FS) + 34);
        n.bh = Math.max(40, n.tl.length * 17 + 22);
      }
      nodes.push(n);
      byId[n.id] = n;
    }

    // drop edges whose endpoints somehow vanished
    var keep = [];
    for (i = 0; i < edges.length; i++) {
      if (byId[edges[i].from] && byId[edges[i].to]) keep.push(edges[i]);
    }

    return { nodes: nodes, edges: keep, notes: notes, byId: byId };
  }

  // ------------------------------------------------------------------- rendering

  D.renderers.stateDiagram = function (lines, head) {
    var i, j, k, e, n, row;

    var P = parse(lines);
    var nodes = P.nodes, edges = P.edges, notes = P.notes, byId = P.byId;
    if (!nodes.length) throw new Error('stateDiagram: no states found');

    /* An edge that clears two or more layers cannot be drawn straight down - the row
       in between is standing in the way, and a plain vertical would be painted through
       the middle of it. Mark those so they get routed round the side instead, like a
       return path but travelling downwards. Layer assignment is purely structural, so
       this answer is the same before and after the slot pass. */
    function markLong() {
      var a, g, ff, tt;
      for (a = 0; a < edges.length; a++) {
        g = edges[a];
        g.long = false;
        if (g.back || g.self) continue;
        ff = byId[g.from]; tt = byId[g.to];
        if (ff && tt && tt.layer - ff.layer >= 2) g.long = true;
      }
    }

    // -- pass 1: classify self / back / layer-skipping edges ----------------------
    for (i = 0; i < nodes.length; i++) { nodes[i].w = nodes[i].bw; nodes[i].h = nodes[i].bh; }
    D.layered(nodes, edges, { vGap: 46, hGap: LANE });
    markLong();

    // -- pass 2: widen each node's slot to fit the labels arriving at it ----------
    var slot = {};
    for (i = 0; i < nodes.length; i++) slot[nodes[i].id] = nodes[i].bw;
    for (i = 0; i < edges.length; i++) {
      e = edges[i];
      if (e.back || e.self || e.long || !e.label) continue;
      e.chip = chipOf(e.label);
      if (e.chip.w + 10 > slot[e.to]) slot[e.to] = e.chip.w + 10;
    }
    for (i = 0; i < nodes.length; i++) { nodes[i].w = slot[nodes[i].id]; nodes[i].h = nodes[i].bh; }
    var lay = D.layered(nodes, edges, { vGap: 46, hGap: LANE });
    var layers = lay.layers;
    markLong();

    // shrink each node back to its real box, centred inside its slot
    for (i = 0; i < nodes.length; i++) {
      n = nodes[i];
      n.x = n.x + (n.w - n.bw) / 2;
      n.w = n.bw;
    }

    // -- terminal markers sit directly under the state that reaches them ----------
    var parentOf = {};
    for (i = 0; i < edges.length; i++) {
      e = edges[i];
      if (!e.back && !e.self) parentOf[e.to] = e.from;
    }
    for (i = 0; i < nodes.length; i++) {
      n = nodes[i];
      if (n.kind !== 'end') continue;
      var par = byId[parentOf[n.id]];
      if (!par) continue;
      var tx = par.x + par.w / 2 - n.w / 2;
      var clear = true;
      for (j = 0; j < nodes.length; j++) {
        var o = nodes[j];
        if (o === n || o.layer !== n.layer) continue;
        if (tx < o.x + o.w + 14 && o.x < tx + n.w + 14) { clear = false; break; }
      }
      if (clear) n.x = tx;
    }

    // -- vertical gaps sized from the labels that cross them ---------------------
    function rowTop(rw) { var v = 1e9, a; for (a = 0; a < rw.length; a++) if (rw[a].y < v) v = rw[a].y; return v; }
    function rowBot(rw) { var v = -1e9, a; for (a = 0; a < rw.length; a++) if (rw[a].y + rw[a].h > v) v = rw[a].y + rw[a].h; return v; }

    function isStraight(f, t) {
      return Math.abs((f.x + f.w / 2) - (t.x + t.w / 2)) < 1.5;
    }

    /* Two states merging into a third both want the same patch of canvas for their
       label - the drop into the shared target - and would be painted one on top of the
       other. Where a target has more than one labelled edge arriving, the labels are
       stacked into a column above it instead: "stackO" is how far above the base each
       chip sits, "stackH" the height of the whole column, which is what the vertical
       gap below has to clear. A target with a single arrival keeps "stackO" undefined
       and is placed exactly as before. */
    var CHIPGAP = 5;
    for (i = 0; i < edges.length; i++) {
      e = edges[i];
      if (e.back || e.self || e.long || !e.label || e.stackO !== undefined) continue;
      var grp = [], g2;
      for (j = 0; j < edges.length; j++) {
        g2 = edges[j];
        if (g2.back || g2.self || g2.long || !g2.label) continue;
        if (g2.to === e.to) grp.push(g2);
      }
      if (grp.length < 2) continue;
      var off = 0;
      for (j = 0; j < grp.length; j++) {
        if (!grp[j].chip) grp[j].chip = chipOf(grp[j].label);
        grp[j].stackO = off;
        off += grp[j].chip.h + CHIPGAP;
      }
      off -= CHIPGAP;
      for (j = 0; j < grp.length; j++) grp[j].stackH = off;
    }

    for (k = 1; k < layers.length; k++) {
      var need = 46;
      for (i = 0; i < edges.length; i++) {
        e = edges[i];
        if (e.back || e.self || e.long) continue;
        var f = byId[e.from], t2 = byId[e.to];
        if (!f || !t2 || f.layer !== k - 1 || t2.layer !== k) continue;
        var req = 46;
        if (e.label) {
          if (!e.chip) e.chip = chipOf(e.label);
          /* straight: the chip sits on the middle of the line.
             elbow: the chip sits on the drop into the target, so the sideways run
             of the elbow (at the half-way mark) has to clear the top of the chip.
             A stacked column has to clear the whole column, not just this one chip. */
          var H = e.stackH === undefined ? e.chip.h : e.stackH;
          req = isStraight(f, t2) ? (H + 26) : (2 * H + 30);
        }
        if (req > need) need = req;
      }
      var dy = rowBot(layers[k - 1]) + need - rowTop(layers[k]);
      row = layers[k];
      for (j = 0; j < row.length; j++) row[j].y += dy;
    }

    /* Everything below is a pure function of the node coordinates, so painting it
       once tells us the true extent, and painting it again after sliding the nodes
       puts the whole drawing at the origin. Baking the offset into the coordinates
       (rather than wrapping the result in a transform) keeps the emitted geometry
       honest - a checker reading the raw x/y of a rect sees where it really is. */
    var art = paint();
    if (art.bb.x0 < -0.01 || art.bb.y0 < -0.01) {
      for (i = 0; i < nodes.length; i++) {
        nodes[i].x -= art.bb.x0;
        nodes[i].y -= art.bb.y0;
      }
      art = paint();
    }
    return D.frame(art.bb.x1 - art.bb.x0, art.bb.y1 - art.bb.y0,
      art.wires + art.boxes + art.chips);

  function paint() {
    var i, j, k, e, n, row;

    var bb = { x0: 0, y0: 0, x1: 1, y1: 1 };
    function bump(x0, y0, x1, y1) {
      if (x0 < bb.x0) bb.x0 = x0;
      if (y0 < bb.y0) bb.y0 = y0;
      if (x1 > bb.x1) bb.x1 = x1;
      if (y1 > bb.y1) bb.y1 = y1;
    }
    var rightMost = 0, leftMost = 1e9;
    for (i = 0; i < nodes.length; i++) {
      n = nodes[i];
      bump(n.x, n.y, n.x + n.w, n.y + n.h);
      if (n.x + n.w > rightMost) rightMost = n.x + n.w;
      if (n.x < leftMost) leftMost = n.x;
    }
    if (leftMost > 1e8) leftMost = 0;

    var wires = '';     // every line, drawn first
    var boxes = '';     // node boxes on top of the lines
    var chips = '';     // labels last, so nothing is drawn through them

    /* Every chip that has been placed, so a note connector routed later can be steered
       around one instead of vanishing behind it. */
    var chipBoxes = [];
    function chipAt(cx, cy, text, box) {
      chipBoxes.push({ x0: cx - box.w / 2, y0: cy - box.h / 2,
                       x1: cx + box.w / 2, y1: cy + box.h / 2 });
      bump(cx - box.w / 2, cy - box.h / 2, cx + box.w / 2, cy + box.h / 2);
      return drawChip(cx, cy, text);
    }

    // -- forward transitions -----------------------------------------------------
    for (i = 0; i < edges.length; i++) {
      e = edges[i];
      if (e.back || e.self || e.long) continue;
      var a = byId[e.from], b = byId[e.to];
      if (!a || !b) continue;
      var p = D.connect(a, b, { inset: 1 });
      wires += D.path(p.d, { stroke: D.C.dim, sw: 1.4, markerEnd: 'd-arrow' });
      if (!e.label) continue;
      if (!e.chip) e.chip = chipOf(e.label);
      var lx, ly;
      if (e.stackO !== undefined) {
        // one of several arrivals: take my own slot in the column above the target
        lx = b.x + b.w / 2;
        ly = b.y - 10 - e.stackO - e.chip.h / 2;
      } else if (isStraight(a, b)) {
        lx = p.mid.x;
        ly = p.mid.y;
      } else {
        lx = b.x + b.w / 2;
        ly = b.y - 10 - e.chip.h / 2;
      }
      chips += chipAt(lx, ly, e.label, e.chip);
      /* a transition chip can stick out further than any box, and the right-hand
         lanes have to start clear of it or a gutter line disappears behind a label */
      if (lx + e.chip.w / 2 > rightMost) rightMost = lx + e.chip.w / 2;
      if (lx - e.chip.w / 2 < leftMost) leftMost = lx - e.chip.w / 2;
    }

    // -- self transitions: left of the state, so the right stays free for returns --
    for (i = 0; i < edges.length; i++) {
      e = edges[i];
      if (!e.self) continue;
      n = byId[e.from];
      if (!n) continue;
      var leftMostInRow = true;
      for (j = 0; j < nodes.length; j++) {
        if (nodes[j] !== n && nodes[j].layer === n.layer && nodes[j].x < n.x) leftMostInRow = false;
      }
      var y1 = n.y + n.h * 0.3, y2 = n.y + n.h * 0.7, cyl = (y1 + y2) / 2;
      var cw = e.label ? chipOf(e.label) : null;
      if (leftMostInRow) {
        var lxe = n.x;
        wires += D.path('M' + r(lxe) + ',' + r(y1)
          + ' C' + r(lxe - LOOP) + ',' + r(y1 - 7) + ' '
          + r(lxe - LOOP) + ',' + r(y2 + 7) + ' '
          + r(lxe - 2) + ',' + r(y2),
          { stroke: D.C.dim, sw: 1.4, markerEnd: 'd-arrow' });
        bump(lxe - LOOP - 2, y1 - 8, lxe, y2 + 8);
        if (lxe - LOOP - 2 < leftMost) leftMost = lxe - LOOP - 2;
        if (cw) {
          var scx = lxe - LOOP - 8 - cw.w / 2;
          chips += chipAt(scx, cyl, e.label, cw);
          if (scx - cw.w / 2 < leftMost) leftMost = scx - cw.w / 2;
        }
      } else {
        var sp = D.selfLoop(n, { out: LOOP });
        wires += D.path(sp.d, { stroke: D.C.dim, sw: 1.4, markerEnd: 'd-arrow' });
        bump(n.x + n.w, y1 - 8, n.x + n.w + LOOP + 2, y2 + 8);
        if (n.x + n.w + LOOP + 2 > rightMost) rightMost = n.x + n.w + LOOP + 2;
        if (cw) {
          var scx2 = n.x + n.w + LOOP + 8 + cw.w / 2;
          chips += chipAt(scx2, cyl, e.label, cw);
          if (scx2 + cw.w / 2 > rightMost) rightMost = scx2 + cw.w / 2;
        }
      }
    }

    /* -- side lanes: one gutter each --------------------------------------------
       Two kinds of edge cannot be drawn between the rows and so are routed out here:
       a return path climbing back up the graph, and a forward edge that skips a layer
       (which straight down would be painted through whatever is standing in between).
       Both leave and re-enter on the right; only the direction of travel differs. */
    var backs = [];
    for (i = 0; i < edges.length; i++) {
      e = edges[i];
      if (e.self || (!e.back && !e.long)) continue;
      if (byId[e.from] && byId[e.to]) backs.push(e);
    }
    backs.sort(function (x, y) {
      var sx = Math.abs(byId[x.from].layer - byId[x.to].layer);
      var sy = Math.abs(byId[y.from].layer - byId[y.to].layer);
      if (sx !== sy) return sx - sy;                 // short hops on the inner lane
      return byId[x.from].layer - byId[y.from].layer;
    });

    /* D.connectBack climbs; this is the same gutter shape travelling downwards. */
    function connectDown(from, to, gx) {
      var a = D.anchor(from, 'right');
      var b = D.anchor(to, 'right');
      var q = 10;
      return {
        d: 'M' + r(a.x) + ',' + r(a.y)
          + ' L' + r(gx - q) + ',' + r(a.y)
          + ' Q' + r(gx) + ',' + r(a.y) + ' ' + r(gx) + ',' + r(a.y + q)
          + ' L' + r(gx) + ',' + r(b.y - q)
          + ' Q' + r(gx) + ',' + r(b.y) + ' ' + r(gx - q) + ',' + r(b.y)
          + ' L' + r(b.x + 2) + ',' + r(b.y),
        mid: { x: gx, y: (a.y + b.y) / 2 }
      };
    }

    var outN = {}, inN = {}, outI = {}, inI = {};
    for (i = 0; i < backs.length; i++) {
      outN[backs[i].from] = (outN[backs[i].from] || 0) + 1;
      inN[backs[i].to] = (inN[backs[i].to] || 0) + 1;
    }

    function vnode(src, dy) { return { x: src.x, y: src.y + dy, w: src.w, h: src.h }; }

    var cursor = rightMost + LANE;
    for (i = 0; i < backs.length; i++) {
      e = backs[i];
      var fa = byId[e.from], ta = byId[e.to];
      outI[e.from] = (outI[e.from] || 0);
      inI[e.to] = (inI[e.to] || 0);
      var fdy = (outI[e.from] - (outN[e.from] - 1) / 2) * 11;
      var tdy = (inI[e.to] - (inN[e.to] - 1) / 2) * 11;
      outI[e.from]++;
      inI[e.to]++;
      // degenerate case: a "back" edge inside one row - force the ends apart
      if (Math.abs((fa.y + fdy) - (ta.y + tdy)) < 24) { fdy += 12; tdy -= 12; }

      var gx = cursor;
      var bp = e.back ? D.connectBack(vnode(fa, fdy), vnode(ta, tdy), gx)
                      : connectDown(vnode(fa, fdy), vnode(ta, tdy), gx);
      wires += D.path(bp.d, { stroke: D.C.dim, sw: 1.4, markerEnd: 'd-arrow' });
      bump(ta.x + ta.w, Math.min(ta.y + tdy, fa.y + fdy) - 4,
           gx + 2, Math.max(ta.y + ta.h + tdy, fa.y + fa.h + fdy) + 4);

      if (e.label) {
        var bc = chipOf(e.label);
        var bcx = gx + 9 + bc.w / 2;
        chips += chipAt(bcx, bp.mid.y, e.label, bc);
        cursor = gx + 9 + bc.w + LANE;
      } else {
        cursor = gx + LANE;
      }
    }

    // -- notes -------------------------------------------------------------------
    var noteRight = cursor + 4;
    var noteLeft = leftMost - LANE;
    for (i = 0; i < notes.length; i++) {
      var note = notes[i];
      var tn = byId[note.target];
      if (!tn) continue;
      var nl = [];
      for (j = 0; j < note.lines.length; j++) {
        var ws = D.wrapText(note.lines[j], NFS, NMAX);
        for (k = 0; k < ws.length; k++) if (trim(ws[k])) nl.push(ws[k]);
      }
      if (!nl.length) continue;
      var nw = D.maxWidth(nl, NFS) + 24;
      var nh = nl.length * NLH + 20;

      /* The connector drops out of the BOTTOM corner of the state and then runs along
         a lane just under it, crossing the gutters square-on instead of creeping along
         beside them. For a state in the last row that band is empty, but a note on a
         state higher up has to cross the margin where the return-path labels live, so
         the lane is pushed down below any chip actually standing in its way. */
      var left = note.side === 'left';
      var nx, ax, turnX, dir;
      if (left) {
        nx = noteLeft - nw;
        ax = tn.x;
        turnX = Math.min(tn.x - 12, leftMost - 12);
        dir = -1;
        noteLeft = nx - LANE;
      } else {
        nx = noteRight;
        ax = tn.x + tn.w;
        turnX = Math.max(tn.x + tn.w + 12, rightMost + 12);
        dir = 1;
        noteRight = nx + nw + LANE;
      }
      var laneY = tn.y + tn.h + 18;
      var runL = Math.min(turnX, left ? nx + nw : nx);
      var runR = Math.max(turnX, left ? nx + nw : nx);
      for (j = 0; j < 8; j++) {
        var moved = false;
        for (k = 0; k < chipBoxes.length; k++) {
          var cbx = chipBoxes[k];
          if (cbx.x1 > runL && cbx.x0 < runR && laneY > cbx.y0 - 7 && laneY < cbx.y1 + 7) {
            laneY = cbx.y1 + 11;
            moved = true;
          }
        }
        if (!moved) break;
      }
      var ncy = laneY;
      var ny = ncy - nh / 2;
      var ay = tn.y + tn.h - 6;
      var q = 8;

      wires += D.path('M' + r(ax) + ',' + r(ay)
        + ' L' + r(turnX - q * dir) + ',' + r(ay)
        + ' Q' + r(turnX) + ',' + r(ay) + ' ' + r(turnX) + ',' + r(ay + q)
        + ' L' + r(turnX) + ',' + r(laneY - q)
        + ' Q' + r(turnX) + ',' + r(laneY) + ' ' + r(turnX + q * dir) + ',' + r(laneY)
        + ' L' + r(left ? nx + nw : nx) + ',' + r(laneY),
        { stroke: D.C.faint, sw: 1.2, dash: '4 3' });
      bump(Math.min(ax, turnX) - 2, ay, Math.max(ax, turnX) + 2, laneY);

      boxes += D.rect(nx, ny, nw, nh, { rx: 8, fill: D.C.node2, stroke: D.C.line, dash: '4 3' });
      for (j = 0; j < nl.length; j++) {
        boxes += D.text(nx + 12, ny + 19 + j * NLH, nl[j], { size: NFS, anchor: 'start', fill: D.C.dim });
      }
      bump(nx, ny, nx + nw, ny + nh);
    }

    // -- the states themselves ---------------------------------------------------
    for (i = 0; i < nodes.length; i++) {
      n = nodes[i];
      var cx = n.x + n.w / 2, cy = n.y + n.h / 2;
      if (n.kind === 'start') {
        boxes += D.el('circle', { cx: cx, cy: cy, r: 9, fill: D.C.text });
      } else if (n.kind === 'end') {
        boxes += D.el('circle', { cx: cx, cy: cy, r: 9, fill: D.C.surface, stroke: D.C.text, 'stroke-width': 1.6 });
        boxes += D.el('circle', { cx: cx, cy: cy, r: 4.6, fill: D.C.text });
      } else if (n.kind === 'composite') {
        boxes += D.rect(n.x, n.y, n.w, n.h, { rx: 14, fill: D.C.surface, stroke: D.C.line });
        boxes += D.text(cx, n.y + 20, n.label, { size: FS, weight: '600' });
        boxes += D.path('M' + r(n.x) + ',' + r(n.y + 30) + ' L' + r(n.x + n.w) + ',' + r(n.y + 30),
          { stroke: D.C.line, sw: 1 });
        for (j = 0; j < n.kids.length; j++) {
          boxes += D.text(n.x + 16, n.y + 30 + 18 + j * NLH, n.kids[j],
            { size: NFS, anchor: 'start', fill: D.C.dim });
        }
      } else {
        boxes += D.rect(n.x, n.y, n.w, n.h, { rx: 14, fill: D.C.node, stroke: D.C.line });
        boxes += D.textBlock(cx, cy, n.tl, { size: FS, fill: D.C.text, weight: '600', lh: 17 });
      }
    }

    return { wires: wires, boxes: boxes, chips: chips, bb: bb };
  }
  };
})();
