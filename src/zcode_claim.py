#!/usr/bin/env python3
"""ZCode free-Start-Plan claimer + 9Router connector.

Takes existing z.ai sessions (bearer token and/or cookies) or email+password,
injects them into the ZCode desktop OAuth flow, claims the free **Start Plan**
(GLM-5.3 3M tok/day + GLM-5.3-Flash 5M tok/day), mints the z.ai coding-plan API
key, and registers every account into 9Router's `glm` provider.

Examples
--------
  # local laptop: auto-launch Chrome (a real window). No cloud needed.
  python zcode_claim.py --token eyJ... --email me@x.com

  # headless VPS: auto-launch a headless Chromium
  python zcode_claim.py --headless --token eyJ... --email me@x.com

  # attach to a Chrome you started yourself
  #   chrome --remote-debugging-port=9222
  python zcode_claim.py --connect-browser 127.0.0.1:9222 --token eyJ... --email me@x.com

  # (optional) use a Browser Use cloud browser instead
  python zcode_claim.py --cdp "$BU_CDP_WS" --token eyJ... --email me@x.com

  # one account from a cookies export (JSON list, dict, or 'a=b; c=d')
  python zcode_claim.py --cookies cookies.json --email me@x.com

  # batch file accounts.json: {"accounts":[{"email","password"|"token"|"cookies"}]}
  python zcode_claim.py --accounts accounts.json --connect \\
      --base http://localhost:20128 --password 123456 --out claimed.json

  # check an already-claimed account
  python zcode_claim.py --jwt-file zjwt.txt --status

Notes
-----
* If --email/--password are given the tool logs in itself; otherwise it seeds
  the browser with the provided token/cookies.
* The claim captcha is Aliyun Captcha 2.0 (inpainting). Solving is probabilistic
  per position, so a full run can take a few minutes per account.
"""

import argparse
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import claim as C
import inject as I
import browser as B


def _resolve_browser(args, log=print):
    """Find a usable CDP endpoint: --cdp URL, --connect host:port, or auto-launch
    a local Chrome/Chromium (headless on a VPS). Falls back to $BU_CDP_WS."""
    return B.resolve_cdp(
        cdp=args.cdp,
        connect=getattr(args, "connect_browser", None),
        port=getattr(args, "cdp_port", None) or B.DEFAULT_PORT,
        launch=not getattr(args, "no_launch", False),
        headless=True if getattr(args, "headless", False) else None,
        user_data_dir=getattr(args, "user_data_dir", None),
        profile=getattr(args, "profile", None),
        log=log,
    )


def _load_accounts(args):
    if args.accounts:
        with open(args.accounts) as f:
            data = json.load(f)
        return data.get("accounts", data) if isinstance(data, dict) else data
    acct = {"email": args.email}
    if args.token:
        acct["token"] = args.token
    if args.cookies:
        acct["cookies"] = _read_cookies(args.cookies)
    if args.password:
        acct["password"] = args.password
    return [acct]


def _read_cookies(value):
    if os.path.exists(value):
        with open(value) as f:
            txt = f.read().strip()
        try:
            return json.loads(txt)
        except Exception:
            return txt
    return value


def _mint_plan_key(zai_access_token):
    """Reuse zai-bulk's mint routine when available; else inline minimal."""
    here = os.path.dirname(os.path.abspath(__file__))
    zb = os.path.join(here, "..", "zai-bulk")
    if os.path.isdir(zb):
        sys.path.insert(0, os.path.abspath(zb))
        try:
            import zauth
            return zauth.mint_plan_key(zai_access_token)
        except Exception as e:
            print(f"  mint via zauth failed: {e}")
    return None


