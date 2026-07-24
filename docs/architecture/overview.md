# System Architecture

## System context

```mermaid
flowchart TB
    subgraph clients[Clients]
        UI[Analyst UI / notebook]
        SVC[Internal service]
    end
    subgraph engine[Text-to-SQL Engine]
        API[FastAPI layer]
        ORCH[Application Orchestrator]
        LLM[(LLM provider<br/>fake / OpenAI-compatible)]
    end
    subgraph data[Data plane]
        PG[(PostgreSQL / SQLite)]
        ROLE[Read-only role]
    end
    UI -->|HTTPS + auth headers| API
    SVC -->|HTTPS + auth headers| API
    API --> ORCH
    ORCH -->|prompt| LLM
    LLM -->|structured SQL| ORCH
    ORCH -->|validated read-only SQL| ROLE
    ROLE --> PG
```

The engine is a **stateless** HTTP service. The only stateful dependencies are the
database and (optionally) an LLM provider. Horizontal scaling is a matter of
running more replicas behind a load balancer; there is no server-side session
state (the schema cache is a per-process optimisation, safely rebuilt on demand).

## Component architecture

```mermaid
flowchart TB
    API[api/*: routes, DI, error envelope]
    ORCH[application/orchestrator.py]
    subgraph pipeline[Pipeline components]
        NORM[Request auth/normalize]
        AMB[application/ambiguity.py]
        RET[retrieval/retriever.py]
        DATES[semantic/dates.py]
        PROMPT[llm/prompt.py]
        PROV[llm/* provider]
        PARSE[sql/parser.py]
        VAL[sql/validator.py]
        POL[security/policy.py]
        REW[security/rewriter.py]
        COST[security/cost.py]
        REPAIR[application/repair.py]
        EXEC[execution/executor.py]
        EXP[application/explainer.py]
    end
    CAT[schema/catalog.py]
    SEM[semantic/*]
    OBS[observability/*]
    API --> ORCH
    ORCH --> NORM --> AMB --> RET --> DATES --> PROMPT --> PROV
    PROV --> PARSE --> VAL --> POL --> REW --> COST --> EXEC --> EXP
    VAL -. repairable .-> REPAIR -. re-prompt .-> PROV
    RET --> CAT
    CAT --> SEM
    ORCH --> OBS
```

Layering follows **dependency inversion**: high-level policy (the orchestrator)
depends on abstractions (`LLMProvider` protocol, `SchemaRetriever` protocol),
never on concrete adapters. The composition root
([`application/container.py`](../../src/text_to_sql/application/container.py)) is
the single place where concrete implementations are chosen.

Dependency direction (arrows point to what a layer may import):

```mermaid
flowchart LR
    api --> application --> domain
    application --> security --> sql --> domain
    application --> retrieval --> semantic --> domain
    application --> schema --> infrastructure --> domain
    application --> llm --> domain
    common --> nothing[stdlib only]
    domain --> common
    observability --> common
```

`common`, `domain`, and `observability` sit at the bottom and never import upward,
which is what keeps the security core unit-testable **without** a server or a
database.

## Request sequence (execute path)

```mermaid
sequenceDiagram
    autonumber
    participant C as Client
    participant A as FastAPI
    participant O as Orchestrator
    participant R as Retriever
    participant P as Provider
    participant V as Validator+Policy+Rewriter+Cost
    participant D as Read-only DB
    C->>A: POST /api/v1/query (+ auth headers)
    A->>O: process(request, auth)
    O->>O: authorize tenant, detect ambiguity
    alt ambiguous
        O-->>C: 409 clarification
    else proceed
        O->>R: retrieve relevant schema
        O->>P: generate(prompt)
        P-->>O: structured SQL candidate
        loop up to max_repair_attempts
            O->>V: parse → AST validate → policy → tenant rewrite → re-validate → cost
            alt secured
                Note over O,V: break
            else repairable
                O->>P: regenerate with sanitized feedback
            else hard failure
                O-->>C: typed error envelope
            end
        end
        O->>D: execute validated, tenant-scoped, LIMITed SQL
        D-->>O: bounded rows
        O->>O: build grounded explanation
        O-->>C: 200 QueryResponse
    end
```

## Trust boundaries

```mermaid
flowchart TB
    subgraph untrusted[Untrusted]
        UQ[User question]
        LLMOUT[LLM output SQL]
        META[DB comments / column names / samples]
    end
    subgraph trusted[Trusted / deterministic]
        AUTH[Auth context from transport]
        CATALOG[Schema catalog]
        POLICY[Policy + rewriter + cost + validator]
    end
    UQ --> POLICY
    LLMOUT --> POLICY
    META --> POLICY
    AUTH --> POLICY
    CATALOG --> POLICY
    POLICY --> SAFE[Only validated SQL reaches the DB]
```

Everything the model reads or writes is untrusted. The **authenticated context**
(established by the transport/gateway) and the **schema catalog** are trusted. The
deterministic security layer is the gate between them. This is elaborated in the
[threat model](../security/threat_model.md).
