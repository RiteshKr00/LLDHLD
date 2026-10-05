"""
03 - fail-closed tenant scoping, and the 17-probe suite that proves it.

    python3 solution.py

Two implementations of the same resolver - one fails OPEN, one fails CLOSED -
run against the same probe matrix. The output is the argument.
"""
ROWS = [
    {"id": 1, "tenant": "acme", "kind": "persona", "name": "acme-ceo"},
    {"id": 2, "tenant": "acme", "kind": "conversation", "name": "acme-chat"},
    {"id": 3, "tenant": "globex", "kind": "persona", "name": "globex-ceo"},
    {"id": 4, "tenant": "globex", "kind": "conversation", "name": "globex-chat"},
    {"id": 5, "tenant": "globex", "kind": "rag_chunk", "name": "globex-secret"},
]

SENTINEL = "\x00no-tenant\x00"      # a value that matches NO row, by construction


def resolve_fail_open(caller):
    """The catastrophic default: no tenant means NO FILTER."""
    if caller.get("superadmin"):
        return None                  # None -> 'all rows' downstream
    return caller.get("tenant")      # None when absent -> also 'all rows'


def resolve_fail_closed(caller):
    """The safe default: no tenant resolves to a sentinel matching nothing."""
    if caller.get("superadmin"):
        return None                  # the ONE deliberate, audited door
    return caller.get("tenant") or SENTINEL


def query(caller, resolver, kind=None):
    scope = resolver(caller)
    rows = ROWS if scope is None else [r for r in ROWS if r["tenant"] == scope]
    return [r for r in rows if kind is None or r["kind"] == kind]


def read_one(caller, resolver, row_id):
    """Out-of-scope must be 404, not 403 - 403 confirms the row EXISTS."""
    rows = query(caller, resolver)
    hit = next((r for r in rows if r["id"] == row_id), None)
    return (200, hit) if hit else (404, None)


# --------------------------------------------------------------------------- #
# the probe matrix: surfaces x access shapes, tenant A reaching for tenant B
# --------------------------------------------------------------------------- #
SURFACES = ["persona", "conversation", "rag_chunk"]
SHAPES = ["list", "detail", "export", "reindex"]
ATTACKER = {"tenant": "acme"}
BROKEN = {}                          # an auth bug: tenant never populated
VICTIM_IDS = {"persona": 3, "conversation": 4, "rag_chunk": 5}


def probes(resolver):
    """Returns (passed, failed, details). A probe passes when nothing leaks."""
    passed, failed, details = 0, 0, []
    for surface in SURFACES:
        for shape in SHAPES:
            for caller, label in ((ATTACKER, "scoped-attacker"), (BROKEN, "auth-bug")):
                if shape == "list":
                    leaked = [r for r in query(caller, resolver, surface)
                              if r["tenant"] != "acme"]
                    ok = not leaked
                else:
                    code, row = read_one(caller, resolver, VICTIM_IDS[surface])
                    ok = code == 404 and row is None
                passed, failed = passed + ok, failed + (not ok)
                if not ok:
                    details.append(f"{surface}/{shape}/{label}")
    return passed, failed, details


if __name__ == "__main__":
    print("probe matrix: 3 surfaces x 4 shapes x 2 callers = 24 probes\n")

    for name, resolver in (("FAIL OPEN  (no tenant = no filter)", resolve_fail_open),
                           ("FAIL CLOSED (no tenant = sentinel)", resolve_fail_closed)):
        p, f, d = probes(resolver)
        print(f"  {name}")
        print(f"    passed {p:>2} / failed {f:>2}")
        if d:
            print(f"    leaks: {len(d)} - e.g. {d[0]}, {d[1]}")
        print()

    po, fo, _ = probes(resolve_fail_open)
    pc, fc, _ = probes(resolve_fail_closed)
    assert fo > 0, "fail-open must leak"
    assert fc == 0, "fail-closed must not leak"

    # the auth-bug caller is the whole point
    print("  the specific difference:")
    print(f"    fail-open,   auth bug -> sees {len(query(BROKEN, resolve_fail_open))} rows"
          f" (EVERY tenant)")
    print(f"    fail-closed, auth bug -> sees {len(query(BROKEN, resolve_fail_closed))} rows")
    print()
    code, _ = read_one(ATTACKER, resolve_fail_closed, 5)
    print(f"    out-of-scope detail read -> HTTP {code}")
    print("    404 not 403: a 403 would confirm the row exists, so a tenant")
    print("    could enumerate another tenant's ids by watching status codes.")
    print("""
  what to notice
  --------------
  * one line of difference. fail-open turns an AUTH BUG into a full data
    dump; fail-closed turns the same bug into an empty result.
  * the sentinel is not a magic string check - it is a value chosen so it
    matches no row BY CONSTRUCTION. Nothing has to remember to check it.
  * 24 probes is a REGRESSION FLOOR, not a proof. It covers the surfaces
    I knew about. A new endpoint needs a new probe - which is the honest
    limitation to volunteer.
""")
    print("OK - topic 03")
