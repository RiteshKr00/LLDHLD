# Authorisation — explained

**Your code — and this is under-claimed on your resume:**

| Anchor | What it is |
|---|---|
| `backend/authz/enforcer.py:9-22` | **Casbin**, with `casbin_sqlalchemy_adapter` → Postgres `casbin_rule` table |
| `backend/authz/permissions.py:220` | `require_permission(resource, action)` — a **dependency factory** |
| `backend/authz/field_policy.py` | 106 lines of **field-level** read policy |
| `backend/authz/seed.py`, `sync.py` | policy seeding and synchronisation |
| `backend/tests/test_authz_matrix.py` | the matrix test |

**Lead with the fact that it's a policy engine.** "Role and per-user page permissions" makes
it sound like if-statements. You integrated Casbin with a database-backed policy store — a
materially stronger claim.

---

## The three models, and which you used

| Model | Rule shape | Good for |
|---|---|---|
| **RBAC** | user → role → permission | most apps; simple to reason about |
| **ABAC** | attributes of user/resource/environment | "own department only", time-bounded |
| **ReBAC** | relationship graph | "manager of the owner of this doc" |

Yours is **RBAC with per-user overrides** — roles grant, and individual users can be granted
or **denied** specific pages on top. That hybrid is where the interesting bugs live, because
grant and deny now interact.

---

## Casbin: the model / policy split

- **Model** (`.conf`) — the *shape* of a rule and the matcher: `sub, obj, act` plus how a
  request is matched against stored policies.
- **Policy** (rows) — the actual rules: `p, admin, resume, write`.

The split matters because **policy changes without a deploy.** Rules live in Postgres, so
granting a permission is a row, not a release. That's the reason to use an engine rather than
if-statements — and it's the answer to "why not just code it?"

The enforcer is **loaded lazily** (`:16-22`), falling back to a file-based policy when
`DATABASE_URL` isn't set — so tests and local dev don't need Postgres.

---

## Page-level vs field-level — why both

**Page-level:** can this user open Bench Analysis at all?
**Field-level:** they can open the roster — but can they see the `salary` column?

An HR system needs both because the *same page* serves users who should see different columns
of the same row. A manager sees their reports' ratings; a peer doesn't. Page-level authz
cannot express that, which is why `field_policy.py` exists as a separate layer.

**The general principle to say:** authorisation isn't binary per endpoint, it's per
**(subject, resource, field)**. Systems that only do endpoint-level authz end up leaking
through response payloads.

---

## The bug worth telling: a role save destroying permissions

**What happened.** The permission grid in the UI could express a subset of what the policy
store could hold. Saving a role wrote back *only what the grid could represent* — silently
deleting any permission the UI had no checkbox for.

**Why it's a great interview story:** it's a **lossy-round-trip** bug, and the class
generalises. Any time a UI reads a rich model, renders a lossy view, and writes the whole
thing back, it destroys what it couldn't display. The fix is either to make writes **partial**
(patch only what the grid owns) or to make the view **complete**.

**The general lesson:** *never round-trip through a lossy representation.* That sentence
applies to config UIs, API PATCH-vs-PUT design, and serialisation. Say it — it shows you
extracted a principle, not just a patch.

---

## The super-admin permission floor

A role edit could remove a permission from a super admin — **locking the last administrator
out of the system**, with no way back in because fixing it required the permission you just
removed.

The floor: certain permissions are **unconditionally granted** to super admins, below the
reach of any role edit. It's the same family as fail-closed — **make the catastrophic state
unreachable rather than merely unlikely.**

---

## Why `require_permission` is a factory

```python
def require_permission(resource: str, action: str):   # takes CONFIG
    def dependency(user = Depends(current_user)):     # RETURNS a dependency
        if not enforcer.enforce(subject_for_user(user), resource, action):
            raise HTTPException(403, ...)
        return user
    return dependency
```

`require_permission` is **not** a dependency — it's a function returning one. That's what lets
it be parameterised per route:

```python
_user: dict = Depends(require_permission("resume", "write"))
```

DRF's `permission_classes` can't do this without a class per permission. It's the cleanest
thing FastAPI's DI does that DRF doesn't — and you shipped it.

---

## Testing an authorisation matrix

`test_authz_matrix.py` does the right thing: enumerate **(role × endpoint × action)** and
assert allowed/denied for every cell. Because routes are introspectable, the test can walk
`app.routes` and fail when a **new endpoint appears with no matrix entry** — so a route added
without an authz decision breaks the build rather than shipping open.

That last property is the one to mention. It converts "we remembered to add authz" from
discipline into a build failure.

---

## One-line summary
> "Casbin with a Postgres-backed policy store, so permissions are data not deploys — RBAC with
> per-user overrides, plus a separate field-level layer because the same page serves users who
> should see different columns."

## The trap answer to avoid
Describing it as "we check the user's role in each endpoint." That's the thing a policy engine
exists to replace, and it undersells work you actually did.
