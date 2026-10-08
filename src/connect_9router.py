"""Register ZCode Start-Plan accounts into 9Router as provider `glm` connections.

9Router's `glm` provider ("Zai GLM Coding", category oauth) exposes
authModes ["oauth","apikey"].  A z.ai coding-plan API key (which is what the
Start Plan uses) works directly via apikey mode, so NO adapter is needed: each
account's key becomes one glm connection and 9Router load-balances the pool.

Transports used by ZCode for Z.ai:
  * openai  : https://api.z.ai/api/paas/v4           (models GLM-4.5-Flash, ...)
  * anthropic: https://api.z.ai/api/anthropic         (GLM-5.3 / GLM-5.3-Flash)

Usage:
  python connect_9router.py --base http://localhost:20128 --password 123456 \
      accounts.json
"""

import argparse
import json
import urllib.error
import urllib.request

UA = "zcode-claim-9router-connector/1.0"
GLM_PROVIDER = "glm"
DEFAULT_MODEL = "GLM-5.3-Flash"


def _req(base, path, method="GET", body=None, cookie=None, timeout=20):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(f"{base}{path}", data=data, method=method)
    r.add_header("Content-Type", "application/json")
    r.add_header("User-Agent", UA)
    if cookie:
        r.add_header("Cookie", cookie)
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            return resp.status, resp.read().decode(), resp.headers
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(), e.headers
    except Exception as e:
        return 0, str(e), None


def login(base, password):
    status, text, headers = _req(base, "/api/auth/login", "POST",
                                 {"password": password or "123456"})
    cookie = ""
    if headers:
        raw = headers.get_all("Set-Cookie") or []
        cookie = "; ".join(c.split(";")[0] for c in raw)
    return status, cookie, text[:200]


def list_connections(base, cookie):
    _, text, _ = _req(base, "/api/providers", cookie=cookie)
    try:
        return json.loads(text).get("connections", [])
    except Exception:
        return []


def add_connection(base, cookie, *, api_key, name):
    return _req(base, "/api/providers", "POST", {
        "provider": GLM_PROVIDER,
        "apiKey": api_key,
        "name": name,
        "priority": 1,
        "defaultModel": DEFAULT_MODEL,
    }, cookie=cookie)


def connect(base, password, accounts, log=print):
    status, cookie, text = login(base, password)
    log(f"9Router login: HTTP {status} {'(ok)' if status == 200 else text}")
    existing = {c.get("name") for c in list_connections(base, cookie)}
    log(f"existing connections: {len(existing)}")
    added = 0
    for i, acct in enumerate(accounts, 1):
        key = acct.get("planApiKey") or acct.get("apiKey")
        email = acct.get("email", f"account-{i}")
        if not key:
            log(f"  [{i}] {email}: no api key, skipped")
            continue
        name = f"ZCode GLM - {email}"
        if name in existing:
            log(f"  [{i}] {email}: already registered")
            continue
        st, tx, _ = add_connection(base, cookie, api_key=key, name=name)
        if st in (200, 201):
            log(f"  [{i}] {email}: registered")
            added += 1
        else:
            log(f"  [{i}] {email}: FAILED HTTP {st} {tx[:150]}")
    log(f"done: {added} new connection(s), {len(accounts)} account(s) offered")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("accounts", nargs="?", default="accounts.json")
    ap.add_argument("--base", default="http://localhost:20128")
    ap.add_argument("--password", default="123456")
    args = ap.parse_args()
    with open(args.accounts) as f:
        accounts = json.load(f)
    if isinstance(accounts, dict):
        accounts = accounts.get("accounts", [])
    connect(args.base, args.password, accounts)


if __name__ == "__main__":
    main()
