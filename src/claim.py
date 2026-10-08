"""Claim the ZCode free "Start Plan" (体验套餐) for a logged-in z.ai account.

Start Plan = free daily quota of the flagship GLM models, as advertised by
ZCode 3.14.4:
    - GLM-5.3        : 3,000,000 tokens / day
    - GLM-5.3-Flash  : 5,000,000 tokens / day
plan_id = "zcode-v3-start-plan"

Endpoints (host https://zcode.z.ai):
    POST /api/v1/zcode-plan/billing/claim
         headers: Authorization: Bearer <zcodeJwtToken>
                  X-Aliyun-Captcha-Verify-Param: <param>
                  X-Aliyun-Captcha-Verify-Region: sgp        (optional)
                  X-ZCode-App-Version: 3.14.4
                  X-Platform: <os>-<arch>
         body   : {"plan_id":"zcode-v3-start-plan"}
    GET  /api/v1/zcode-plan/billing/current      -> active plans
    GET  /api/v1/zcode-plan/billing/balance      -> per-model quota buckets
    GET  /api/v1/client/configs?app_version=&platform= -> captcha config + startPlanPreview

The claim is gated by Aliyun Captcha 2.0 (sceneId 11xygtvd, prefix no8xfe,
region sgp).  We load the official SDK in the same browser page, drive the
INPAINTING slider, and read the produced `captchaVerifyParam`.
"""

import asyncio
import json
import math
import random
import time
import urllib.error
import urllib.request

ZCODE = "https://zcode.z.ai"
PLAN_ID = "zcode-v3-start-plan"
APP_VERSION = "3.14.4"
# scene published in /api/v1/client/configs
CAPTCHA = {"sceneId": "11xygtvd", "prefix": "no8xfe", "region": "sgp"}
COEF = (0.00354991, 0.07703295, -0.01016667)


class ClaimError(Exception):
    pass


def _invert(left_px):
    a, b, c = COEF
    d = b * b - 4 * a * (c - left_px)
    return (-b + math.sqrt(max(d, 0))) / (2 * a)


def _platform():
    import platform
    osname = {"linux": "linux", "darwin": "darwin", "win32": "win32"}.get(
        __import__("sys").platform, "linux")
    arch = {"x86_64": "x64", "amd64": "x64", "aarch64": "arm64",
            "arm64": "arm64"}.get(platform.machine(), "x64")
    return f"{osname}-{arch}"


def _req(method, path, jwt, body=None, extra_headers=None, timeout=30):
    url = f"{ZCODE}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if jwt:
        req.add_header("Authorization", f"Bearer {jwt}")
    for k, v in (extra_headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode())
        except Exception:
            raise ClaimError(f"HTTP {e.code} on {path}")


def client_configs(jwt=None):
    q = f"/api/v1/client/configs?app_version={APP_VERSION}&platform={_platform()}"
    return _req("GET", q, jwt)


def billing_current(jwt):
    return _req("GET",
                f"/api/v1/zcode-plan/billing/current?app_version={APP_VERSION}", jwt)


def billing_balance(jwt, coding_plan_key=None):
    h = {"X-ZCode-App-Version": APP_VERSION, "X-Platform": _platform()}
    if coding_plan_key:
        h["x-coding-plan-api-key"] = coding_plan_key
    return _req("GET",
                f"/api/v1/zcode-plan/billing/balance?app_version={APP_VERSION}",
                jwt, extra_headers=h)


def billing_preview(jwt, plan_id=None):
    q = f"/api/v1/zcode-plan/billing/preview?app_version={APP_VERSION}&platform={_platform()}"
    if plan_id:
        q += f"&plan_id={plan_id}"
    return _req("GET", q, jwt,
                extra_headers={"X-ZCode-App-Version": APP_VERSION,
                               "X-Platform": _platform()})


def claim(jwt, captcha_param, captcha_region=CAPTCHA["region"], plan_id=PLAN_ID):
    """POST the claim. Returns the parsed response dict."""
    headers = {
        "X-Aliyun-Captcha-Verify-Param": captcha_param,
        "X-ZCode-App-Version": APP_VERSION,
        "X-Platform": _platform(),
    }
    if captcha_region:
        headers["X-Aliyun-Captcha-Verify-Region"] = captcha_region
    return _req("POST", f"/api/v1/zcode-plan/billing/claim?app_version={APP_VERSION}",
                jwt, body={"plan_id": plan_id}, extra_headers=headers)


