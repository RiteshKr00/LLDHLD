/* sequenceDiagram - participants across the top, lifelines down, messages in order.
 *
 * Layout in one sentence: measure the participant labels, space the lifelines just
 * far enough apart that message text fits between them, then walk the events top to
 * bottom handing each one the vertical room it asks for. Self messages get a small
 * loop off the right of their own lifeline; notes get a pale box that pushes
 * everything below it further down.
 *
 * ES5 only (runs under Windows Script Host in mobile/test/). Pure string -> string.
 */

(function () {
  'use strict';

  var D = window.LLDD;
  if (!D) return;

  // ---------------------------------------------------------------- constants

  var P_SIZE = 12, P_LH = 15;        // participant label
  var M_SIZE = 11, M_LH = 14;        // message label
  var N_SIZE = 11, N_LH = 14;        // note text
  var G_SIZE = 10.5, G_LH = 13;      // alt/loop/opt bracket tag

  var BOX_PAD = 9;                   // horizontal padding inside a participant box
  var MIN_BOX_W = 62;
  var PART_WRAP = 118;               // wrap participant labels at this width
  var BASE_GAP = 30;                 // minimum gap between participant boxes
  var HEAD_GAP = 26;                 // below the header row before the first message
  var ROW_GAP = 17;                  // below one message before the next
  var LOOP_W = 34, LOOP_H = 24;      // self-message loop
  var MIN_LABEL_W = 145;             // a message label may overhang its span this far
  var MAX_LABEL_W = 260;
  var SELF_LABEL_W = 190;
  var SELF_MIN_W = 110;              // ...but never squeeze self text below this
  var NOTE_WRAP = 200;
  var FOOT_AT = 480;                 // repeat the participant row below a tall diagram

  function r(v) { return D.round(v); }

  function trim(s) {
    return String(s === null || s === undefined ? '' : s).replace(/^\s+|\s+$/g, '');
  }

  // ------------------------------------------------------------------ metrics

  /* Characters after which a too-long word may be broken. Breaking "publish(COMMENT_
     POSTED)" keeps the diagram narrow without inventing whitespace that is not in
     the source - the two halves concatenate back to the original string. */
  var BREAK_AFTER = '([{_.,;:/|>=+&-';

  function splitLong(word, size, maxW) {
    var out = [], s = word, guard = 0, i, best, alt;
    while (D.textWidth(s, size) > maxW && s.length > 1 && guard++ < 40) {
      best = 0;   // greedy: the last break that still fits
      alt = 0;    // the earliest break whose *remainder* also fits, i.e. fewest lines
      for (i = 1; i < s.length; i++) {
        if (D.textWidth(s.slice(0, i), size) > maxW) break;
        if (BREAK_AFTER.indexOf(s.charAt(i - 1)) >= 0) {
          best = i;
          if (!alt && D.textWidth(s.slice(i), size) <= maxW) alt = i;
        }
      }
      /* Prefer `alt`: it splits "publish(COMMENT_POSTED)" after the bracket rather
         than through the middle of the identifier. */
      if (alt) best = alt;
      if (!best) best = i - 1;
      if (best < 1) best = 1;
      out.push(s.slice(0, best));
      s = s.slice(best);
    }
    out.push(s);
    return out;
  }

  /** Wrap on spaces (D.wrapText), then hard-break anything still too wide. */
  function fit(text, size, maxW) {
    var soft = D.wrapText(text, size, maxW);
    var out = [], i, j, piece;
    for (i = 0; i < soft.length; i++) {
      if (D.textWidth(soft[i], size) <= maxW) { out.push(soft[i]); continue; }
      piece = splitLong(soft[i], size, maxW);
      for (j = 0; j < piece.length; j++) out.push(piece[j]);
    }
    return out;
  }

  // -------------------------------------------------------------------- chips

  /* Message text is drawn on an opaque plate so a dashed lifeline never runs
     through it. The plate carries no stroke, so it is not a "box" for the
     geometry checker - it is type, not structure. */
  function chip(cx, cy, lines, size, lh, colour) {
    var w = D.maxWidth(lines, size) + 12;
    var h = lines.length * lh + 4;
    return D.rect(cx - w / 2, cy - h / 2, w, h,
                  { rx: 5, fill: D.C.surface, stroke: 'none' })
         + D.textBlock(cx, cy, lines, { size: size, lh: lh, fill: colour });
  }

  /** Same, anchored at its left edge (self-message text, bracket tags). */
  function chipL(x, cy, lines, size, lh, colour) {
    var w = D.maxWidth(lines, size) + 10;
    var h = lines.length * lh + 4;
    return D.rect(x - 5, cy - h / 2, w, h,
                  { rx: 5, fill: D.C.surface, stroke: 'none' })
         + D.textBlock(x, cy, lines, { size: size, lh: lh, fill: colour, anchor: 'start' });
  }

  // ------------------------------------------------------------------ parsing

  /* Longest first: '-->>' must win over '-->' and '->>'. */
  var ARROWS = ['<<-->>', '<<->>', '-->>', '--x', '--)', '-->', '->>', '-x', '-)', '->'];

  function findArrow(s) {
    var i, k, tok, c;
    for (i = 0; i < s.length; i++) {
      c = s.charAt(i);
      if (c !== '-' && c !== '<') continue;
      for (k = 0; k < ARROWS.length; k++) {
        tok = ARROWS[k];
        if (s.slice(i, i + tok.length) === tok) return { at: i, tok: tok };
      }
    }
    return null;
  }

  var RE_NOTE = /^note\s+(over|left\s+of|right\s+of)\s+([^:]+):\s*([\s\S]*)$/i;
  var RE_PART = /^(?:participant|actor)\s+([\s\S]+)$/i;
  var RE_AS = /^([\s\S]+?)\s+as\s+([\s\S]+)$/i;
  /* `rect` and `box` draw nothing here, but they still take an `end`, so they have
     to go on the same stack as alt/loop - otherwise a `box` around the participant
     list eats the `end` belonging to the first real block. */
  var RE_GSTART = /^(alt|opt|loop|par|critical|break|rect|box)\b\s*([\s\S]*)$/i;
  var RE_GELSE = /^(?:else|and|option)\b\s*([\s\S]*)$/i;
  var RE_SKIP = /^(?:activate|deactivate|autonumber|link|links|properties|details|create|destroy|accTitle|accDescr)\b/i;
  var RE_TITLE = /^title\b\s*:?\s*([\s\S]*)$/i;

  function parse(lines) {
    var parts = [], index = {}, events = [], title = null;
    var i, line, m, body, as, id, lab, who, ia, ib, place, tok, f, from, to, text, ci, c0;

    function ensure(raw) {
      var key = trim(D.label(raw));
      if (!key) return -1;
      var slot = '@' + key;
      if (index[slot] === undefined) {
        index[slot] = parts.length;
        parts.push({ id: key, label: key });
      }
      return index[slot];
    }

    for (i = 1; i < lines.length; i++) {
      line = lines[i];

      m = RE_PART.exec(line);
      if (m) {
        body = trim(m[1]);
        as = RE_AS.exec(body);
        if (as) { id = trim(as[1]); lab = trim(as[2]); } else { id = body; lab = body; }
        ia = ensure(id);
        if (ia >= 0) parts[ia].label = D.label(lab);
        continue;
      }

      m = RE_TITLE.exec(line);
      if (m) { title = D.label(trim(m[1])); continue; }

      m = RE_NOTE.exec(line);
      if (m) {
        place = m[1].toLowerCase();
        who = m[2].split(',');
        ia = ensure(who[0]);
        if (ia < 0) continue;
        /* `Note over A,C` spans the two named lifelines; mermaid only ever names
           two, but take the last if a note lists more so the span still covers. */
        ib = who.length > 1 ? ensure(who[who.length - 1]) : ia;
        if (ib < 0) ib = ia;
        events.push({
          kind: 'note',
          a: Math.min(ia, ib),
          b: Math.max(ia, ib),
          where: place.indexOf('left') === 0 ? 'left' : (place.indexOf('right') === 0 ? 'right' : 'over'),
          text: D.label(m[3])
        });
        continue;
      }

      if (RE_SKIP.test(line)) continue;

      m = RE_GSTART.exec(line);
      if (m) {
        tok = m[1].toLowerCase();
        var quiet = tok === 'rect' || tok === 'box';
        events.push({
          kind: 'gstart',
          gkind: tok,
          hidden: quiet,
          label: quiet ? '' : D.label(trim(m[2]))
        });
        continue;
      }

      m = RE_GELSE.exec(line);
      if (m) { events.push({ kind: 'gelse', label: D.label(trim(m[1])) }); continue; }

      if (/^end\b/i.test(line)) { events.push({ kind: 'gend' }); continue; }

      // message
      ci = line.indexOf(':');
      body = ci >= 0 ? line.slice(0, ci) : line;
      text = ci >= 0 ? trim(line.slice(ci + 1)) : '';
      f = findArrow(body);
      if (!f) continue;                                  // not something we understand
      from = trim(body.slice(0, f.at));
      to = trim(body.slice(f.at + f.tok.length));
      c0 = to.charAt(0);
      if (c0 === '+' || c0 === '-') to = trim(to.slice(1));   // activation shorthand
      if (!from || !to) continue;
      ia = ensure(from);
      ib = ensure(to);
      if (ia < 0 || ib < 0) continue;
      events.push({
        kind: 'msg', a: ia, b: ib, self: ia === ib,
        dashed: f.tok.indexOf('--') >= 0,
        cross: f.tok.charAt(f.tok.length - 1) === 'x',
        text: D.label(text)
      });
    }

    return { parts: parts, events: events, title: title };
  }

  // ------------------------------------------------------------------- render

  D.renderers.sequenceDiagram = function (lines, head) {
    var doc = parse(lines);
    var parts = doc.parts, events = doc.events;
    var i, k, p, ev, a, b, m;

    if (!parts.length) throw new Error('sequenceDiagram: no participants found');

    // -- participant boxes ---------------------------------------------------
    var pLines = 1;
    for (i = 0; i < parts.length; i++) {
      p = parts[i];
      p.lines = fit(p.label, P_SIZE, PART_WRAP);
      p.w = Math.max(MIN_BOX_W, D.maxWidth(p.lines, P_SIZE) + BOX_PAD * 2);
      if (p.lines.length > pLines) pLines = p.lines.length;
    }
    var headH = Math.max(34, pLines * P_LH + 15);

    // -- horizontal placement ------------------------------------------------
    /* Gaps start at the minimum and grow only where a message label genuinely
       cannot fit between the two lifelines it joins. Growing per-gap (rather than
       uniformly) is what keeps the whole thing inside a phone screen. */
    var gaps = [];
    for (i = 0; i < parts.length - 1; i++) gaps.push(BASE_GAP);

    function place() {
      var x = 0, j;
      for (j = 0; j < parts.length; j++) {
        parts[j].x = x;
        parts[j].cx = x + parts[j].w / 2;
        x += parts[j].w + (j < gaps.length ? gaps[j] : 0);
      }
    }

    function measure() {
      var j, e, allow, span, room;
      for (j = 0; j < events.length; j++) {
        e = events[j];
        if (e.kind !== 'msg') continue;
        if (e.self) {
          /* Self text sits to the right of the loop. Keep it inside the corridor
             before the next lifeline where that costs at most a line or two, so a
             column of self-calls does not shred its neighbour's lifeline. */
          allow = SELF_LABEL_W;
          if (e.a < parts.length - 1) {
            room = parts[e.a + 1].cx - (parts[e.a].cx + LOOP_W + 10) - 8;
            if (room < allow) allow = Math.max(SELF_MIN_W, room);
          }
        } else {
          span = Math.abs(parts[e.b].cx - parts[e.a].cx);
          allow = span - 12;
          if (allow < MIN_LABEL_W) allow = MIN_LABEL_W;
          if (allow > MAX_LABEL_W) allow = MAX_LABEL_W;
        }
        e.lines = e.text ? fit(e.text, M_SIZE, allow) : [];
        e.lw = e.lines.length ? D.maxWidth(e.lines, M_SIZE) : 0;
      }
    }

    function widen() {
      var need = [], changed = false, j, e, lo, hi, span, deficit, each, g, over;
      for (j = 0; j < gaps.length; j++) need.push(0);
      for (j = 0; j < events.length; j++) {
        e = events[j];
        if (e.kind !== 'msg' || !e.lines.length) continue;
        if (e.self) {
          /* A self label sits in the corridor to the right of its own lifeline.
             If it would reach the next lifeline it whites out a slice of it, so
             open that one gap instead of letting the plate overprint. */
          if (e.a >= parts.length - 1) continue;
          over = (parts[e.a].cx + LOOP_W + 10 + e.lw + 8) - parts[e.a + 1].cx;
          if (over > 0.5) {
            if (need[e.a] < over) need[e.a] = over;
            changed = true;
          }
          continue;
        }
        lo = Math.min(e.a, e.b);
        hi = Math.max(e.a, e.b);
        if (hi === lo) continue;
        span = parts[hi].cx - parts[lo].cx;
        deficit = e.lw + 12 - span;
        if (deficit <= 0.5) continue;
        each = deficit / (hi - lo);
        for (g = lo; g < hi; g++) if (need[g] < each) need[g] = each;
        changed = true;
      }
      if (changed) for (j = 0; j < gaps.length; j++) gaps[j] += need[j];
      return changed;
    }

    for (var pass = 0; pass < 3; pass++) {
      place();
      measure();
      if (pass === 2) break;
      if (!widen()) break;
    }

    var last = parts[parts.length - 1];
    var rowW = last.x + last.w;

    /* Bracket tags and the title are wrapped to the participant row. Every alt/loop
       frame is guaranteed to be at least `rowW + 16` wide (see gPad below), so a tag
       wrapped to rowW - 22 always fits inside its own frame, and a title wrapped to
       rowW always fits the canvas. Neither can run off the edge. */
    var TAG_WRAP = Math.max(90, rowW - 22);

    // -- vertical pass -------------------------------------------------------
    var minX = 0, maxX = rowW;
    function seeX(x0, x1) { if (x0 < minX) minX = x0; if (x1 > maxX) maxX = x1; }

    var titleLines = doc.title ? fit(doc.title, 13, Math.max(260, rowW)) : null;
    var titleW = titleLines ? D.maxWidth(titleLines, 13) : 0;
    var titleH = titleLines ? titleLines.length * 17 + 10 : 0;
    var topY = titleH;
    var headBottom = topY + headH;
    var y = headBottom + HEAD_GAP;

    var stack = [], groups = [], g, lh, mid, span, wrapW, nw, nh, nx, bh;
    var maxDepth = 0, hasGroup = false, vis, tag, dl, dh;

    for (i = 0; i < events.length; i++) {
      ev = events[i];

      if (ev.kind === 'gstart') {
        vis = 0;                                  // nest against visible frames only
        for (k = 0; k < stack.length; k++) if (!stack[k].hidden) vis++;
        g = { kind: ev.gkind, label: ev.label, hidden: ev.hidden,
              depth: vis, top: y - 8, divs: [] };
        if (!g.hidden) {
          tag = g.kind + (g.label ? '  ' + g.label : '');
          g.lines = fit(tag, G_SIZE, TAG_WRAP);
          g.th = g.lines.length * G_LH + 4;
          /* the tag plate hangs below the frame's top edge, so the first row inside
             has to clear it - a two-line "alt <long condition>" needs the room */
          y += Math.max(24, g.th + 10);
          hasGroup = true;
          if (vis > maxDepth) maxDepth = vis;
        }
        stack.push(g);
        groups.push(g);
        continue;
      }

      if (ev.kind === 'gelse') {
        if (stack.length) {
          g = stack[stack.length - 1];
          if (!g.hidden) {
            y += 4;
            dl = ev.label ? fit(ev.label, G_SIZE, TAG_WRAP) : [];
            dh = dl.length ? dl.length * G_LH + 4 : 0;
            g.divs.push({ y: y, lines: dl, h: dh });
            y += Math.max(22, dh + 10);
          }
        }
        continue;
      }

      if (ev.kind === 'gend') {
        if (stack.length) {
          g = stack.pop();
          if (!g.hidden) {                        // `rect` draws nothing, so costs nothing
            g.bottom = Math.max(g.top + 30, y - ROW_GAP + 10);
            y = g.bottom + 16;
          }
        }
        continue;
      }

      if (ev.kind === 'note') {
        a = parts[ev.a];
        b = parts[ev.b];
        span = b.cx - a.cx;
        wrapW = NOTE_WRAP;
        if (ev.where === 'over' && ev.b !== ev.a) {
          wrapW = Math.max(NOTE_WRAP, Math.min(320, span + 40));
        }
        ev.lines = ev.text ? fit(ev.text, N_SIZE, wrapW) : [];
        nw = Math.max(84, D.maxWidth(ev.lines, N_SIZE) + 24);
        if (ev.where === 'over' && ev.b !== ev.a && span + 44 > nw) nw = span + 44;
        nh = Math.max(30, ev.lines.length * N_LH + 14);
        if (ev.where === 'left') nx = a.cx - 12 - nw;
        else if (ev.where === 'right') nx = a.cx + 12;
        else nx = (a.cx + b.cx) / 2 - nw / 2;
        ev.nx = nx; ev.ny = y + 2; ev.nw = nw; ev.nh = nh;
        y = ev.ny + nh + 16;
        seeX(nx - 2, nx + nw + 2);
        continue;
      }

      if (ev.kind !== 'msg') continue;

      a = parts[ev.a];
      b = parts[ev.b];
      lh = ev.lines.length * M_LH;

      if (ev.self) {
        ev.y1 = y + 2 + (lh > LOOP_H ? (lh - LOOP_H) / 2 : 0);
        ev.y2 = ev.y1 + LOOP_H;
        ev.cy = (ev.y1 + ev.y2) / 2;
        ev.lx = a.cx + LOOP_W + 10;
        bh = Math.max(LOOP_H, lh);
        y = y + 2 + bh + ROW_GAP;
        seeX(a.cx, ev.lx + ev.lw + 6);
      } else {
        ev.cy = y + lh / 2;
        ev.ay = y + lh + 7;
        y = ev.ay + ROW_GAP;
        if (ev.lw) {
          mid = (a.cx + b.cx) / 2;
          seeX(mid - ev.lw / 2 - 6, mid + ev.lw / 2 + 6);
        }
      }
    }

    while (stack.length) {                       // unbalanced alt/loop: close it here
      g = stack.pop();
      if (!g.hidden) g.bottom = Math.max(g.top + 30, y - ROW_GAP + 10);
    }

    var lifeBottom = Math.max(y - ROW_GAP + 8, headBottom + 34);
    var hasFoot = (lifeBottom - topY) > FOOT_AT;
    var footY = 0;
    if (hasFoot) { footY = lifeBottom + 6; lifeBottom = footY; }
    var totalH = hasFoot ? footY + headH : lifeBottom;

    /* Reserve the margin the alt/loop frames need. They are drawn full width, so
       they have to sit OUTSIDE everything already measured - notes and self-message
       labels included, both of which reach past the participant row. Each nesting
       level is inset 8px, so the outermost frame needs 8 + 8*maxDepth of clearance
       and the innermost still clears content by 8. Doing it here, once, is what
       stops a `loop` box from cutting through the very call it encloses. */
    var gPad = hasGroup ? 8 + maxDepth * 8 : 0;
    if (gPad) { minX -= gPad; maxX += gPad; }

    /* The title is centred on the finished canvas, so the canvas has to be at
       least as wide as the title or it hangs off both ends. */
    if (titleW > maxX - minX) {
      var tSlack = (titleW - (maxX - minX)) / 2;
      minX -= tSlack;
      maxX += tSlack;
    }

    // -- shift everything into positive space --------------------------------
    var dx = minX < 0 ? -minX : 0;
    var width = maxX - minX;
    if (dx) {
      for (i = 0; i < parts.length; i++) { parts[i].x += dx; parts[i].cx += dx; }
      for (i = 0; i < events.length; i++) {
        ev = events[i];
        if (ev.kind === 'note') ev.nx += dx;
        else if (ev.kind === 'msg' && ev.self) ev.lx += dx;
      }
    }
    var gx0 = minX + dx;                         // == 0: gPad already bought the margin
    var gx1 = maxX + dx;                         // == width

    // -- emit ----------------------------------------------------------------
    var body = '';

    if (titleLines) {
      body += D.textBlock(width / 2, (titleH - 8) / 2, titleLines,
                          { size: 13, lh: 17, weight: 600, fill: D.C.text });
    }

    for (i = 0; i < parts.length; i++) {
      p = parts[i];
      body += D.path('M' + r(p.cx) + ',' + r(headBottom) + ' L' + r(p.cx) + ',' + r(lifeBottom),
                     { stroke: D.C.line, sw: 1.2, dash: '4 6' });
    }

    for (i = 0; i < groups.length; i++) {
      g = groups[i];
      if (g.hidden) continue;
      var ax0 = gx0 + g.depth * 8;
      var ax1 = gx1 - g.depth * 8;
      var ay0 = g.top;
      var ay1 = Math.min(g.bottom, lifeBottom);
      if (ay1 < ay0 + 26) ay1 = ay0 + 26;
      if (ax1 < ax0 + 40) ax1 = ax0 + 40;
      body += D.path('M' + r(ax0) + ',' + r(ay0) + ' L' + r(ax1) + ',' + r(ay0)
                   + ' L' + r(ax1) + ',' + r(ay1) + ' L' + r(ax0) + ',' + r(ay1) + ' Z',
                     { stroke: D.C.line, sw: 1.2 });
      // the tag plate hangs just below the top edge so it never erases the frame
      body += chipL(ax0 + 11, ay0 + g.th / 2 + 3, g.lines, G_SIZE, G_LH, D.C.dim);
      for (k = 0; k < g.divs.length; k++) {
        body += D.path('M' + r(ax0) + ',' + r(g.divs[k].y) + ' L' + r(ax1) + ',' + r(g.divs[k].y),
                       { stroke: D.C.line, sw: 1, dash: '5 5' });
        if (g.divs[k].lines.length) {
          body += chipL(ax0 + 11, g.divs[k].y + g.divs[k].h / 2 + 3,
                        g.divs[k].lines, G_SIZE, G_LH, D.C.dim);
        }
      }
    }

    for (i = 0; i < parts.length; i++) {
      p = parts[i];
      body += D.rect(p.x, topY, p.w, headH, { rx: 7, fill: D.C.node2, stroke: D.C.line });
      body += D.textBlock(p.cx, topY + headH / 2, p.lines,
                          { size: P_SIZE, lh: P_LH, weight: 600, fill: D.C.text });
      if (hasFoot) {
        body += D.rect(p.x, footY, p.w, headH, { rx: 7, fill: D.C.node2, stroke: D.C.line });
        body += D.textBlock(p.cx, footY + headH / 2, p.lines,
                            { size: P_SIZE, lh: P_LH, weight: 600, fill: D.C.text });
      }
    }

    for (i = 0; i < events.length; i++) {
      ev = events[i];

      if (ev.kind === 'note') {
        body += D.rect(ev.nx, ev.ny, ev.nw, ev.nh,
                       { rx: 6, fill: D.C.node2, stroke: D.C.warn });
        if (ev.lines.length) {
          body += D.textBlock(ev.nx + ev.nw / 2, ev.ny + ev.nh / 2, ev.lines,
                              { size: N_SIZE, lh: N_LH, fill: D.C.text });
        }
        continue;
      }

      if (ev.kind !== 'msg') continue;

      a = parts[ev.a];
      b = parts[ev.b];
      var colour = ev.dashed ? D.C.dim : D.C.accent;
      var marker = ev.cross ? null : (ev.dashed ? 'd-arrow' : 'd-arrow-accent');
      var dash = ev.dashed ? '6 4' : null;

      if (ev.self) {
        var lx = a.cx, rr = 8;
        body += D.path('M' + r(lx) + ',' + r(ev.y1)
                     + ' L' + r(lx + LOOP_W - rr) + ',' + r(ev.y1)
                     + ' Q' + r(lx + LOOP_W) + ',' + r(ev.y1) + ' ' + r(lx + LOOP_W) + ',' + r(ev.y1 + rr)
                     + ' L' + r(lx + LOOP_W) + ',' + r(ev.y2 - rr)
                     + ' Q' + r(lx + LOOP_W) + ',' + r(ev.y2) + ' ' + r(lx + LOOP_W - rr) + ',' + r(ev.y2)
                     + ' L' + r(lx + 3) + ',' + r(ev.y2),
                       { stroke: colour, sw: 1.4, dash: dash, markerEnd: marker });
        if (ev.cross) body += cross(lx + 3, ev.y2, colour);
        if (ev.lines.length) body += chipL(ev.lx, ev.cy, ev.lines, M_SIZE, M_LH, D.C.text);
        continue;
      }

      var dir = b.cx >= a.cx ? 1 : -1;
      var x1 = a.cx + dir * 1.5;
      var x2 = b.cx - dir * 2.5;
      body += D.path('M' + r(x1) + ',' + r(ev.ay) + ' L' + r(x2) + ',' + r(ev.ay),
                     { stroke: colour, sw: 1.4, dash: dash, markerEnd: marker });
      if (ev.cross) body += cross(x2, ev.ay, colour);
      if (ev.lines.length) {
        body += chip((a.cx + b.cx) / 2, ev.cy, ev.lines, M_SIZE, M_LH, D.C.text);
      }
    }

    return D.frame(width, totalH, body);
  };

  /** The little x that ends a `-x` message (a call that fails / is dropped). */
  function cross(x, y, colour) {
    var s = 4.2;
    return D.path('M' + r(x - s) + ',' + r(y - s) + ' L' + r(x + s) + ',' + r(y + s)
                + ' M' + r(x + s) + ',' + r(y - s) + ' L' + r(x - s) + ',' + r(y + s),
                  { stroke: colour, sw: 1.6 });
  }
})();
