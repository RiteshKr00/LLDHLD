import pathlib, re, importlib.util
import xml.etree.ElementTree as ET
NS = "{http://www.w3.org/2000/svg}"
spec = importlib.util.spec_from_file_location("mk", "mobile/test/make_diagram_test.py")
mk = importlib.util.module_from_spec(spec); spec.loader.exec_module(mk)

def poly(d):
    """Reconstruct the true corner polyline: M start, Q control points, final L end."""
    pts=[]
    m=re.match(r'M([-\d.]+),([-\d.]+)', d)
    pts.append((float(m.group(1)),float(m.group(2))))
    for q in re.finditer(r'Q([-\d.]+),([-\d.]+)', d):
        pts.append((float(q.group(1)),float(q.group(2))))
    last=re.findall(r'L([-\d.]+),([-\d.]+)', d)[-1]
    pts.append((float(last[0]),float(last[1])))
    return pts

def segbox(p,q,b,pad):
    bx,by,bw,bh = b[0]+pad, b[1]+pad, b[2]-2*pad, b[3]-2*pad
    if bw<=0 or bh<=0: return 0
    # axis-aligned segments only
    x1,y1=p; x2,y2=q
    lox,hix=min(x1,x2),max(x1,x2); loy,hiy=min(y1,y2),max(y1,y2)
    ox = min(hix,bx+bw)-max(lox,bx); oy = min(hiy,by+bh)-max(loy,by)
    if ox>0.5 and oy>0.5: return min(ox,oy)
    return 0

tot=0
for d in [x for x in mk.collect() if x["type"]=="classDiagram"]:
    p=pathlib.Path("mobile/test/out-classDiagram")/(d["name"]+".svg")
    root=ET.fromstring(p.read_text(encoding="utf-16",errors="replace"))
    bs=[]; names={}
    for r in root.iter(NS+"rect"):
        if r.get("stroke") in (None,"none"): continue
        bs.append((float(r.get("x")),float(r.get("y")),float(r.get("width")),float(r.get("height"))))
    labels=[]
    for r in root.iter(NS+"rect"):
        if r.get("stroke") not in (None,"none"): continue
        labels.append((float(r.get("x")),float(r.get("y")),float(r.get("width")),float(r.get("height"))))
    msgs=[]
    for g in root.iter(NS+"g"):
        for e in g.findall(NS+"path"):
            pts=poly(e.get("d"))
            for i in range(1,len(pts)):
                for b in bs:
                    v=segbox(pts[i-1],pts[i],b,4)
                    if v: msgs.append("edge segment %s-%s cuts box at %s (depth %.1f)" % (pts[i-1],pts[i],(b[0],b[1]),v))
    # label chip vs class box
    for L in labels:
        for b in bs:
            ox=min(L[0]+L[2],b[0]+b[2])-max(L[0],b[0]); oy=min(L[1]+L[3],b[1]+b[3])-max(L[1],b[1])
            if ox>2 and oy>2: msgs.append("label chip %s overlaps box %s by %.0fx%.0f" % ((round(L[0]),round(L[1])),(round(b[0]),round(b[1])),ox,oy))
    # label chip vs label chip
    for i in range(len(labels)):
        for j in range(i+1,len(labels)):
            L,M=labels[i],labels[j]
            ox=min(L[0]+L[2],M[0]+M[2])-max(L[0],M[0]); oy=min(L[1]+L[3],M[1]+M[3])-max(L[1],M[1])
            if ox>2 and oy>2: msgs.append("label chips overlap %s / %s by %.0fx%.0f" % ((round(L[0]),round(L[1])),(round(M[0]),round(M[1])),ox,oy))
    print("%-26s %s" % (d["name"], "OK" if not msgs else "*** %d" % len(msgs)))
    for m in msgs[:10]: print("     ",m); tot+=1
print("\nproblems", tot)
