# Topic 8: authorisation — RBAC, Casbin, field-level policy

## The prompt
> "How did you model permissions in the HR platform? Every field in an HR system is sensitive
> to someone — walk me through how you handled that."

## The follow-up bank
1. RBAC vs ABAC vs ReBAC — which did you use and why?
2. Why a policy engine rather than if-statements?
3. Page-level vs field-level authorisation — why do you need both?
4. A role save destroyed permissions the UI couldn't express. How does that happen?
5. What's a super-admin permission floor and why does it exist?
6. `Depends(require_permission(...))` — why a factory?
7. How do you test an authorisation matrix?