# --------------------------------------------------------------------- browser
async def _slider_box(page):
    return await page.evaluate(
        "()=>{const s=document.getElementById('aliyunCaptcha-sliding-slider');"
        "if(!s)return null;const r=s.getBoundingClientRect();"
        "return {x:r.x+r.width/2,y:r.y+r.height/2,ok:r.width>0&&r.y>0&&r.y<950}}")


async def _drag(page, sx, sy, dist):
    over = dist + random.uniform(6, 10)
    await page.mouse.move(sx, sy)
    await page.mouse.down()
    for i in range(1, 26):
        t = i / 25
        e = 1 - (1 - t) ** 3
        await page.mouse.move(sx + over * e, sy + math.sin(t * 5) * 1.2)
        await asyncio.sleep(0.007)
    for j in range(1, 7):
        t = j / 6
        cur = over + (dist - over) * t
        await page.mouse.move(sx + cur, sy + random.uniform(-0.6, 0.6))
        await asyncio.sleep(0.012)
    await page.mouse.move(sx + dist, sy)
    await asyncio.sleep(0.12)
    await page.mouse.up()


async def _reopen(page):
    await page.evaluate(
        "()=>{const c=document.getElementById('aliyunCaptcha-btn-close');"
        "if(c&&c.offsetParent)c.click()}")
    await asyncio.sleep(0.25)
    await page.evaluate(
        "()=>{const el=document.getElementById('aliyunCaptcha-captcha-left')"
        "||document.querySelector('.aliyunCaptcha-captcha-left');if(el)el.click()}")
    await asyncio.sleep(1.9)


async def _passed(page):
    t = (await page.evaluate("()=>document.body.innerText")).lower()
    return "verification passed" in t


INJECT_SDK_JS = """(scene)=>{
  window.__capParam=null; window.__capErr=null;
  let el=document.getElementById('__caphost');
  if(!el){el=document.createElement('div');el.id='__caphost';
    el.style.cssText='position:fixed;bottom:10px;left:10px;z-index:2147483647;background:#fff;padding:6px';
    document.body.appendChild(el);
    el.innerHTML='<div id="__capbox"></div><button id="__capbtn">verify</button>';}
  window.initAliyunCaptcha({
    SceneId:scene.sceneId, mode:'popup', element:'#__capbox', button:'#__capbtn',
    region:scene.region, prefix:scene.prefix, language:'en', captchaLogoImg:'',
    getInstance:(i)=>{window.__capInst=i;},
    success:(p)=>{window.__capParam=p;},
    fail:(e)=>{window.__capErr=JSON.stringify(e);}
  });
  return 'ok';
}"""


async def solve_captcha_param(page, scene=CAPTCHA, rounds=10, log=print):
    """Load the Aliyun SDK in the current page, drive the slider until it
    passes, and return the captchaVerifyParam."""
    # make sure the SDK is present (it is cached by the app after first load)
    has = await page.evaluate("()=>typeof window.initAliyunCaptcha")
    if has != "function":
        await page.evaluate(
            """()=>new Promise((res)=>{
                 const s=document.createElement('script');
                 s.src='https://o.alicdn.com/captcha-frontend/aliyunCaptcha/AliyunCaptcha.js';
                 s.onload=res; s.onerror=res; document.head.appendChild(s);})""")
        await page.wait_for_timeout(1500)
    await page.evaluate(INJECT_SDK_JS, scene)
    await page.wait_for_timeout(800)
    # click the button to reveal the slider
    await page.evaluate(
        "()=>{const b=document.getElementById('__capbtn');if(b)b.click();}")
    await page.wait_for_timeout(2200)

    for rnd in range(rounds):
        for target in range(4, 300, 4):
            b = await _slider_box(page)
            if not b or not b.get("ok"):
                await _reopen(page)
                b = await _slider_box(page)
                if not b or not b.get("ok"):
                    continue
            await _drag(page, b["x"], b["y"], _invert(target))
            await asyncio.sleep(1.25)
            if await _passed(page):
                param = await page.evaluate("()=>window.__capParam")
                log(f"  captcha solved (offset={target})")
                if param:
                    return param
                # some SDK builds only expose the string via the instance
                param = await page.evaluate(
                    "()=>{try{return window.__capInst && window.__capInst.getVerifyParam"
                    " && window.__capInst.getVerifyParam();}catch(e){return null}}")
                if param:
                    return param
                raise ClaimError("captcha passed but no verify param exposed")
            await _reopen(page)
        log(f"  captcha round {rnd} no hit")
    return None


