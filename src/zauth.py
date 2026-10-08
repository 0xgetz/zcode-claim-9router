"""Z.AI ZCode OAuth -> coding-plan API key mint (pure HTTP, no browser).

Reverse-engineered from the official ZCode CLI and 9Router's glm provider
(src/lib/oauth/providers/glm.js). Flow:

  1. POST {cliInitUrl}  Bearer <pollToken>  {"provider":"zai"}
       -> { data:{ flow_id, authorize_url, poll_token, poll_interval_sec, expires_at } }
  2. User opens authorize_url and approves  (browser, see oauth_approve_* helpers)
  3. GET  {cliPollUrl}/<flow_id>  Bearer <pollToken>
       -> { data:{ status:"pending" } } until { status:"ready", token, user, zai:{access_token} }
  4. POST https://api.z.ai/api/auth/z/login  {"token": <zai access_token>}
       -> { data:{ access_token } }  (platform business JWT)
  5. business JWT -> getCustomerInfo -> api_keys list/create("zcode-api-key")
       -> copy -> secretKey; final credential = "<apiKey>.<secretKey>"

Only stdlib is used so this module imports anywhere.
"""

import json
import secrets
import time
import urllib.error
import urllib.request

CLI_INIT_URL = "https://zcode.z.ai/api/v1/oauth/cli/init"
CLI_POLL_URL = "https://zcode.z.ai/api/v1/oauth/cli/poll"
BUSINESS_LOGIN_URL = "https://api.z.ai/api/auth/z/login"
API_BASE = "https://api.z.ai"
PLAN_API_KEY_NAME = "zcode-api-key"


class ZaiError(Exception):
    pass


def _http(url, method="GET", body=None, headers=None, timeout=30):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        raise ZaiError(f"HTTP {e.code} on {url}: {e.read().decode()[:200]}") from e


def _ok(payload):
    return payload.get("code") in (0, 200, None) and payload.get("success") is not False


# ---------------------------------------------------------------- step 1 + 3
def init_flow(poll_token=None, provider="zai"):
    """Start an OAuth flow. Returns dict with poll_token, flow_id, authorize_url."""
    poll_token = poll_token or secrets.token_hex(32)
    payload = _http(CLI_INIT_URL, "POST", {"provider": provider},
                    {"Authorization": f"Bearer {poll_token}"})
    if not _ok(payload) or not payload.get("data"):
        raise ZaiError(payload.get("msg") or "ZCode OAuth init returned no data")
    d = payload["data"]
    if not d.get("flow_id") or not d.get("authorize_url"):
        raise ZaiError("init response missing flow_id/authorize_url")
    return {
        "poll_token": poll_token,
        "flow_id": d["flow_id"],
        "authorize_url": d["authorize_url"],
        "poll_interval_sec": d.get("poll_interval_sec", 3),
        "expires_at": d.get("expires_at"),
    }


def poll_flow(flow_id, poll_token):
    """One poll. Returns the raw data dict (status pending/ready/failed)."""
    payload = _http(f"{CLI_POLL_URL}/{flow_id}", headers={"Authorization": f"Bearer {poll_token}"})
    if not _ok(payload):
        raise ZaiError(payload.get("msg") or "ZCode poll failed")
    return payload.get("data") or {}


