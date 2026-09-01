"""
Parser for the mock-interview sources in ../interview-mode/hld/*.md.

The study docs elsewhere are shipped to the app as plain markdown. These are
different: Mock mode has to reveal a problem one step at a time and score the
checkpoints you actually said, so the file has to be parsed into *structure*.

The headings this relies on are the contract written down in
../interview-mode/FORMAT.md. Change one there, change it here.
"""
import re

DASH = "—"  # em dash, as used in the headings

# '## META', '## PROMPT', '## STEP 3 - Deep dive', ... (all-caps h2)
TOP_SECTION = re.compile(r"^## ([A-Z][A-Z0-9 " + DASH + r"\-&/]+)\s*$", re.M)
STEP_HEAD = re.compile(r"^## (STEP \d+ " + DASH + r"[^\n]+|DEEP DIVE[^\n]*)\s*$", re.M)


def top_sections(md):
    """Split a mock file into {SECTION: body} on its all-caps h2 headings."""
    out, ms = {}, list(TOP_SECTION.finditer(md))
    for i, m in enumerate(ms):
        end = ms[i + 1].start() if i + 1 < len(ms) else len(md)
        out[m.group(1).strip()] = md[m.end():end].strip()
    return out


def bullets(block, label):
    """The list items under a '### LABEL' sub-heading."""
    r = re.search(r"^### " + label + r"\s*$(.*?)(?=^### |\Z)", block, re.M | re.S)
    if not r:
        return []
    return [ln.strip("-* •").strip()
            for ln in r.group(1).strip().splitlines()
            if ln.strip().startswith(("-", "*"))]


def parse_steps(md):
    """'## STEP n - name' blocks, each with its checkpoints / traps / followups."""
    steps, ms = [], list(STEP_HEAD.finditer(md))
    for i, m in enumerate(ms):
        body = md[m.end():ms[i + 1].start() if i + 1 < len(ms) else len(md)]
        steps.append({
            "title": m.group(1).strip(),
            # everything before the first '###' is the step's own guidance
            "body": re.split(r"^### ", body, maxsplit=1, flags=re.M)[0].strip(),
            "checkpoints": bullets(body, "CHECKPOINTS"),
            "traps": bullets(body, "TRAPS"),
            "followups": bullets(body, "FOLLOWUPS"),
        })
    return steps


def parse_clarify(text):
    """'- **question?**' followed by an indented arrow line carrying the answer."""
    items, q = [], None
    for line in text.splitlines():
        t = line.strip()
        if t.startswith("- **"):
            q = t.lstrip("- ").strip()
        elif t.startswith("→") and q:
            items.append({"q": q, "a": t.lstrip("→ ").strip()})
            q = None
    return items


def parse_meta(text):
    """'- key: value' lines in the META block."""
    meta = {}
    for line in text.splitlines():
        m = re.match(r"^-\s*([a-z\-]+):\s*(.+)$", line.strip())
        if m:
            meta[m.group(1)] = m.group(2).strip()
    return meta


def parse(md, stem):
    """One mock file -> the dict the app consumes."""
    secs = top_sections(md)
    meta = parse_meta(secs.get("META", ""))
    steps = parse_steps(md)
    return {
        "id": stem,
        "track": "HLD",
        "difficulty": meta.get("difficulty", ""),
        "time": meta.get("time", "45 min"),
        "tags": [t.strip() for t in meta.get("tags", "").split(",") if t.strip()],
        "why": meta.get("why-it-matters", ""),
        "priority": meta.get("priority", "core"),
        "prompt": secs.get("PROMPT", "").strip(),
        "clarify": parse_clarify(secs.get("CLARIFY", "")),
        "steps": steps,
        "checkpoints": sum(len(s["checkpoints"]) for s in steps),
        "rubric": secs.get("RUBRIC", ""),
        "reference": secs.get("REFERENCE", ""),
        "oneliner": secs.get("ONE-LINER", "").strip(),
    }


# ---------------------------------------------------------------------------
# LLD problems
#
# The LLD folders were written as study docs, not as mock files, but they are
# consistent enough to drive a mock: the clarifying questions and the locked
# answers are both numbered lists that line up 1:1, each '## Step n' is a
# stage, and the review notes marked with a pencil are exactly the traps.
# ---------------------------------------------------------------------------

PENCIL = "\U0001f4dd"
H2 = re.compile(r"^## +(.+?)\s*$", re.M)
STEP_H2 = re.compile(r"^Step (\d+)\s*[" + DASH + r"\-]\s*(.+)$")
NUMBERED = re.compile(r"^\d+\.\s+(.*)$")
BULLET = re.compile(r"^[-*]\s+(?:\[[ xX]\]\s*)?(.*)$")


