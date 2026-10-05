# Multi-tenancy — diagrams

## 1. The whole system, end to end

```mermaid
flowchart TB
    CL["Client<br/>tenant A user, or superadmin"] --> API["API edge<br/>authn, JWT to principal"]
    API --> TS{"callerTenantScope<br/>which tenant is this?"}
    TS -->|"superadmin act-as"| AU["Audit log<br/>who acted as which tenant"]
    AU --> SC["resolveScopeTenant<br/>the one funnel"]
    TS -->|"ordinary user"| SC
    SC --> H["Handlers<br/>users, personas, conversations"]
    SC --> RG["RAG path<br/>ragContextIdOf persona"]
    H --> DB[("Postgres<br/>every read carries tenant_id")]
    RG --> VX[("Vector store<br/>one namespace per persona")]
    DB --> RESP["Response<br/>only this tenant's rows"]
    VX --> RESP
    TS -->|"nothing resolves"| FC["Fail closed sentinel<br/>matches no rows"]
    FC --> RESP
    RESP --> CL
    SC --- PB["17 cross-tenant probes<br/>test this one place"]
```

Everything below is a zoom into one part of this path. The two load-bearing
claims: tenant resolution happens once at the edge, and no handler is trusted to
remember the filter — it asks the funnel.

## 2. Fail closed vs fail open

```mermaid
flowchart TB
    R[Request arrives] --> C{callerTenantScope<br/>resolves a tenant?}
    C -->|yes| OK[filter by that tenant]
    C -->|no, superadmin| ACT[audited act-as path]
    C -->|"no, ordinary user"| FC["FAIL CLOSED<br/>sentinel matching NO rows"]
    FC --> E[empty result / 404]
    C -.->|"THE BUG: no tenant = no filter"| FO["FAIL OPEN<br/>every tenant's data"]
    FO -.-> LEAK[catastrophic leak]
```

## 3. One funnel, not scattered filters

#### Scattered — relies on memory

```mermaid
flowchart LR
    H1[users handler] --> W1["WHERE tenant_id = ?"]
    H2[conversations] --> W2["WHERE tenant_id = ?"]
    H3[new endpoint] --> W3["...forgot"]
    W3 --> LK[leak]
```

#### One primitive

```mermaid
flowchart LR
    G1[users] --> RS[resolveScopeTenant]
    G2[conversations] --> RS
    G3[RAG ingest/query] --> RS
    G4[new endpoint] --> RS
    RS --> Q[(scoped query)]
    RS --- T["17 probes test<br/>ONE place"]
```

The scattered version fails on the endpoint nobody remembered. The funnel version
has exactly one place to get right, and therefore exactly one place to test.

## 4. RAG isolation is structural

#### Filtered — weaker

```mermaid
flowchart TB
    Q1[query] --> IX1[("one shared index<br/>all tenants' chunks")]
    IX1 --> PF{"post-filter<br/>by tenant"}
    PF -->|"bug here"| CL[content leak]
    PF -->|"filter holds"| OK1["A's chunks only,<br/>this time"]
```

#### Namespaced — structural

```mermaid
flowchart TB
    Q2[query] --> RC[ragContextIdOf persona]
    RC --> IX2[("persona A namespace")]
    IX2 --> OUT["only A's chunks were<br/>ever in the searched set"]
```

Filtering is one forgotten predicate away from a leak, because another tenant's
chunks were in the searched set. Namespacing removes the set, so there is nothing
to filter out.

## 5. The probe matrix

#### The two axes

```mermaid
flowchart LR
    S["SURFACES<br/>what data is asked for"] --> U[users]
    S --> P[personas]
    S --> C[conversations]
    S --> R[RAG]
    A["ACCESS SHAPES<br/>how it is asked for"] --> L[list]
    A --> D[detail]
    A --> E[export]
    A --> X[reindex]
```

#### What every cell asserts

```mermaid
flowchart LR
    S2["every surface"] --> M["tenant A requests tenant B<br/>assert: nothing returned"]
    A2["every access shape"] --> M
    M --> V["17 probes: a regression floor,<br/>not a proof"]
```

Export and reindex are the cells teams forget: they are read paths that do not
look like reads.