def wait_ready(flow_id, poll_token, interval=3, timeout=300):
    """Poll until ready. Returns the ready data dict (has zai.access_token)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        d = poll_flow(flow_id, poll_token)
        st = d.get("status")
        if st == "ready":
            return d
        if st == "failed":
            raise ZaiError("ZCode authorization failed or was cancelled")
        time.sleep(interval)
    raise ZaiError("ZCode authorization timed out")


# ------------------------------------------------------------------- step 4
def business_login(zai_access_token):
    payload = _http(BUSINESS_LOGIN_URL, "POST", {"token": zai_access_token})
    token = (payload.get("data") or {}).get("access_token") or (payload.get("data") or {}).get("accessToken")
    if not token:
        raise ZaiError(payload.get("msg") or "business login missing access_token")
    return token.strip()


# ------------------------------------------------------------------- step 5
def _biz(url, business_token, method="GET", body=None, label="request"):
    payload = _http(url, method, body, {"Authorization": f"Bearer {business_token}"})
    if not _ok(payload):
        raise ZaiError(f"Z.ai {label}: {payload.get('msg') or payload.get('code')}")
    return payload.get("data") if payload.get("data") is not None else payload


def _default_org_project(customer_info):
    orgs = customer_info.get("organizations") or []
    for org in orgs:
        projects = [p for p in (org.get("projects") or [])
                    if str(p.get("projectType", "")).strip() != "2"]
        if org.get("organizationId") and projects:
            return org, projects[0]
    return None, None


def mint_plan_key(zai_access_token):
    """Full steps 4+5. Returns dict with planApiKey + supporting tokens."""
    business = business_login(zai_access_token)
    hdrs = {"Authorization": f"Bearer {business}"}

    info = _biz(f"{API_BASE}/api/biz/customer/getCustomerInfo", business, label="customer info")
    org, project = _default_org_project(info or {})
    if not org or not project:
        raise ZaiError("no usable Z.ai organization/project (is a coding plan active?)")
    oid, pid = org["organizationId"], project["projectId"]

    base = f"{API_BASE}/api/biz/v1/organization/{oid}/projects/{pid}/api_keys"
    keys = _biz(base, business, label="api keys") or []
    key = None
    if isinstance(keys, list):
        key = next((k.get("apiKey") for k in keys if k.get("name") == PLAN_API_KEY_NAME), None)
    if not key:
        created = _biz(base, business, "POST", {"name": PLAN_API_KEY_NAME}, "api key create")
        key = created.get("apiKey") if isinstance(created, dict) else None
    if not key:
        raise ZaiError("api_keys response is missing apiKey")

    secret = _biz(f"{base}/copy/{key}", business, label="api key copy")
    secret_key = (secret or {}).get("secretKey")
    if not secret_key:
        raise ZaiError("api key copy response is missing secretKey")

    return {
        "planApiKey": f"{key}.{secret_key}",
        "zaiBusinessToken": business,
        "zaiAccessToken": zai_access_token,
        "org": org.get("organizationName"),
        "project": project.get("projectName"),
    }


def usage_quota(business_token):
    """Returns the quota payload; raises if the account has no coding plan."""
    try:
        return _http(f"{API_BASE}/api/monitor/usage/quota/limit",
                     headers={"Authorization": f"Bearer {business_token}"})
    except ZaiError as e:
        return {"error": str(e)}


# --------------------------------------------- browser-side consent (step 2)
APPROVE_JS = r"""
(async () => {
  const u = new URL(location.href);
  const q = Object.fromEntries(u.searchParams);
  const fd = new URLSearchParams({
    client_id: q.client_id, redirect_uri: q.redirect_uri,
    state: q.state, response_type: q.response_type, action: 'approve',
  });
  const res = await fetch('/api/oauth/authorize', {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    credentials: 'include',
    body: fd,
  });
  const txt = await res.text();
  return JSON.stringify({ status: res.status, text: txt });
})()
"""


def consent_url_js(authorize_url):
    """JS to run on chat.z.ai after login: approve consent, then load callback."""
    cb = approve_callback(authorize_url)
    return APPROVE_JS, cb


def approve_callback(authorize_url):
    """Given the authorize_url, return a JS expression that posts consent and
    returns the resulting redirect_url (the CLI callback with ?code=)."""
    return (
        "(async()=>{const u=new URL(%s);const q=Object.fromEntries(u.searchParams);"
        "const fd=new URLSearchParams({client_id:q.client_id,redirect_uri:q.redirect_uri,"
        "state:q.state,response_type:q.response_type,action:'approve'});"
        "const r=await fetch('/api/oauth/authorize',{method:'POST',"
        "headers:{'Content-Type':'application/x-www-form-urlencoded'},"
        "credentials:'include',body:fd});return await r.text();})()"
        % json.dumps(authorize_url)
    )