async def _login_in_browser(cdp_ws, email, password, log=print):
    """Log in to chat.z.ai (email+password) and solve the login captcha."""
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(cdp_ws)
        ctx = browser.contexts[0] if browser.contexts else await browser.new_context()
        page = await ctx.new_page()
        await page.goto("https://chat.z.ai/auth", wait_until="domcontentloaded",
                        timeout=45000)
        await page.wait_for_timeout(2500)
        await page.evaluate("()=>{const b=[...document.querySelectorAll('button')]"
                            ".find(x=>/continue\\s*with\\s*email/i.test(x.innerText));if(b)b.click()}")
        await page.wait_for_timeout(1800)
        await page.evaluate(
            "()=>{function sn(el,v){const p=Object.getOwnPropertyDescriptor("
            "HTMLInputElement.prototype,'value').set;p.call(el,v);"
            "el.dispatchEvent(new Event('input',{bubbles:true}));"
            "el.dispatchEvent(new Event('change',{bubbles:true}));}"
            "sn(document.querySelector('input[type=email]'),%s);"
            "sn(document.querySelector('input[type=password]'),%s);}"
            % (json.dumps(email), json.dumps(password)))
        await page.wait_for_timeout(400)
        await page.evaluate("()=>{const b=[...document.querySelectorAll('button')]"
                            ".find(x=>/^sign in$/i.test(x.innerText.trim()));if(b)b.click()}")
        await page.wait_for_timeout(2800)
        await page.evaluate(
            "()=>{const el=document.getElementById('aliyunCaptcha-captcha-text')"
            "||document.querySelector('.aliyunCaptcha-captcha-text');"
            "if(el){const box=el.closest('[id*=\"aliyunCaptcha\"]')||el;box.click();}}")
        await page.wait_for_timeout(2000)
        ok = await C.solve_captcha_param(page, log=log)
        if not ok:
            await page.close()
            raise I.InjectError("login captcha not solved")
        await page.evaluate("()=>{const b=[...document.querySelectorAll('button')]"
                            ".find(x=>/^sign in$/i.test(x.innerText.trim()));if(b)b.click()}")
        await page.wait_for_timeout(6500)
        log(f"  logged in, at {page.url[:70]}")
        # keep the cookies for reuse; then close and let inject.py drive OAuth
        cookies = await ctx.cookies("https://chat.z.ai")
        await page.close()
        return cookies


def _solve_with_solverify(args, log=print):
    """Solve the claim captcha via Solverify (needs --solverify-key + --proxy)."""
    import solverify
    key = args.solverify_key or os.environ.get("SOLVERIFY_API_KEY")
    if not key:
        raise SystemExit("--solverify needs --solverify-key or SOLVERIFY_API_KEY")
    proxies = [p.strip() for p in (args.proxy or "").split(",") if p.strip()]
    if not proxies:
        raise SystemExit("--solverify needs --proxy host:port[,host:port...]")
    log(f"  solverify: solving scene {C.CAPTCHA['sceneId']} via {proxies}")
    raw, dec, used = solverify.solve_aliyun_retry(
        key, "https://zcode.z.ai/coding-plan?embedded=app",
        C.CAPTCHA["sceneId"], C.CAPTCHA["prefix"], proxies,
        region=C.CAPTCHA["region"], log=log)
    log(f"  solverify solved via {used}")
    return raw


