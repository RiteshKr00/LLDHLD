import pathlib, re, sys, importlib.util
import xml.etree.ElementTree as ET
NS = "{http://www.w3.org/2000/svg}"
spec = importlib.util.spec_from_file_location("mk", "mobile/test/make_diagram_test.py")
mk = importlib.util.module_from_spec(spec); spec.loader.exec_module(mk)

REL_RX = re.compile(r'^([A-Za-z_]\w*)\s*(?:"([^"]*)"\s*)?'
                    r'(<\|--|--\|>|<\|\.\.|\.\.\|>|\*--|--\*|o--|--o|-->|<--|\.\.>|<\.\.|--|\.\.)'
                    r'\s*(?:"([^"]*)"\s*)?([A-Za-z_]\w*)\s*$')

def norm(s):
    return re.sub(r'\s+', ' ', s).strip()

def gen(s):
    return re.sub(r'~([^~]*)~', r'<\1>', s)

def analyse(src):
    classes, members, rels = set(), [], []
    cur = None
    lines = [l.strip() for l in src.split("\n")]
    lines = [l for l in lines if l and not l.startswith("%%")]
    for line in lines[1:]:
        if cur is not None:
            if line.startswith('}'):
                cur = None; continue
            m = re.match(r'^<<\s*(.+?)\s*>>$', line)
            if m: members.append((cur, '<<'+m.group(1)+'>>'))
            else: members.append((cur, gen(line)))
            continue
        m = re.match(r'^class\s+([A-Za-z_]\w*)\s*(\{)?\s*$', line)
        if m:
            classes.add(m.group(1))
            if m.group(2): cur = m.group(1)
            continue
        if re.match(r'^(direction|note|click|style|classDef|cssClass|link|namespace|end)\b', line, re.I):
            continue
        label = ''
        if ':' in line:
            i = line.index(':')
            label = line[i+1:].strip(); line = line[:i].strip()
        m = REL_RX.match(line)
        if not m: continue
        classes.add(m.group(1)); classes.add(m.group(4+1-1+1) if False else m.group(5))
        rels.append((m.group(1), m.group(3), m.group(5), m.group(2), m.group(4), label))
    return classes, members, rels

def svgtext(p):
    t = p.read_text(encoding="utf-16", errors="replace")
    root = ET.fromstring(t)
    return [(e.text or '') for e in root.iter(NS+"text")]

bad = 0
for d in [x for x in mk.collect() if x["type"]=="classDiagram"]:
    p = pathlib.Path("mobile/test/out-classDiagram")/(d["name"]+".svg")
    classes, members, rels = analyse(d["src"])
    texts = svgtext(p)
    joined = norm(" ".join(texts))
    exact = set(norm(t) for t in texts)
    probs = []
    for c in sorted(classes):
        # class name may be wrapped on camel seams -> check joined with spaces removed
        if c not in joined.replace(" ", ""):
            probs.append("MISSING class %s" % c)
    for owner, mem in members:
        if norm(mem) not in joined:
            probs.append("MISSING member of %s: %r" % (owner, mem))
    for a, op, b, ca, cb, label in rels:
        if label and norm(label) not in joined:
            probs.append("MISSING edge label %r (%s %s %s)" % (label, a, op, b))
        if ca and norm(ca) not in exact and norm(ca) not in joined:
            probs.append("MISSING card %r on %s (%s %s %s)" % (ca, a, a, op, b))
        if cb and norm(cb) not in exact and norm(cb) not in joined:
            probs.append("MISSING card %r on %s (%s %s %s)" % (cb, b, a, op, b))
    print("%-26s classes=%d members=%d rels=%d texts=%d %s" % (
        d["name"], len(classes), len(members), len(rels), len(texts),
        "OK" if not probs else "*** %d PROBLEMS" % len(probs)))
    for x in probs:
        bad += 1
        print("      " + x)
print()
print("total problems:", bad)
