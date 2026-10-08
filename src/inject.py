"""Inject an existing z.ai session (token + cookies) into the ZCode desktop OAuth
flow and mint a ZCode JWT (`zcodejwttoken`).

Reverse-engineered from ZCode 3.14.4 (`out/host/index.js`):

    authorize : https://chat.z.ai/api/oauth/authorize
                ?client_id=client_P8X5CMWmlaRO9gyO-KSqtg
                &redirect_uri=zcode://oauth/callback&response_type=code&state=<s>
    consent   : POST https://chat.z.ai/api/oauth/authorize  (form urlencoded)
                {client_id, redirect_uri, response_type, state, action:"approve"}
                -> {redirect_url: "zcode://oauth/callback?code=<code>&state=.."}
    exchange  : POST https://zcode.z.ai/api/v1/oauth/token  (json)
                {provider:"zai", code, redirect_uri, state}
                -> data:{ token:<zcodeJwt>, zai:{access_token}, user, expires_in }

The consent POST needs a logged-in chat.z.ai cookie session.  We support two
modes:

  * token mode  - the caller supplies a bearer token; the browser is navigated
                  with the token already set as the `token` cookie.
  * cookie mode - the caller supplies raw cookies from a logged-in browser
                  export; we set them on chat.z.ai before driving consent.

Everything runs inside a Chromium driven over CDP so it works headless on a
server as well as on the user's own machine.
"""

import asyncio
import json

CLIENT_ID = "client_P8X5CMWmlaRO9gyO-KSqtg"
REDIRECT_URI = "zcode://oauth/callback"
AUTHORIZE = "https://chat.z.ai/api/oauth/authorize"
TOKEN_URL = "https://zcode.z.ai/api/v1/oauth/token"


class InjectError(Exception):
    pass


async def _apply_cookies(ctx, cookies):
    """cookies: list of {name,value,domain,path...} or {name:value} or a raw
    'a=b; c=d' Cookie header string. All are normalized onto .z.ai."""
    norm = []
    if isinstance(cookies, str):
        for part in cookies.split(";"):
            if "=" in part:
                k, v = part.strip().split("=", 1)
                norm.append({"name": k, "value": v, "domain": ".z.ai", "path": "/"})
    elif isinstance(cookies, dict):
        for k, v in cookies.items():
            norm.append({"name": k, "value": str(v), "domain": ".z.ai", "path": "/"})
    elif isinstance(cookies, list):
        for c in cookies:
            if isinstance(c, str):
                continue
            dom = c.get("domain") or ".z.ai"
            norm.append({
                "name": c["name"], "value": c["value"], "path": c.get("path", "/"),
                "domain": dom,
                **({"secure": c["secure"]} if "secure" in c else {}),
                **({"httpOnly": c["httpOnly"]} if "httpOnly" in c else {}),
            })
    # A bare `token` cookie is the Open WebUI bearer; make sure it lands on
    # both .z.ai and chat.z.ai.
    if norm:
        await ctx.add_cookies([
            {**c, "domain": "chat.z.ai"} for c in norm if c["name"] == "token"
        ])
        await ctx.add_cookies(norm)


async def mint_jwt(ctx, state, log=print):
    """Drive the OAuth authorize page (already logged in) -> code -> JWT."""
    page = await ctx.new_page()
    await page.goto(
        f"{AUTHORIZE}?client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}"
        f"&response_type=code&state={state}",
        wait_until="domcontentloaded", timeout=45000)
    await page.wait_for_timeout(3500)
    url = page.url
    log(f"  authorize landed on {url[:80]}")

    code = None
    if "oauth/authorize" in url:
        # in-page consent POST (keeps the cookie session)
        res = await page.evaluate(
            """async (args)=>{
                const body=new URLSearchParams({
                  client_id:args.clientId, redirect_uri:args.redirectUri,
                  response_type:'code', state:args.state, action:'approve'});
                const r=await fetch('/api/oauth/authorize',{method:'POST',
                  headers:{'Content-Type':'application/x-www-form-urlencoded'},
                  credentials:'include', body});
                return await r.text();
            }""", {"clientId": CLIENT_ID, "redirectUri": REDIRECT_URI, "state": state})
        log(f"  consent resp: {res[:120]}")
        try:
            code = json.loads(res)["redirect_url"].split("code=")[1].split("&")[0]
        except Exception as e:
            await page.close()
            raise InjectError(f"could not read oauth code from consent: {e}")
    else:
        # already redirected (custom scheme dropped) - look in the URL
        if "code=" in url:
            code = url.split("code=")[1].split("&")[0]
    await page.close()

    if not code:
        raise InjectError("no oauth code obtained (is the account logged in?)")

    tok = await asyncio.get_event_loop().run_in_executor(
        None, _exchange, code, state)
    return tok


def _exchange(code, state):
    import urllib.request
    req = urllib.request.Request(
        TOKEN_URL,
        data=json.dumps({"provider": "zai", "code": code,
                         "redirect_uri": REDIRECT_URI, "state": state}).encode(),
        method="POST", headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read().decode())
    if data.get("code") not in (0, None):
        raise InjectError(f"token exchange failed: {data.get('msg') or data}")
    d = data.get("data") or {}
    return {
        "zcodeJwtToken": d.get("token"),
        "zaiAccessToken": (d.get("zai") or {}).get("access_token"),
        "user": d.get("user"),
        "expiresIn": d.get("expires_in"),
    }


async def inject_and_mint(cdp_ws, token=None, cookies=None, state=None, log=print):
    """High level: attach, login, mint JWT. Returns the token set dict."""
    import secrets
    from playwright.async_api import async_playwright

    state = state or secrets.token_hex(16)
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(cdp_ws)
        ctx = browser.contexts[0] if browser.contexts else await browser.new_context()
        # seed the session
        if cookies:
            await _apply_cookies(ctx, cookies)
        if token:
            await ctx.add_cookies([
                {"name": "token", "value": token, "domain": domain, "path": "/"}
                for domain in (".z.ai", "chat.z.ai")
            ])
        return await mint_jwt(ctx, state, log)
