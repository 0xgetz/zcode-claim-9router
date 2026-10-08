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

## Web console (Level 3)

The console is a four-page SPA served into the cloud browser by the bridge. The
page and the bridge speak a tiny **request/response RPC** over the same CDP
session — the page calls `window.bcodeRpc(JSON)` and the bridge answers with
`window.__bcodeReply(id, ok, data)`. No sockets, ports or tunnels.

```mermaid
flowchart TB
    subgraph Browser["🌐 Cloud browser"]
        UI["console.html (SPA)"]
        subgraph Pages["4 pages"]
            P1["Dashboard"]
            P2["Accounts"]
            P3["Capture"]
            P4["Results"]
        end
        ZT["z.ai tab<br/>(captcha solver)"]
        UI --- Pages
    end

    subgraph Bridge["🐍 console_bridge.py"]
        RPC["RPC dispatcher"]
        ACC["accounts store<br/>accounts.json"]
        RES["results store<br/>results.json"]
        FS["work dir<br/>console_data/"]
        PP["param poller"]
    end

    subgraph Pipeline["⚙️ zcode_claim.py"]
        INJ2["inject"]
        CLM2["claim"]
        CN2["connect"]
        BAT["batch"]
    end

    UI -->|"bcodeRpc"| RPC
    RPC -->|"__bcodeReply"| UI
    RPC --> ACC
    RPC --> RES
    RPC --> FS
    RPC --> INJ2 & CLM2 & CN2 & BAT
    PP -->|reads __capParams| ZT
    PP -->|writes| FS
    P2 --> ACC
    P4 --> RES

    classDef ui fill:#141a30,stroke:#7c5cff,color:#e7ecf3
    classDef br fill:#1b2130,stroke:#5b8cff,color:#e7ecf3
    classDef pl fill:#0d1220,stroke:#22d3ee,color:#e7ecf3
    class UI,P1,P2,P3,P4,ZT ui
    class RPC,ACC,RES,FS,PP br
    class INJ2,CLM2,CN2,BAT pl
```

### RPC actions

| Action | Page | Purpose |
|--------|------|---------|
| `ping` | all | connection heartbeat (top-right dot) |
| `inject` / `claim` / `connect` | Dashboard | single stages |
| `opencaptcha` / `grabparam` | Capture | open the z.ai tab, read the captured param |
| `accounts.list/add/remove/clear/import/export` | Accounts | batch manager |
| `batch.run` | Accounts | run every account through the pipeline |
| `fs.read` / `fs.write` | Results | read/write files in the work dir |
| `results.get` | Results | last run / batch results |
| `status` | Results | jwt-file plan status |

### Screenshots

See [`docs/screenshots/`](screenshots) (dashboard, accounts, capture, results,
mobile) and the walkthrough video [`docs/demo.mp4`](demo.mp4).

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
│   ├── screenshots/               console screenshots (png)
│   ├── demo.mp4                   console walkthrough video
│   ├── record_demo.py             regenerates demo.mp4
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
│   ├── console.html               Web UI console (4-page SPA)
│   ├── console_bridge.py          CDP bridge + RPC backend
│   └── console_data/              work dir (gitignored): accounts, results, param
├── run.sh                         one-command launcher
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
