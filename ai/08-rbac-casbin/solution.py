"""
08 - RBAC with a policy engine, the lossy round-trip bug, and the floor.

    python3 solution.py

A ~30-line Casbin stand-in, then the two bugs that are worth telling in an
interview: a save that destroys what the UI could not render, and a role edit
that locks out the last admin.
"""
# --------------------------------------------------------------------------- #
# a minimal enforcer: policy is DATA, so a grant is a row, not a deploy
# --------------------------------------------------------------------------- #
class Enforcer:
    def __init__(self):
        self.p = set()          # (subject, object, action)
        self.g = set()          # (user, role)

    def add_policy(self, s, o, a): self.p.add((s, o, a))
    def remove_policy(self, s, o, a): self.p.discard((s, o, a))
    def add_role(self, u, r): self.g.add((u, r))

    def roles_of(self, u):
        return {r for (usr, r) in self.g if usr == u} | {u}

    def enforce(self, u, o, a):
        return any((s, o, a) in self.p for s in self.roles_of(u))

    def policies_for(self, subject):
        return {(o, a) for (s, o, a) in self.p if s == subject}


e = Enforcer()
for obj, act in [("resume", "read"), ("resume", "write"), ("bench", "read"),
                 ("payroll", "read"), ("audit", "read")]:
    e.add_policy("admin", obj, act)
e.add_role("ritesh", "admin")

# permissions the admin UI grid can actually render
GRID_CAN_RENDER = {("resume", "read"), ("resume", "write"), ("bench", "read")}

# permissions a super admin keeps no matter what a role edit says
FLOOR = {("audit", "read")}


def save_role_LOSSY(enf, role, checked):
    """THE BUG: PUT the whole role using only what the grid holds."""
    for (o, a) in list(enf.policies_for(role)):
        enf.remove_policy(role, o, a)          # wipe everything...
    for (o, a) in checked:
        enf.add_policy(role, o, a)             # ...restore only the visible


def save_role_PATCH(enf, role, checked):
    """THE FIX: only touch what the grid actually owns."""
    for (o, a) in GRID_CAN_RENDER:
        if (o, a) in checked:
            enf.add_policy(role, o, a)
        else:
            enf.remove_policy(role, o, a)


def apply_floor(enf, role):
    for (o, a) in FLOOR:
        enf.add_policy(role, o, a)


if __name__ == "__main__":
    print("  policy engine: a grant is a ROW, not a deploy")
    print(f"  admin starts with {len(e.policies_for('admin'))} permissions:"
          f" {sorted(e.policies_for('admin'))}\n")

    checked = {("resume", "read"), ("bench", "read")}      # user unticks resume:write

    import copy
    lossy = copy.deepcopy(e); save_role_LOSSY(lossy, "admin", checked)
    patch = copy.deepcopy(e); save_role_PATCH(patch, "admin", checked)

    print("  user unticks resume:write and saves")
    print(f"    LOSSY (PUT whole role) -> {sorted(lossy.policies_for('admin'))}")
    print(f"    PATCH (grid-owned only)-> {sorted(patch.policies_for('admin'))}")
    lost = e.policies_for("admin") - lossy.policies_for("admin") - {("resume", "write")}
    print(f"    SILENTLY DESTROYED by the lossy save: {sorted(lost)}")
    assert ("payroll", "read") in lost and ("audit", "read") in lost
    assert ("payroll", "read") in patch.policies_for("admin")
    print("    -> never round-trip through a lossy representation\n")

    print("  the permission floor")
    print(f"    after a lossy save, can admin read the audit log?"
          f" {lossy.enforce('ritesh', 'audit', 'read')}")
    print("      -> the last administrator is LOCKED OUT, and fixing it")
    print("         requires the permission that was just removed")
    apply_floor(lossy, "admin")
    print(f"    with the floor enforced: {lossy.enforce('ritesh', 'audit', 'read')}")
    assert lossy.enforce("ritesh", "audit", "read")
    print("      -> make the catastrophic state UNREACHABLE, not unlikely\n")

    print("  the factory pattern (why FastAPI DI beats permission_classes)")
    def require_permission(obj, act):          # takes CONFIG
        def dependency(user):                  # RETURNS a dependency
            if not e.enforce(user, obj, act):
                raise PermissionError(f"need {obj}:{act}")
            return user
        return dependency
    guard = require_permission("resume", "write")
    print(f"    require_permission('resume','write')('ritesh') -> {guard('ritesh')}")
    try:
        require_permission("payroll", "write")("ritesh")
    except PermissionError as ex:
        print(f"    require_permission('payroll','write')      -> 403 {ex}")
    print("    -> one function, parameterised per route. DRF needs a CLASS each.")
    print("\nOK - topic 08")