def _process_account(args, acct, log=print):
    email = acct.get("email", "?")
    log(f"\n=== {email} ===")
    cdp = _resolve_browser(args, log)
    cookies = acct.get("cookies")
    token = acct.get("token")
    # If no direct token, log in when a password is available.
    if not token and not cookies and acct.get("password"):
        cookies = asyncio.run(_login_in_browser(cdp, email, acct["password"], log))
        acct["_logged_in"] = True

    jwt_set = asyncio.run(
        I.inject_and_mint(cdp, token=token, cookies=cookies, log=log))
    jwt = jwt_set.get("zcodeJwtToken")
    log(f"  ZCode JWT: {(jwt or '')[:22]}...")
    if not jwt:
        raise I.InjectError("no ZCode JWT minted")

    cur = C.billing_current(jwt)
    plans = (cur.get("data") or {}).get("plans") or []
    log(f"  current plans: {[p.get('plan_id') or p.get('planId') for p in plans]}")

    result = {"email": email, "zcodeJwtToken": jwt,
              "zaiAccessToken": jwt_set.get("zaiAccessToken"),
              "before": plans}

    if not args.no_claim and not plans:
        log("  claiming Start Plan (solving captcha)...")
        param = acct.get("captchaParam") or args.captcha_param
        if not param and args.solverify:
            param = _solve_with_solverify(args, log)
        if not param:
            param = asyncio.run(C.claim_via_browser(cdp, jwt, log))
        if not param:
            log("  CLAIM skipped: no captcha param")
        else:
            resp = C.claim(jwt, param)
            result["claim"] = resp
            log(f"  claim response: {json.dumps(resp)[:300]}")
            cur2 = C.billing_current(jwt)
            result["after"] = (cur2.get("data") or {}).get("plans") or []
            log(f"  plans after: {[p.get('plan_id') or p.get('planId') for p in result['after']]}")

    # mint the z.ai coding-plan api key for 9Router
    if jwt_set.get("zaiAccessToken"):
        mk = _mint_plan_key(jwt_set["zaiAccessToken"])
        if mk:
            result["planApiKey"] = mk.get("planApiKey")
            result["org"] = mk.get("org")
            log(f"  plan key: {(mk.get('planApiKey') or '')[:22]}...")
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cdp", default=os.environ.get("BU_CDP_WS"),
                    help="CDP websocket URL (ws://...). Optional — omit to auto-launch a local browser.")
    ap.add_argument("--connect-browser", dest="connect_browser",
                    help="connect to an already-running browser at host:port (default port 9222)")
    ap.add_argument("--cdp-port", dest="cdp_port", type=int,
                    help="local remote-debugging port to find/launch (default 9222)")
    ap.add_argument("--headless", action="store_true",
                    help="force a headless browser (auto on a VPS without a display)")
    ap.add_argument("--no-launch", dest="no_launch", action="store_true",
                    help="never auto-launch a browser; require --cdp/--connect")
    ap.add_argument("--profile", help="named local profile dir (persists logins)")
    ap.add_argument("--user-data-dir", dest="user_data_dir",
                    help="explicit Chrome user-data-dir to use/launch")
    ap.add_argument("--email")
    ap.add_argument("--password")
    ap.add_argument("--token", help="z.ai bearer token")
    ap.add_argument("--cookies", help="cookies file or 'a=b; c=d' string")
    ap.add_argument("--accounts", help="JSON file with {'accounts':[...]}")
    ap.add_argument("--jwt-file", help="existing zcode JWT (for --status)")
    ap.add_argument("--status", action="store_true", help="only print plan status")
    ap.add_argument("--no-claim", action="store_true", help="skip the claim")
    ap.add_argument("--captcha-param", help="pre-solved Aliyun captchaVerifyParam")
    ap.add_argument("--solverify", action="store_true",
                    help="solve the claim captcha via Solverify")
    ap.add_argument("--solverify-key", help="Solverify clientKey (or SOLVERIFY_API_KEY)")
    ap.add_argument("--proxy", help="Solverify HTTP proxy host:port[,host:port...]")
    ap.add_argument("--connect", action="store_true", help="register into 9Router")
    ap.add_argument("--base", default="http://localhost:20128")
    ap.add_argument("--9router-password", dest="router_password", default="123456")
    ap.add_argument("--out", default="claimed.json")
    args = ap.parse_args()

    if args.status:
        jwt = open(args.jwt_file).read().strip()
        print(json.dumps({"current": C.billing_current(jwt),
                          "balance": C.billing_balance(jwt)}, indent=1)[:1500])
        return

    accounts = _load_accounts(args)
    results = []
    for acct in accounts:
        try:
            results.append(_process_account(args, acct))
        except Exception as e:
            print(f"  ERROR {acct.get('email')}: {e}")
            results.append({"email": acct.get("email"), "error": str(e)})

    with open(args.out, "w") as f:
        json.dump({"accounts": results}, f, indent=1)
    print(f"\nwrote {args.out} ({len(results)} account(s))")

    if args.connect:
        import connect_9router
        connect_9router.connect(args.base, args.router_password, results)


if __name__ == "__main__":
    main()
