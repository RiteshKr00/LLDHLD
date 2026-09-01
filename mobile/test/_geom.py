import pathlib, re, importlib.util
import xml.etree.ElementTree as ET
NS = "{http://www.w3.org/2000/svg}"
spec = importlib.util.spec_from_file_location("mk", "mobile/test/make_diagram_test.py")
mk = importlib.util.module_from_spec(spec); spec.loader.exec_module(mk)

REL_RX = re.compile(r'^([A-Za-z_]\w*)\s*(?:"([^"]*)"\s*)?'
                    r'(<\|--|--\|>|<\|\.\.|\.\.\|>|\*--|--\*|o--|--o|-->|<--|\.\.>|<\.\.|--|\.\.)'
                    r'\s*(?:"([^"]*)"\s*)?([A-Za-z_]\w*)\s*$')
# expected marker end + which class it should sit on
EXP = {
 '<|--': ('d-tri', 'A'), '--|>': ('d-tri','B'), '<|..': ('d-tri','A'), '..|>': ('d-tri','B'),
 '*--': ('d-dia','A'), '--*': ('d-dia','B'), 'o--': ('d-diaO','A'), '--o': ('d-diaO','B'),
 '-->': ('d-arrow','B'), '<--': ('d-arrow','A'), '..>': ('d-arrow','B'), '<..': ('d-arrow','A'),
 '--': (None,None), '..': (None,None)}

def rels(src):
    out=[]; cur=None
    lines=[l.strip() for l in src.split("\n")]
    lines=[l for l in lines if l and not l.startswith("%%")]
    for line in lines[1:]:
        if cur is not None:
            if line.startswith('}'): cur=None
            continue
        m=re.match(r'^class\s+([A-Za-z_]\w*)\s*(\{)?\s*$', line)
        if m:
            if m.group(2): cur=m.group(1)
            continue
        if re.match(r'^(direction|note|click|style|classDef|cssClass|link|namespace|end)\b', line, re.I): continue
        if ':' in line: line=line[:line.index(':')].strip()
        m=REL_RX.match(line)
        if m: out.append((m.group(1), m.group(3), m.group(5)))
    return out

def parse_pts(d):
    # M x,y then sequence of L/Q ; return first and last coordinate pair
    nums = re.findall(r'[-\d.]+,[-\d.]+', d)
    pts = [tuple(float(v) for v in n.split(',')) for n in nums]
    return pts

def boxes_with_names(root):
    # boxes = stroked rects; names = bold text (weight 600) grouped by proximity
    bs=[]
    for r in root.iter(NS+"rect"):
        if r.get("stroke") in (None,"none"): continue
        bs.append([float(r.get("x")),float(r.get("y")),float(r.get("width")),float(r.get("height")),[]])
    for t in root.iter(NS+"text"):
        if t.get("font-weight") != "600": continue
        x=float(t.get("x")); y=float(t.get("y")); s=t.text or ''
        for b in bs:
            if b[0]-1<=x<=b[0]+b[2]+1 and b[1]-1<=y<=b[1]+b[3]+1:
                b[4].append(s); break
    return bs

tot_e=0; probs=0
for d in [x for x in mk.collect() if x["type"]=="classDiagram"]:
    p=pathlib.Path("mobile/test/out-classDiagram")/(d["name"]+".svg")
    txt=p.read_text(encoding="utf-16",errors="replace")
    root=ET.fromstring(txt)
    # translate offsets
    bs=boxes_with_names(root)
    names={}
    for b in bs: names[''.join(b[4])]=b
    paths=[]
    for g in root.iter(NS+"g"):
        for e in g.findall(NS+"path"):
            paths.append(e)
    src_rels=rels(d["src"])
    msgs=[]
    if len(paths)!=len(src_rels):
        msgs.append("edge count %d != %d relations" % (len(paths), len(src_rels)))
    # each path endpoint must lie on some box border (within 2px)
    def on_border(pt):
        x,y=pt
        for b in bs:
            bx,by,bw,bh,_=b
            if bx-2.5<=x<=bx+bw+2.5 and by-2.5<=y<=by+bh+2.5:
                if abs(y-by)<2.5 or abs(y-(by+bh))<2.5 or abs(x-bx)<2.5 or abs(x-(bx+bw))<2.5:
                    return b
        return None
    def inside(pt):
        x,y=pt
        for b in bs:
            bx,by,bw,bh,_=b
            if bx+3<x<bx+bw-3 and by+3<y<by+bh-3: return b
        return None
    for e in paths:
        pts=parse_pts(e.get("d"))
        if not pts: continue
        a=on_border(pts[0]); z=on_border(pts[-1])
        if not a: msgs.append("path start not on a box border: %s" % (pts[0],))
        if not z: msgs.append("path end not on a box border: %s" % (pts[-1],))
        for q in pts:
            b=inside(q)
            if b: msgs.append("path vertex inside box %s: %s" % (''.join(b[4]), q)); break
    # marker semantics
    marker_by_pair={}
    for e in paths:
        pts=parse_pts(e.get("d"))
        me=e.get("marker-end")
        z=on_border(pts[-1])
        marker_by_pair.setdefault((''.join(z[4]) if z else '?', me and me[5:-1]),0)
        marker_by_pair[(''.join(z[4]) if z else '?', me and me[5:-1])]+=1
    for (A,op,B) in src_rels:
        mk_,side = EXP[op]
        target = A if side=='A' else B
        if mk_ is None: continue
        key=(target.replace(" ",""), mk_)
        found=False
        for (nm,m),c in marker_by_pair.items():
            if m==mk_ and nm.replace(" ","")==target and c>0:
                marker_by_pair[(nm,m)]-=1; found=True; break
        if not found:
            msgs.append("marker %s expected terminating on %s for %s %s %s" % (mk_,target,A,op,B))
    tot_e+=len(paths)
    print("%-26s paths=%2d rels=%2d %s" % (d["name"], len(paths), len(src_rels), "OK" if not msgs else "*** "+str(len(msgs))))
    for m in msgs[:12]:
        probs+=1; print("     ", m)
print("\ntotal edges", tot_e, "problems", probs)
