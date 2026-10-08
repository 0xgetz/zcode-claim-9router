<div align="center">

<img src="assets/banner.png" alt="ZCode Claim — 9Router Pipeline" width="820">

# ZCode Claim · 9Router Pipeline

**Take an existing z.ai account → mint a ZCode JWT → claim the free Start Plan → connect GLM to 9Router.**

[![License: MIT](https://img.shields.io/badge/License-MIT-22d3ee?style=flat-square)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.9%2B-5b8cff?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![9Router](https://img.shields.io/badge/9Router-glm%20provider-7c5cff?style=flat-square)](https://9router.com)
[![Platform](https://img.shields.io/badge/Cloud-Browser%20%2F%20CDP-0ea5e9?style=flat-square)](#architecture)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-38c172?style=flat-square)](CONTRIBUTING.md)

[English](README.md) · [Indonesia](docs/README.id.md) · [中文](docs/README.zh.md) · [日本語](docs/README.ja.md) · [Español](docs/README.es.md)

</div>

---

## What this is

A small, dependency-light toolkit that automates the **ZCode** free-trial
("Start Plan") workflow and wires the result into **9Router** as a `glm`
provider pool. It is the automation counterpart to the official ZCode desktop
app: everything the app does through its UI, this does through its HTTP APIs and
a CDP-controlled Chromium.

> Reverse-engineered from **ZCode 3.14.4** (`ZCode-3.14.4-linux-x64.AppImage` →
> `resources/app.asar` → `out/host/index.js`, `out/renderer/assets/*`).

### The free Start Plan

| Entitlement | Free quota |
|-------------|-----------|
| **GLM-5.3**       | **3,000,000 tokens / day** |
| **GLM-5.3-Flash** | **5,000,000 tokens / day** |

`plan_id = "zcode-v3-start-plan"`. Without it, only the flash models
(`glm-4.5-flash`, `glm-4.7-flash`, `glm-4.6v-flash`) are free and the flagship
**GLM-5.3 returns `1113 Insufficient balance`**.

## Pipeline

```
z.ai token / cookies ──▶ OAuth consent ──▶ ZCode JWT ──▶ claim Start Plan ──▶ mint plan key ──▶ 9Router (glm)
      inject.py            chat.z.ai       zcode.z.ai        billing/claim        zauth.py      connect_9router.py
```

| Stage | Status |
|-------|--------|
| Inject token/cookies → ZCode JWT | ✅ verified |
| Claim Start Plan (Aliyun Captcha 2.0 gate) | ⚠️ needs an interactive solve |
| Mint z.ai coding-plan API key | ✅ verified |
| Register key into 9Router `glm` pool | ✅ verified against a mock 9Router |

## Two ways to run it

### 1. Web UI console (recommended)

A clickable dashboard is injected into a cloud browser; its buttons drive the
pipeline over the same CDP session — no ports, no tunnels.

```bash
python src/console_bridge.py --cdp "$BU_CDP_WS"
```

Open the browser's live view. The **ZCode Pipeline Console** lets you:

1. **Inject** — paste a z.ai bearer token and/or cookies → *Inject / mint JWT*.
2. **Claim** — *Open z.ai captcha tab*, solve the slider; the
   `captchaVerifyParam` is captured automatically → *Claim Start Plan*.
3. **Connect** — set the 9Router base/password → *Connect to 9Router*.

### 2. CLI orchestrator

```bash
# inject a token, mint the JWT, submit a human-solved captcha, connect 9Router
python src/zcode_claim.py --cdp "$BU_CDP_WS" --email me@x.com --token eyJ... \
    --captcha-param '<param>' --connect --base http://localhost:20128

# batch of accounts → register every key into the glm pool
python src/zcode_claim.py --cdp "$BU_CDP_WS" --accounts accounts.json \
    --connect --base http://localhost:20128 --out claimed.json

# check a JWT you already hold
python src/zcode_claim.py --jwt-file zjwt.txt --status
```

## Requirements

- Python 3.9+
- `websockets` (for the console bridge) and `playwright` (for browser-driven steps)
- A Chromium reachable over CDP (e.g. a Browser Use cloud browser via `$BU_CDP_WS`)

```bash
pip install websockets playwright
```

## Repository layout

```
zcode-claim-9router/
├── assets/            logo + banner (svg + png)
├── docs/              README translations (id, zh, ja, es) + STRUCTURE.md
├── examples/          sample account / config files
├── src/               the toolkit
│   ├── inject.py          token/cookies → ZCode OAuth → JWT
│   ├── claim.py           Aliyun captcha + billing/claim
│   ├── zauth.py           z.ai coding-plan API-key minting
│   ├── connect_9router.py register a key as a glm connection
│   ├── zcode_claim.py     CLI orchestrator
│   ├── solverify.py       third-party Aliyun solver client
│   ├── console.html       Web UI dashboard
│   └── console_bridge.py  CDP bridge for the dashboard
├── CONTRIBUTING.md
├── LICENSE
└── README.md
```

See [`docs/STRUCTURE.md`](docs/STRUCTURE.md) for the full component diagram.

## The captcha wall (please read)

The `billing/claim` call is gated by **Aliyun Captcha 2.0** (scene `11xygtvd`,
prefix `no8xfe`, region `sgp`). The server demands a **signed, interactive**
`captchaVerifyParam` produced *inside z.ai's own page*:

- A third-party solver (Solverify) returns a genuine solve, but in the
  **unsigned** shape and without the page-session binding → the claim rejects it
  (`3007` / `3001`).
- Scripted drags of the SDK slider are **silently rejected** regardless of
  accuracy (behavioural detection).
- Therefore the claim step expects a real interactive solve. The Web UI console
  exists to make that single step painless: solve once in the z.ai tab and the
  param flows through automatically.

## Responsible use

- Claiming trial quota through automation **breaches z.ai's Terms of Service**.
  Run this only on accounts you own, and know the risk.
- The Start Plan is **one per account and one-time**; a used plan cannot be
  re-claimed.
- `billing/claim` **rate-limits** (HTTP 429) — space out attempts.

## License

[MIT](LICENSE) © 0xgetz
