<div align="center">

<img src="../assets/banner.png" alt="ZCode Claim — 9Router Pipeline" width="820">

# ZCode Claim · 9Router Pipeline

**既存の z.ai アカウント → ZCode JWT を発行 → 無料 Start Plan を取得 → GLM を 9Router に接続。**

[![License: MIT](https://img.shields.io/badge/License-MIT-22d3ee?style=flat-square)](../LICENSE)
[![Python](https://img.shields.io/badge/Python-3.9%2B-5b8cff?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![9Router](https://img.shields.io/badge/9Router-glm%20provider-7c5cff?style=flat-square)](https://9router.com)
[![Platform](https://img.shields.io/badge/Cloud-Browser%20%2F%20CDP-0ea5e9?style=flat-square)](#アーキテクチャ)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-38c172?style=flat-square)](../CONTRIBUTING.md)

[English](../README.md) · [Indonesia](README.id.md) · [中文](README.zh.md) · **日本語** · [Español](README.es.md)

</div>

---

## これは何か

**ZCode** の無料トライアル(「Start Plan」)ワークフローを自動化し、その結果を
**9Router** の `glm` プロバイダプールへ接続する、依存の少ない軽量ツールキット
です。公式 ZCode デスクトップアプリの自動化版にあたります。アプリが UI 経由で
行うことを、本ツールは HTTP API と CDP 制御の Chromium 経由で行います。

> **ZCode 3.14.4** からのリバースエンジニアリング
> (`ZCode-3.14.4-linux-x64.AppImage` → `resources/app.asar` →
> `out/host/index.js`, `out/renderer/assets/*`)。

### 無料 Start Plan

| 権利 | 無料枠 |
|------|--------|
| **GLM-5.3**       | **3,000,000 トークン / 日** |
| **GLM-5.3-Flash** | **5,000,000 トークン / 日** |

`plan_id = "zcode-v3-start-plan"`。これが無い場合、無料なのは flash モデル
(`glm-4.5-flash`, `glm-4.7-flash`, `glm-4.6v-flash`)のみで、フラッグシップの
**GLM-5.3 は `1113 Insufficient balance` を返します**。

## パイプライン

```
z.ai token / cookies ──▶ OAuth 同意 ──▶ ZCode JWT ──▶ Start Plan 取得 ──▶ plan key 発行 ──▶ 9Router (glm)
      inject.py         chat.z.ai       zcode.z.ai      billing/claim        zauth.py      connect_9router.py
```

| ステージ | 状態 |
|----------|------|
| token/cookies → ZCode JWT | ✅ 検証済み |
| Start Plan 取得(Aliyun Captcha 2.0 ゲート) | ⚠️ 対話的解決が必要 |
| z.ai coding-plan API key 発行 | ✅ 検証済み |
| key を 9Router `glm` プールへ登録 | ✅ モック 9Router に対して検証済み |

## 実行方法は2通り

### 1. Web UI コンソール(推奨)

クリック可能なダッシュボードがクラウドブラウザに注入され、そのボタンが同じ
CDP セッション経由でパイプラインを駆動します — ポートもトンネルも不要。

```bash
python src/console_bridge.py --cdp "$BU_CDP_WS"
```

ブラウザのライブビューを開きます。**ZCode Pipeline Console** で:

1. **Inject** — z.ai bearer token と/または cookies を貼り付け → *Inject / mint JWT*。
2. **Claim** — *Open z.ai captcha tab* でスライダーを解決すると
   `captchaVerifyParam` が自動取得 → *Claim Start Plan*。
3. **Connect** — 9Router の base/password を入力 → *Connect to 9Router*。

### 2. CLI オーケストレータ

```bash
# token を注入、JWT を発行、人手解決した captcha を送信、9Router へ接続
python src/zcode_claim.py --cdp "$BU_CDP_WS" --email me@x.com --token eyJ... \
    --captcha-param '<param>' --connect --base http://localhost:20128

# アカウント一括 → 各 key を glm プールへ登録
python src/zcode_claim.py --cdp "$BU_CDP_WS" --accounts accounts.json \
    --connect --base http://localhost:20128 --out claimed.json

# 既に持っている JWT を確認
python src/zcode_claim.py --jwt-file zjwt.txt --status
```

## 要件

- Python 3.9+
- `websockets`(コンソールブリッジ)と `playwright`(ブラウザ駆動ステップ)
- CDP で到達可能な Chromium(例: `$BU_CDP_WS` 経由の Browser Use クラウドブラウザ)

```bash
pip install websockets playwright
```

## リポジトリ構成

```
zcode-claim-9router/
├── assets/            ロゴ + バナー(svg + png)
├── docs/              README 翻訳(id, zh, ja, es)+ STRUCTURE.md
├── examples/          サンプルのアカウント / 設定ファイル
├── src/               ツールキット
│   ├── inject.py          token/cookies → ZCode OAuth → JWT
│   ├── claim.py           Aliyun captcha + billing/claim
│   ├── zauth.py           z.ai coding-plan API key 発行
│   ├── connect_9router.py key を glm 接続として登録
│   ├── zcode_claim.py     CLI オーケストレータ
│   ├── solverify.py       サードパーティ Aliyun ソルバクライアント
│   ├── console.html       Web UI ダッシュボード
│   └── console_bridge.py  ダッシュボード用 CDP ブリッジ
├── CONTRIBUTING.md
├── LICENSE
└── README.md
```

全体のコンポーネント図は [`docs/STRUCTURE.md`](STRUCTURE.md) を参照。

## captcha の壁(必読)

`billing/claim` は **Aliyun Captcha 2.0**(scene `11xygtvd`、prefix `no8xfe`、
region `sgp`)で保護されています。サーバは *z.ai 自身のページ内* で生成された
**署名済み・対話的**な `captchaVerifyParam` を要求します:

- サードパーティソルバ(Solverify)は本物の解を返しますが、**未署名**の形で
  ページセッション束縛も無いため → claim は拒否します(`3007` / `3001`)。
- SDK スライダーのスクリプト操作は、精度に関わらず**静かに拒否**されます
  (挙動検出)。
- したがって claim ステップは実際の対話的解決を前提とします。Web UI コンソール
  はその一手間を無くすため:z.ai タブで一度解決すれば param が自動で流れます。

## 責任ある利用

- 自動化によるトライアル枠の取得は **z.ai の利用規約に違反**します。所有する
  アカウントでのみ実行し、リスクを理解してください。
- Start Plan は **アカウントごとに1回限り**;使用済みプランは再取得できません。
- `billing/claim` は**レート制限**(HTTP 429)があります — 試行間隔を空けて
  ください。

## ライセンス

[MIT](../LICENSE) © 0xgetz
