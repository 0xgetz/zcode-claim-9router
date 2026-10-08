<div align="center">

<img src="../assets/banner.png" alt="ZCode Claim — 9Router Pipeline" width="820">

# ZCode Claim · 9Router Pipeline

**Toma una cuenta z.ai existente → acuña un JWT de ZCode → reclama el Start Plan gratis → conecta GLM a 9Router.**

[![License: MIT](https://img.shields.io/badge/License-MIT-22d3ee?style=flat-square)](../LICENSE)
[![Python](https://img.shields.io/badge/Python-3.9%2B-5b8cff?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![9Router](https://img.shields.io/badge/9Router-glm%20provider-7c5cff?style=flat-square)](https://9router.com)
[![Platform](https://img.shields.io/badge/Cloud-Browser%20%2F%20CDP-0ea5e9?style=flat-square)](#arquitectura)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-38c172?style=flat-square)](../CONTRIBUTING.md)

[English](../README.md) · [Indonesia](README.id.md) · [中文](README.zh.md) · [日本語](README.ja.md) · **Español**

</div>

---

## Qué es esto

Un toolkit ligero, con pocas dependencias, que automatiza el flujo de prueba
gratuita de **ZCode** ("Start Plan") y conecta el resultado a **9Router** como un
pool de proveedores `glm`. Es la contraparte automatizada de la app de escritorio
oficial de ZCode: todo lo que la app hace por su UI, esto lo hace por sus APIs
HTTP y un Chromium controlado por CDP.

> Ingeniería inversa de **ZCode 3.14.4**
> (`ZCode-3.14.4-linux-x64.AppImage` → `resources/app.asar` →
> `out/host/index.js`, `out/renderer/assets/*`).

### El Start Plan gratuito

| Derecho | Cuota gratuita |
|---------|----------------|
| **GLM-5.3**       | **3.000.000 tokens / día** |
| **GLM-5.3-Flash** | **5.000.000 tokens / día** |

`plan_id = "zcode-v3-start-plan"`. Sin él, solo los modelos flash
(`glm-4.5-flash`, `glm-4.7-flash`, `glm-4.6v-flash`) son gratis y el insignia
**GLM-5.3 devuelve `1113 Insufficient balance`**.

## Pipeline

```
token / cookies de z.ai ──▶ consentimiento OAuth ──▶ JWT de ZCode ──▶ reclamar Start Plan ──▶ acuñar plan key ──▶ 9Router (glm)
       inject.py                 chat.z.ai            zcode.z.ai           billing/claim            zauth.py      connect_9router.py
```

| Etapa | Estado |
|-------|--------|
| Inyectar token/cookies → JWT de ZCode | ✅ verificado |
| Reclamar Start Plan (puerta Aliyun Captcha 2.0) | ⚠️ requiere resolución interactiva |
| Acuñar la API key coding-plan de z.ai | ✅ verificado |
| Registrar la key en el pool `glm` de 9Router | ✅ verificado contra un 9Router simulado |

## Dos formas de ejecutarlo

### 1. Consola Web UI (recomendada)

Se inyecta un panel clicable en un navegador en la nube; sus botones mueven el
pipeline por la misma sesión CDP — sin puertos ni túneles.

```bash
python src/console_bridge.py --cdp "$BU_CDP_WS"
```

Abre la vista en vivo del navegador. La **ZCode Pipeline Console** te permite:

1. **Inject** — pega un bearer token y/o cookies de z.ai → *Inject / mint JWT*.
2. **Claim** — *Open z.ai captcha tab*, resuelve el deslizador; el
   `captchaVerifyParam` se captura automáticamente → *Claim Start Plan*.
3. **Connect** — define base/password de 9Router → *Connect to 9Router*.

### 2. Orquestador CLI

```bash
# inyecta un token, acuña el JWT, envía el captcha resuelto a mano, conecta 9Router
python src/zcode_claim.py --cdp "$BU_CDP_WS" --email me@x.com --token eyJ... \
    --captcha-param '<param>' --connect --base http://localhost:20128

# lote de cuentas → registra cada key en el pool glm
python src/zcode_claim.py --cdp "$BU_CDP_WS" --accounts accounts.json \
    --connect --base http://localhost:20128 --out claimed.json

# comprueba un JWT que ya tengas
python src/zcode_claim.py --jwt-file zjwt.txt --status
```

## Requisitos

- Python 3.9+
- `websockets` (para el puente de consola) y `playwright` (para los pasos con navegador)
- Un Chromium accesible por CDP (p. ej. un navegador en la nube de Browser Use vía `$BU_CDP_WS`)

```bash
pip install websockets playwright
```

## Estructura del repositorio

```
zcode-claim-9router/
├── assets/            logo + banner (svg + png)
├── docs/              traducciones del README (id, zh, ja, es) + STRUCTURE.md
├── examples/          archivos de cuenta / config de ejemplo
├── src/               el toolkit
│   ├── inject.py          token/cookies → OAuth de ZCode → JWT
│   ├── claim.py           captcha de Aliyun + billing/claim
│   ├── zauth.py           acuñación de la API key coding-plan de z.ai
│   ├── connect_9router.py registra una key como conexión glm
│   ├── zcode_claim.py     orquestador CLI
│   ├── solverify.py       cliente del solver Aliyun de terceros
│   ├── console.html       panel Web UI
│   └── console_bridge.py  puente CDP del panel
├── CONTRIBUTING.md
├── LICENSE
└── README.md
```

Consulta [`docs/STRUCTURE.md`](STRUCTURE.md) para el diagrama de componentes completo.

## El muro del captcha (léelo)

La llamada `billing/claim` está protegida por **Aliyun Captcha 2.0** (scene
`11xygtvd`, prefix `no8xfe`, region `sgp`). El servidor exige un
`captchaVerifyParam` **firmado e interactivo** generado *dentro de la propia
página de z.ai*:

- Un solver de terceros (Solverify) devuelve una solución real, pero en forma
  **sin firmar** y sin el vínculo de sesión de la página → el claim lo rechaza
  (`3007` / `3001`).
- Los arrastres por script del deslizador del SDK se **rechazan en silencio** sea
  cual sea su precisión (detección de comportamiento).
- Por eso el paso de claim espera una resolución interactiva real. La consola Web
  UI existe para hacer ese único paso indoloro: resuelve una vez en la pestaña de
  z.ai y el param fluye solo.

## Uso responsable

- Reclamar cuota de prueba mediante automatización **viola los Términos de
  Servicio de z.ai**. Úsalo solo con cuentas propias y conoce el riesgo.
- El Start Plan es **uno por cuenta y de un solo uso**; un plan usado no se puede
  reclamar de nuevo.
- `billing/claim` **limita la tasa** (HTTP 429) — espacia los intentos.

## Licencia

[MIT](../LICENSE) © 0xgetz
