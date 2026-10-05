# Authorisation — diagrams

## 1. The whole system, end to end

Two paths through one policy store: the request path (top) and the administration path (bottom).

```mermaid
flowchart TB
    CL["Client<br/>HR web app"] --> SSO["AuthN<br/>Microsoft SSO, session"]
    SSO --> API["FastAPI route<br/>Depends(require_permission(res, act))"]
    API --> ENF["Casbin enforcer, per node<br/>model.conf shape + cached policy rows"]
    ENF --> DB[("Postgres casbin_rule<br/>policy as data, filtered per tenant")]
    ENF -->|deny| E403["403<br/>page-level stop"]
    ENF -->|allow| H["handler runs<br/>reads HR data"]
    H --> FP["field_policy.py<br/>one visible-field set per request"]
    FP --> RESP["response<br/>only the fields THIS subject may see"]
    RESP --> CL
    ADM["Admin<br/>role / permission grid UI"] --> WR["policy write API<br/>PATCH what the grid owns, floor applies"]
    WR --> DB
    WR --> AUD["append-only change log<br/>who, when, before, after"]
    WR --> INV["Redis pub/sub invalidation<br/>revoke sync, grant lazy"]
    INV --> ENF
```

## 2. The layers

```mermaid
flowchart TB
    R[Request] --> A{"AuthN — who are you?<br/>Microsoft SSO / session"}
    A -->|unknown| E401[401]
    A -->|known| P{"page-level authz<br/>Depends(require_permission(res, act))<br/>-> casbin enforce"}
    P -->|denied| E403[403]
    P -->|allowed| H[handler runs]
    H --> F{"field-level policy<br/>field_policy.py"}
    F --> OUT["response with only the fields<br/>THIS subject may see"]
    F -.->|"missing this layer"| LEAK["page allowed but salary column leaks"]
```

## 3. Casbin: model vs policy

```mermaid
flowchart LR
    M["MODEL (.conf)<br/>the shape, in code"] --> M1["request: sub, obj, act"]
    M --> M2["policy: sub, obj, act"]
    M --> M3["matcher: how to compare them"]
    P["POLICY (Postgres casbin_rule)<br/>the rules, as data"] --> P1["p, admin, resume, write"]
    P --> P2["p, viewer, resume, read"]
    P --> P3["g, ritesh, admin"]
    M --> E["enforcer.enforce sub, obj, act"]
    P --> E
    E --> D{allow / deny}
    P --- N["changes with a ROW,<br/>not a deploy"]
```

## 4. The lossy round-trip bug

```mermaid
flowchart TB
    S[(policy store<br/>rich: 40 permissions)] --> UI["permission grid UI<br/>can render only 30"]
    UI --> V["user edits, clicks Save"]
    V --> W{"write strategy"}
    W -->|"BUG: PUT whole role<br/>with what the grid holds"| L["the 10 unrepresentable<br/>permissions DELETED"]
    W -->|"FIX: PATCH only<br/>what the grid owns"| K["the other 10 untouched"]
    L --> G["general lesson:<br/>never round-trip through<br/>a lossy representation"]
```

## 5. The permission floor

```mermaid
flowchart TB
    RE[admin edits a role] --> C{"does the edit remove a<br/>permission from a super admin?"}
    C -->|"no floor"| LO["super admin loses it<br/>-> LOCKED OUT<br/>-> fixing it needs the permission<br/>they just lost"]
    C -->|"floor enforced"| FL["floor permissions are<br/>unconditionally granted<br/>-> edit cannot reach them"]
    FL --> SAFE["catastrophic state is UNREACHABLE,<br/>not merely unlikely"]
```