def h2_sections(md):
    """[(heading, body)] for every '## ' heading, in file order."""
    out, ms = [], list(H2.finditer(md))
    for i, m in enumerate(ms):
        end = ms[i + 1].start() if i + 1 < len(ms) else len(md)
        out.append((m.group(1).strip(), md[m.end():end].strip()))
    return out


SEPARATOR = re.compile(r"^\|[\s:|-]+\|$")


def items(body, keep_sub=True):
    """Leaf list items in a block, skipping code fences.

    Sub-headings are folded into the item text ('Functional - Shorten: ...')
    so a flat checkpoint list still says which bucket it came from.

    Table rows score fine as checkpoints, but the HEADER row does not - and a
    header is only identifiable by the separator row that follows it, so this
    needs one line of lookahead rather than a list of known header words.
    """
    out, fence, sub = [], False, ""
    lines = body.splitlines()
    for i, line in enumerate(lines):
        t = line.strip()
        if t.startswith("```"):
            fence = not fence
            continue
        if fence:
            continue
        if t.startswith("### "):
            sub = t[4:].strip()
            # drop the parenthetical coaching in headings like 'Functional (what it DOES)'
            sub = re.sub(r"\s*\(.*?\)\s*$", "", sub).strip()
            continue
        if PENCIL in t or t.startswith(">"):
            continue

        if t.startswith("|") and t.endswith("|"):
            if SEPARATOR.match(t):
                continue                                   # the |---|---| rule
            nxt = next((x.strip() for x in lines[i + 1:] if x.strip()), "")
            if SEPARATOR.match(nxt):
                continue                                   # a separator follows -> header row
            cells = [c.strip() for c in t.strip("|").split("|")]
            if len(cells) < 2 or not cells[0] or not cells[1]:
                continue                                   # blank cell -> not a checkpoint
            out.append(cells[0] + "  " + DASH + "  " + cells[1])
            continue

        m = NUMBERED.match(t) or BULLET.match(t)
        if not m:
            continue
        text = m.group(1).strip()
        if len(text) < 4:
            continue
        out.append(("**" + sub + "** " + DASH + " " + text) if (keep_sub and sub) else text)
    return out


def notes(body):
    """The review notes - lines carrying the pencil marker."""
    out = []
    for line in body.splitlines():
        t = line.strip()
        if PENCIL in t:
            out.append(t.lstrip("->* ").replace(PENCIL, "").strip())
    return out


def strip_lead_italic(body):
    """Drop a leading '_coaching line_' that is not part of the prompt."""
    lines = body.strip().splitlines()
    while lines and lines[0].strip().startswith("_") and lines[0].strip().endswith("_"):
        lines.pop(0)
    return "\n".join(lines).strip()


def parse_lld(md, stem):
    """One LLD problem.md -> the same mock shape as the HLD files."""
    secs = h2_sections(md)
    by = {}
    for head, body in secs:
        by.setdefault(head, body)

    def find(prefix):
        for head, body in secs:
            if head.lower().startswith(prefix):
                return body
        return ""

    qs = items(find("clarifying question"), keep_sub=False)
    ans = items(find("clarification"), keep_sub=False)
    clarify = [{"q": q, "a": ans[i] if i < len(ans) else ""} for i, q in enumerate(qs)]

    steps = []
    for head, body in secs:
        m = STEP_H2.match(head)
        if m:
            name = re.sub(r"\s*[\u2705\u2190].*$", "", m.group(2))
            name = re.sub(r"\s*\(.*?\)\s*$", "", name).strip()
            title = "STEP " + m.group(1) + " " + DASH + " " + name
        elif head.lower().startswith("rest api mapping"):
            title = "STEP " + str(len(steps) + 1) + " " + DASH + " REST API mapping"
        else:
            continue
        cps = items(body)
        if not cps:
            continue
        steps.append({
            "title": title,
            "body": "",
            "checkpoints": cps,
            "traps": notes(body),
            "followups": [],
        })

    return {
        "id": stem,
        "track": "LLD",
        "difficulty": "",
        "time": "45 min",
        "tags": [],
        "why": "",
        "priority": "core",
        "prompt": strip_lead_italic(find("the prompt")),
        "clarify": clarify,
        "steps": steps,
        "checkpoints": sum(len(s["checkpoints"]) for s in steps),
        "rubric": "",
        "reference": "",
        "oneliner": "",
    }