TRACELESS_SETUP = """(scene)=>{
  window.__capParam=null; window.__capErr=null;
  ['zcode-aliyun-captcha-container'].forEach(id=>{const e=document.getElementById(id);if(e)e.remove();});
  document.querySelectorAll('[id^="aliyunCaptcha"]').forEach(e=>{try{e.remove()}catch(_){}});
  const c=document.createElement('div'); c.id='zcode-aliyun-captcha-container';
  c.style.cssText='position:fixed;top:40px;left:50%;transform:translateX(-50%);'+
    'width:600px;min-height:420px;z-index:2147483647;background:#fff';
  c.innerHTML='<div id="zcode-aliyun-captcha-element" style="width:100%">'+
              '</div><button id="zcode-aliyun-captcha-button" '+
              'style="display:block;margin:8px auto">go</button>';
  document.body.appendChild(c);
  window.AliyunCaptchaConfig={region:scene.region, prefix:scene.prefix};
  window.initAliyunCaptcha({SceneId:scene.sceneId, mode:'popup',
    element:'#zcode-aliyun-captcha-element', button:'#zcode-aliyun-captcha-button',
    language:'en', captchaLogoImg:'',
    getInstance:(i)=>{window.__capInst=i;}, success:(p)=>{window.__capParam=p;},
    fail:(e)=>{window.__capErr=JSON.stringify(e);}});
  return 'ok';
}"""

SDK_LOAD_JS = """()=>new Promise((res)=>{const s=document.createElement('script');
  s.src='https://o.alicdn.com/captcha-frontend/aliyunCaptcha/AliyunCaptcha.js';
  s.onload=res; s.onerror=res; document.head.appendChild(s);})"""


async def traceless_param(page, scene=CAPTCHA, tries=20, log=print):
    """Load the Aliyun SDK in chat.z.ai and call startTracelessVerification()
    until it yields a captchaVerifyParam. Returns the param or None.

    Traceless verification needs no user gesture but the claim endpoint may
    still demand an interactive solve; callers should verify by submitting."""
    if await page.evaluate("()=>typeof window.initAliyunCaptcha") != "function":
        await page.evaluate(SDK_LOAD_JS)
        await page.wait_for_timeout(1500)
    await page.evaluate(TRACELESS_SETUP, scene)
    for _ in range(tries):
        st = await page.evaluate(
            "()=>({inst:!!window.__capInst,param:window.__capParam,"
            "err:window.__capErr})")
        if st.get("param"):
            log("  traceless captcha param acquired")
            return st["param"]
        if st.get("err"):
            log(f"  traceless captcha error: {st['err']}")
            return None
        if st.get("inst"):
            await page.evaluate(
                "()=>{try{window.__capInst.startTracelessVerification()}"
                "catch(e){window.__capErr=String(e)}}")
        await page.wait_for_timeout(1300)
    return None


async def claim_via_browser(cdp_ws, jwt, log=print):
    """Open chat.z.ai, obtain a captcha verify param (traceless first, then
    interactive sweep), and return it (or None)."""
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(cdp_ws)
        ctx = browser.contexts[0] if browser.contexts else await browser.new_context()
        page = await ctx.new_page()
        await page.goto("https://chat.z.ai/", wait_until="domcontentloaded",
                        timeout=45000)
        await page.wait_for_timeout(2000)
        await page.evaluate(
            "()=>{document.querySelectorAll('[class*=close],[aria-label*=close]')"
            ".forEach(e=>{try{e.click()}catch(_){}})}")
        param = await traceless_param(page, log=log)
        if not param:
            log("  traceless failed, trying interactive solve")
            param = await solve_captcha_param(page, log=log)
        await page.close()
        return param


def claim_with_browser(cdp_ws, jwt, log=print):
    param = asyncio.run(claim_via_browser(cdp_ws, jwt, log))
    if not param:
        raise ClaimError("could not obtain captcha verify param")
    return claim(jwt, param)
