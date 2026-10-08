<div align="center">

<img src="../assets/banner.png" alt="ZCode Claim — 9Router Pipeline" width="820">

# ZCode Claim · 9Router Pipeline

**Ambil akun z.ai yang sudah ada → cetak JWT ZCode → klaim Start Plan gratis → sambungkan GLM ke 9Router.**

[![License: MIT](https://img.shields.io/badge/License-MIT-22d3ee?style=flat-square)](../LICENSE)
[![Python](https://img.shields.io/badge/Python-3.9%2B-5b8cff?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![9Router](https://img.shields.io/badge/9Router-glm%20provider-7c5cff?style=flat-square)](https://9router.com)
[![Platform](https://img.shields.io/badge/Cloud-Browser%20%2F%20CDP-0ea5e9?style=flat-square)](#arsitektur)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-38c172?style=flat-square)](../CONTRIBUTING.md)

[English](../README.md) · **Indonesia** · [中文](README.zh.md) · [日本語](README.ja.md) · [Español](README.es.md)

</div>

---

## Konsol Web UI

Seluruh alur berjalan dari **konsol web** yang disuntikkan bridge ke browser — tanpa terminal, tanpa port. Empat halaman: **Dashboard**, **Accounts**, **Capture**, dan **Results**. Lihat [`docs/demo.mp4`](demo.mp4) atau tangkapan layar di README utama.

## Apa ini

Toolkit ringan dengan sedikit dependensi yang mengotomatiskan alur **ZCode**
trial gratis ("Start Plan") dan menyambungkan hasilnya ke **9Router** sebagai
kumpulan provider `glm`. Ini adalah versi otomasi dari aplikasi desktop ZCode
resmi: semua yang dilakukan aplikasi lewat UI-nya, toolkit ini lakukan lewat API
HTTP-nya dan Chromium yang dikendalikan CDP.

> Hasil reverse-engineering dari **ZCode 3.14.4**
> (`ZCode-3.14.4-linux-x64.AppImage` → `resources/app.asar` →
> `out/host/index.js`, `out/renderer/assets/*`).

### Start Plan gratis

| Hak akses | Kuota gratis |
|-----------|--------------|
| **GLM-5.3**       | **3.000.000 token / hari** |
| **GLM-5.3-Flash** | **5.000.000 token / hari** |

`plan_id = "zcode-v3-start-plan"`. Tanpanya, hanya model flash
(`glm-4.5-flash`, `glm-4.7-flash`, `glm-4.6v-flash`) yang gratis dan model
unggulan **GLM-5.3 mengembalikan `1113 Insufficient balance`**.

## Alur

```
token / cookies z.ai ──▶ OAuth consent ──▶ JWT ZCode ──▶ klaim Start Plan ──▶ cetak plan key ──▶ 9Router (glm)
      inject.py            chat.z.ai        zcode.z.ai       billing/claim         zauth.py     connect_9router.py
```

| Tahap | Status |
|-------|--------|
| Inject token/cookies → JWT ZCode | ✅ terverifikasi |
| Klaim Start Plan (gerbang Aliyun Captcha 2.0) | ⚠️ butuh solve interaktif |
| Cetak z.ai coding-plan API key | ✅ terverifikasi |
| Daftarkan key ke pool `glm` 9Router | ✅ terverifikasi lawan 9Router tiruan |

## Dua cara menjalankannya

### 1. Web UI console (disarankan)

Dashboard yang bisa diklik disuntikkan ke cloud browser; tombol-tombolnya
menggerakkan alur lewat sesi CDP yang sama — tanpa port, tanpa tunnel.

```bash
python src/console_bridge.py --cdp "$BU_CDP_WS"
```

Buka live view browser. **ZCode Pipeline Console** memungkinkan kamu:

1. **Inject** — tempel bearer token dan/atau cookies z.ai → *Inject / mint JWT*.
2. **Claim** — *Open z.ai captcha tab*, selesaikan slider; `captchaVerifyParam`
   ditangkap otomatis → *Claim Start Plan*.
3. **Connect** — isi base/password 9Router → *Connect to 9Router*.

### 2. CLI orchestrator

```bash
# inject token, cetak JWT, kirim captcha yang di-solve manusia, sambung 9Router
python src/zcode_claim.py --cdp "$BU_CDP_WS" --email me@x.com --token eyJ... \
    --captcha-param '<param>' --connect --base http://localhost:20128

# batch akun → daftarkan setiap key ke pool glm
python src/zcode_claim.py --cdp "$BU_CDP_WS" --accounts accounts.json \
    --connect --base http://localhost:20128 --out claimed.json

# cek JWT yang sudah kamu punya
python src/zcode_claim.py --jwt-file zjwt.txt --status
```

## Kebutuhan

- Python 3.9+
- `websockets` (untuk console bridge) dan `playwright` (untuk langkah berbasis browser)
- Chromium yang dapat dijangkau lewat CDP (mis. cloud browser Browser Use via `$BU_CDP_WS`)

```bash
pip install websockets playwright
```

## Struktur repositori

```
zcode-claim-9router/
├── assets/            logo + banner (svg + png)
├── docs/              terjemahan README (id, zh, ja, es) + STRUCTURE.md
├── examples/          contoh file akun / config
├── src/               toolkit
│   ├── inject.py          token/cookies → OAuth ZCode → JWT
│   ├── claim.py           captcha Aliyun + billing/claim
│   ├── zauth.py           cetak API key coding-plan z.ai
│   ├── connect_9router.py daftarkan key sebagai koneksi glm
│   ├── zcode_claim.py     orchestrator CLI
│   ├── solverify.py       klien solver Aliyun pihak ketiga
│   ├── console.html       dashboard Web UI
│   └── console_bridge.py  jembatan CDP untuk dashboard
├── CONTRIBUTING.md
├── LICENSE
└── README.md
```

Lihat [`docs/STRUCTURE.md`](STRUCTURE.md) untuk diagram komponen lengkap.

## Dinding captcha (mohon dibaca)

Panggilan `billing/claim` dijaga oleh **Aliyun Captcha 2.0** (scene `11xygtvd`,
prefix `no8xfe`, region `sgp`). Server menuntut `captchaVerifyParam` yang
**signed dan interaktif**, dihasilkan *di dalam halaman z.ai sendiri*:

- Solver pihak ketiga (Solverify) menghasilkan solve asli, tetapi dalam bentuk
  **unsigned** dan tanpa ikatan sesi halaman → claim menolaknya (`3007` / `3001`).
- Drag slider SDK secara skrip **ditolak diam-diam** berapa pun akurasinya
  (deteksi perilaku).
- Karena itu, langkah claim mengharapkan solve interaktif nyata. Web UI console
  ada agar satu langkah itu tanpa repot: solve sekali di tab z.ai dan param
  mengalir otomatis.

## Penggunaan yang bertanggung jawab

- Mengklaim kuota trial lewat otomasi **melanggar Ketentuan Layanan z.ai**.
  Jalankan hanya pada akun milikmu, dan pahami risikonya.
- Start Plan **satu per akun dan sekali pakai**; plan yang sudah terpakai tidak
  bisa diklaim ulang.
- `billing/claim` **membatasi laju** (HTTP 429) — beri jeda antar percobaan.

## Lisensi

[MIT](../LICENSE) © 0xgetz
