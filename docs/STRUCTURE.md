# Repository Structure

Component map of **ZCode Claim · 9Router Pipeline**. The diagram below is
Mermaid — GitHub renders it live, so it is a real diagram, not a static image.

```mermaid
flowchart LR
    subgraph Input["🔑 Credentials"]
        A1["z.ai bearer token"]
        A2["z.ai cookies"]
        A3["email + password"]
    end

    subgraph Core["⚙️ src/ — the toolkit"]
        INJ["inject.py<br/>token/cookies → OAuth → JWT"]
        CLM["claim.py<br/>Aliyun captcha + billing/claim"]
        AUT["zauth.py<br/>mint coding-plan API key"]
        CON["connect_9router.py<br/>register as glm connection"]
        CLI["zcode_claim.py<br/>CLI orchestrator"]
        SOL["solverify.py<br/>3rd-party Aliyun solver"]
    end

    subgraph UI["🖥️ Web UI console"]
        HTML["console.html<br/>dashboard page"]
        BRG["console_bridge.py<br/>CDP bridge"]
    end

    subgraph Ext["🌐 External"]
        ZAI["chat.z.ai"]
        ZCODE["zcode.z.ai"]
        ROUTER["9Router / glm"]
        CDP["Cloud browser (CDP)"]
    end

    A1 --> INJ
    A2 --> INJ
    A3 --> INJ
    INJ -->|consent + token exchange| ZAI
    INJ -->|zcode JWT| ZCODE
    INJ --> CLM
    CLM -->|captchaVerifyParam| ZCODE
    SOL -.->|unsigned solve: rejected| CLM
    CLM --> AUT
    AUT --> CON
    CON -->|POST /api/providers| ROUTER

    HTML <-->|Runtime.addBinding| BRG
    BRG -->|runs stages| CLI
    CLI --> INJ
    CLI --> CLM
    CLI --> CON
    BRG <-->|drive + capture| CDP

    classDef core fill:#1b2130,stroke:#5b8cff,color:#e7ecf3
    classDef ui fill:#141a30,stroke:#7c5cff,color:#e7ecf3
    classDef ext fill:#0d1220,stroke:#22d3ee,color:#e7ecf3
    class INJ,CLM,AUT,CON,CLI,SOL core
    class HTML,BRG ui
    class ZAI,ZCODE,ROUTER,CDP ext
```

## Plain-text overview

```
zcode-claim-9router/
├── assets/
│   ├── logo.svg / logo.png        the mark (glowing Z in a router ring)
│   └── banner.svg / banner.png    README header
├── docs/
│   ├── README.id.md               Bahasa Indonesia
│   ├── README.zh.md               中文
│   ├── README.ja.md               日本語
│   ├── README.es.md               Español
│   └── STRUCTURE.md               this file
├── examples/
│   ├── accounts.example.json      batch input shape
│   └── config.example.ini         console / CLI defaults
├── src/
│   ├── inject.py                  token|cookies → ZCode OAuth → JWT
│   ├── claim.py                   Aliyun Captcha 2.0 + billing/claim
│   ├── zauth.py                   z.ai coding-plan API-key minting
│   ├── connect_9router.py         register a key as a `glm` connection
│   ├── zcode_claim.py             CLI orchestrator (single / batch)
│   ├── solverify.py               Solverify Aliyun solver client
│   ├── console.html               Web UI dashboard
│   └── console_bridge.py          CDP bridge for the dashboard
├── CONTRIBUTING.md
├── LICENSE
└── README.md
```

## Stage-by-stage data flow

| # | Stage | Module | Input | Output | Verified |
|---|-------|--------|-------|--------|----------|
| 1 | Inject | `inject.py` | token / cookies | ZCode JWT | ✅ |
| 2 | Claim | `claim.py` | JWT + `captchaVerifyParam` | Start Plan active | ⚠️ interactive captcha |
| 3 | Mint key | `zauth.py` | z.ai access token | coding-plan API key | ✅ |
| 4 | Connect | `connect_9router.py` | API key | `glm` connection | ✅ |

## Why the claim needs an interactive solve

```mermaid
sequenceDiagram
    participant U as User (z.ai tab)
    participant S as Aliyun SDK
    participant Z as z.ai server
    U->>S: drag slider
    S->>S: verify interactively
    S-->>U: captchaVerifyParam {certifyId, sceneId, isSign, securityToken}
    U->>Z: POST billing/claim + param
    Z->>Z: bind to page session, check signature
    Z-->>U: 200 OK  (only for a real in-page solve)

    Note over S,Z: Third-party solvers return an UNSIGNED param<br/>with no page-session binding → Z replies 3007 / 3001
```
