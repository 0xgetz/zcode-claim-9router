#!/usr/bin/env python3
"""ZCode Pipeline Console - CDP bridge (Level 3).

Serves a full multi-page SPA into the Browser Use cloud browser and relays its
requests to the local pipeline (`zcode_claim.py`). No ports or tunnels: the page
and this bridge talk over the same CDP session via `Runtime.addBinding` and
`Runtime.evaluate`, using a request/response envelope so the page can call
"server" functions.

Usage:
    python console_bridge.py --cdp "$BU_CDP_WS"

RPC protocol (page -> bridge):
    page calls  window.bcodeRpc(JSON.stringify({id, action, payload}))
    bridge runs  the action and calls back
                 window.__bcodeReply(id, ok, data)

Actions:
    ping, inject, claim, connect
    opencaptcha, grabparam
    accounts.list / add / remove / clear / import / export
    batch.run
    fs.read / fs.write / fs.delete
    results.get
    status
"""

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time

import websockets

HERE = os.path.dirname(os.path.abspath(__file__))
DASHBOARD = os.path.join(HERE, "console.html")
PIPELINE = os.path.join(HERE, "zcode_claim.py")
WORK = os.environ.get("ZCODE_CONSOLE_WORK", os.path.join(HERE, "console_data"))
ACCOUNTS_FILE = os.path.join(WORK, "accounts.json")
RESULTS_FILE = os.path.join(WORK, "results.json")
PARAM_FILE = os.path.join(WORK, "captcha_param.txt")

# Installed on every new document in the z.ai solver tab: wraps initAliyunCaptcha
# so the moment the slider passes the produced captchaVerifyParam is stashed in
# window.__capParams AND persisted server-side by param_poller.
_CAPTCHA_HOOK = r"""
(() => {
  window.__capParams = window.__capParams || [];
  const iv = setInterval(() => {
    if (window.initAliyunCaptcha && !window.__wrapped) {
      window.__wrapped = true;
      const o = window.initAliyunCaptcha;
      window.initAliyunCaptcha = (c) => {
        const s = c.success;
        c.success = (p) => { try { window.__capParams.push(p); } catch(e){} try { s && s(p); } catch(e){} };
        return o(c);
      };
    }
  }, 30);
})();
"""


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def ensure_work():
    os.makedirs(WORK, exist_ok=True)


def safe_read(path, default=""):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except Exception:
        return default


def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path, data):
    ensure_work()
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


def append_result(stage, email, exit_code, result):
    """Record a single-stage run so the Results page can show it."""
    data = load_json(RESULTS_FILE, {"results": []})
    data["results"] = [r for r in data.get("results", [])
                       if not (r.get("stage") == stage and r.get("email") == email)]
    data["results"].append({"stage": stage, "email": email,
                            "exit": exit_code, "result": result,
                            "at": time.time()})
    save_json(RESULTS_FILE, data)


def extract_json_objects(text):
    """Pull every top-level JSON object out of mixed stdout."""
    out, depth, start = [], 0, None
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and start is not None:
                    try:
                        out.append(json.loads(text[start:i + 1]))
                    except Exception:
                        pass
    return out


# --------------------------------------------------------------------------- #
# CDP
# --------------------------------------------------------------------------- #
class CDP:
    def __init__(self, ws_url):
        self.ws_url = ws_url
        self.ws = None
        self._id = 0
        self._pending = {}
        self._binding_event = None

    async def connect(self):
        self.ws = await websockets.connect(self.ws_url, max_size=128 * 1024 * 1024)
        self._recv_task = asyncio.create_task(self._recv_loop())

    async def _recv_loop(self):
        try:
            async for raw in self.ws:
                msg = json.loads(raw)
                if "id" in msg and msg["id"] in self._pending:
                    fut = self._pending.pop(msg["id"])
                    if not fut.done():
                        fut.set_result(msg)
                elif msg.get("method") == "Runtime.bindingCalled":
                    params = msg.get("params", {})
                    if params.get("name") == "bcodeRpc" and self._binding_event:
                        try:
                            res = self._binding_event(params.get("payload"))
                            if asyncio.iscoroutine(res):
                                asyncio.create_task(res)
                        except Exception:
                            pass
        except Exception:
            pass

    async def send(self, method, params=None, session_id=None):
        self._id += 1
        mid = self._id
        payload = {"id": mid, "method": method, "params": params or {}}
        if session_id:
            payload["sessionId"] = session_id
        fut = asyncio.get_event_loop().create_future()
        self._pending[mid] = fut
        await self.ws.send(json.dumps(payload))
        return await asyncio.wait_for(fut, timeout=120)

    def on_binding(self, cb):
        self._binding_event = cb


async def pick_page(cdp):
    tg = await cdp.send("Target.getTargets")
    pages = [t for t in tg["result"]["targetInfos"]
             if t["type"] == "page" and not t["url"].startswith("chrome://")]
    if pages:
        return pages[0]["targetId"]
    nt = await cdp.send("Target.createTarget", {"url": "about:blank"})
    return nt["result"]["targetId"]


async def eval_js(cdp, session_id, expr):
    r = await cdp.send("Runtime.evaluate", {
        "expression": expr, "returnByValue": True,
    }, session_id=session_id)
    return r.get("result", {}).get("result", {}).get("value")


async def push_log(cdp, sid, level, text):
    try:
        await eval_js(cdp, sid,
                      "window.__bcodeLog && window.__bcodeLog(%s,%s)"
                      % (json.dumps(level), json.dumps(text)))
    except Exception:
        pass


async def push_status(cdp, sid, stage, state, msg=""):
    try:
        await eval_js(cdp, sid,
                      "window.__bcodeStatus && window.__bcodeStatus(%s,%s,%s)"
                      % (json.dumps(stage), json.dumps(state), json.dumps(msg)))
    except Exception:
        pass


async def reply(cdp, sid, rid, ok, data):
    try:
        await eval_js(cdp, sid,
                      "window.__bcodeReply && window.__bcodeReply(%s,%s,%s)"
                      % (json.dumps(rid), json.dumps(bool(ok)), json.dumps(data)))
    except Exception:
        pass


async def run_pipeline(args_list, cdp, sid):
    """Run zcode_claim.py, streaming stdout into the dashboard. Returns (rc, text)."""
    ensure_work()
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-u", PIPELINE, *args_list,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=HERE,
    )
    chunks = []
    while True:
        line = await proc.stdout.readline()
        if not line:
            break
        s = line.decode(errors="replace").rstrip("\n")
        chunks.append(s)
        await push_log(cdp, sid, "out", s)
    await proc.wait()
    return proc.returncode, "\n".join(chunks)


# --------------------------------------------------------------------------- #
# accounts registry
# --------------------------------------------------------------------------- #
def accounts_load():
    return load_json(ACCOUNTS_FILE, {"accounts": []})


def accounts_save(data):
    save_json(ACCOUNTS_FILE, data)


def norm_account(p):
    a = {
        "email": (p.get("email") or "").strip(),
        "token": (p.get("token") or "").strip(),
        "cookies": (p.get("cookies") or "").strip(),
        "password": (p.get("password") or "").strip(),
        "jwt": (p.get("jwt") or "").strip(),
    }
    return {k: v for k, v in a.items() if v}


# --------------------------------------------------------------------------- #
# command handlers
# --------------------------------------------------------------------------- #
async def cmd_ping(cdp, sid, p):
    return True, {"alive": True, "time": time.time(),
                  "work": WORK}


async def cmd_inject(cdp, sid, p):
    token = (p.get("token") or "").strip()
    cookies = (p.get("cookies") or "").strip()
    email = (p.get("email") or "").strip()
    if not token and not cookies:
        await push_status(cdp, sid, "inject", "error", "need token or cookies")
        return False, {"error": "need token or cookies"}
    await push_status(cdp, sid, "inject", "running", "minting ZCode JWT...")
    out_path = os.path.join(WORK, "inject_result.json")
    a = ["--cdp", cdp.ws_url, "--no-claim", "--out", out_path]
    if token:
        a += ["--token", token]
    if cookies:
        a += ["--cookies", cookies]
    if email:
        a += ["--email", email]
    rc, text = await run_pipeline(a, cdp, sid)
    result = load_json(out_path, {})
    append_result("inject", email, rc, result)
    await push_status(cdp, sid, "inject", "done" if rc == 0 else "error", f"exit {rc}")
    return rc == 0, {"exit": rc, "result": result, "log": text[-4000:]}


async def cmd_claim(cdp, sid, p):
    param = (p.get("captcha_param") or "").strip()
    email = (p.get("email") or "").strip()
    if not param:
        await push_status(cdp, sid, "claim", "error", "paste/solve the captcha param first")
        return False, {"error": "missing captcha param"}
    await push_status(cdp, sid, "claim", "running", "claiming Start Plan...")
    out_path = os.path.join(WORK, "claim_result.json")
    a = ["--captcha-param", param, "--out", out_path]
    jwt = (p.get("jwt") or "").strip()
    token = (p.get("token") or "").strip()
    cookies = (p.get("cookies") or "").strip()
    if jwt:
        a += ["--jwt-file", jwt]
    elif token:
        a += ["--token", token]
    elif cookies:
        a += ["--cookies", cookies]
    if email:
        a += ["--email", email]
    rc, text = await run_pipeline(a, cdp, sid)
    result = load_json(out_path, {})
    append_result("claim", email, rc, result)
    await push_status(cdp, sid, "claim", "done" if rc == 0 else "error", f"exit {rc}")
    return rc == 0, {"exit": rc, "result": result, "log": text[-4000:]}


async def cmd_connect(cdp, sid, p):
    base = (p.get("base") or "http://localhost:20128").strip()
    pw = (p.get("password") or "123456").strip()
    await push_status(cdp, sid, "connect", "running", "registering to 9Router...")
    out_path = os.path.join(WORK, "connect_result.json")
    a = ["--connect", "--base", base, "--9router-password", pw, "--out", out_path]
    jwt = (p.get("jwt") or "").strip()
    token = (p.get("token") or "").strip()
    cookies = (p.get("cookies") or "").strip()
    if jwt:
        a += ["--jwt-file", jwt]
    elif token:
        a += ["--token", token]
    elif cookies:
        a += ["--cookies", cookies]
    rc, text = await run_pipeline(a, cdp, sid)
    result = load_json(out_path, {})
    email = (p.get("email") or "").strip()
    append_result("connect", email, rc, result)
    await push_status(cdp, sid, "connect", "done" if rc == 0 else "error", f"exit {rc}")
    return rc == 0, {"exit": rc, "result": result, "log": text[-4000:]}


async def cmd_opencaptcha(cdp, sid, p, solver_sessions):
    await push_status(cdp, sid, "log", "running", "opening z.ai tab")
    nt = await cdp.send("Target.createTarget", {"url": "about:blank"})
    new_tid = nt["result"]["targetId"]
    att2 = await cdp.send("Target.attachToTarget",
                          {"targetId": new_tid, "flatten": True})
    sid2 = att2["result"]["sessionId"]
    await cdp.send("Page.enable", {}, session_id=sid2)
    await cdp.send("Runtime.enable", {}, session_id=sid2)
    await cdp.send("Page.addScriptToEvaluateOnNewDocument",
                   {"source": _CAPTCHA_HOOK}, session_id=sid2)
    await cdp.send("Page.navigate",
                   {"url": "https://chat.z.ai/auth"}, session_id=sid2)
    solver_sessions.append(sid2)
    await push_log(cdp, sid, "ok",
                   f"opened z.ai auth tab ({new_tid[:8]}…) — sign in and solve the "
                   "slider; the param is captured automatically")
    await push_status(cdp, sid, "log", "done", "ready")
    return True, {"tab": new_tid}


async def cmd_grabparam(cdp, sid, p):
    if not os.path.exists(PARAM_FILE):
        return False, {"error": "no captured param yet — solve the slider first"}
    val = safe_read(PARAM_FILE).strip()
    if not val:
        return False, {"error": "captured param file is empty"}
    return True, {"param": val}


async def cmd_accounts_list(cdp, sid, p):
    return True, accounts_load()


async def cmd_accounts_add(cdp, sid, p):
    data = accounts_load()
    acct = norm_account(p)
    if not acct:
        return False, {"error": "empty account"}
    # de-dupe by email+credential
    data["accounts"] = [a for a in data["accounts"]
                        if json.dumps(a, sort_keys=True) != json.dumps(acct, sort_keys=True)]
    data["accounts"].append(acct)
    accounts_save(data)
    return True, data


async def cmd_accounts_remove(cdp, sid, p):
    idx = p.get("index")
    data = accounts_load()
    if isinstance(idx, int) and 0 <= idx < len(data["accounts"]):
        data["accounts"].pop(idx)
        accounts_save(data)
        return True, data
    return False, {"error": "bad index"}


async def cmd_accounts_clear(cdp, sid, p):
    data = {"accounts": []}
    accounts_save(data)
    return True, data


async def cmd_accounts_import(cdp, sid, p):
    """Import from pasted text: JSON {accounts:[...]}, a JSON list, or CSV lines."""
    text = (p.get("text") or "").strip()
    imported = []
    if not text:
        return False, {"error": "empty input"}
    try:
        obj = json.loads(text)
        if isinstance(obj, dict) and isinstance(obj.get("accounts"), list):
            imported = [norm_account(x) for x in obj["accounts"]]
        elif isinstance(obj, list):
            imported = [norm_account(x) for x in obj]
        elif isinstance(obj, dict):
            imported = [norm_account(obj)]
    except Exception:
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = [x.strip() for x in line.split(",")]
            if len(parts) >= 3:
                imported.append(norm_account(
                    {"email": parts[0], "password": parts[1], "token": parts[2]}))
            elif len(parts) == 2:
                imported.append(norm_account({"email": parts[0], "token": parts[1]}))
    imported = [x for x in imported if x]
    if not imported:
        return False, {"error": "no accounts parsed"}
    data = accounts_load()
    seen = {json.dumps(a, sort_keys=True) for a in data["accounts"]}
    added = 0
    for a in imported:
        k = json.dumps(a, sort_keys=True)
        if k not in seen:
            seen.add(k)
            data["accounts"].append(a)
            added += 1
    accounts_save(data)
    return True, {"added": added, "total": len(data["accounts"]), "accounts": data["accounts"]}


async def cmd_accounts_export(cdp, sid, p):
    return True, accounts_load()


async def cmd_batch_run(cdp, sid, p):
    """Run the full pipeline over every registered account sequentially."""
    data = accounts_load()
    accts = data["accounts"]
    if not accts:
        return False, {"error": "no accounts registered"}
    param = (p.get("captcha_param") or safe_read(PARAM_FILE).strip()).strip()
    base = (p.get("base") or "http://localhost:20128").strip()
    pw = (p.get("password") or "123456").strip()
    do_connect = bool(p.get("connect", True))

    results = []
    await push_status(cdp, sid, "batch", "running", f"0/{len(accts)}")
    for i, a in enumerate(accts):
        await push_log(cdp, sid, "ok", f"=== account {i + 1}/{len(accts)}: "
                                       f"{a.get('email', '(no email)')} ===")
        out_path = os.path.join(WORK, f"batch_{i}.json")
        args = ["--out", out_path]
        if a.get("token"):
            args += ["--token", a["token"]]
        elif a.get("cookies"):
            args += ["--cookies", a["cookies"]]
        elif a.get("password") and a.get("email"):
            args += ["--email", a["email"], "--password", a["password"]]
        if a.get("email"):
            args += ["--email", a["email"]]
        if param:
            args += ["--captcha-param", param]
        if do_connect:
            args += ["--connect", "--base", base, "--9router-password", pw]
        rc, text = await run_pipeline(["--cdp", cdp.ws_url] + args, cdp, sid)
        res = load_json(out_path, {})
        results.append({"email": a.get("email", ""), "exit": rc, "result": res})
        await push_status(cdp, sid, "batch", "running", f"{i + 1}/{len(accts)}")
    save_json(RESULTS_FILE, {"results": results, "at": time.time()})
    await push_status(cdp, sid, "batch", "done", f"{len(accts)} accounts")
    ok = all(r["exit"] == 0 for r in results)
    return ok, {"results": results}


async def cmd_fs_read(cdp, sid, p):
    path = p.get("path") or ""
    if not path:
        return False, {"error": "no path"}
    return True, {"path": path, "content": safe_read(path)}


async def cmd_fs_write(cdp, sid, p):
    path = p.get("path") or ""
    content = p.get("content") or ""
    if not path:
        return False, {"error": "no path"}
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return True, {"path": path, "bytes": len(content)}


async def cmd_results_get(cdp, sid, p):
    return True, load_json(RESULTS_FILE, {"results": []})


async def cmd_status(cdp, sid, p):
    jwt = (p.get("jwt") or "").strip()
    if not jwt or not os.path.exists(jwt):
        return False, {"error": "provide a jwt file path"}
    a = ["--jwt-file", jwt, "--status"]
    rc, text = await run_pipeline(a, cdp, sid)
    return rc == 0, {"exit": rc, "log": text[-2000:]}


# --------------------------------------------------------------------------- #
# dispatch
# --------------------------------------------------------------------------- #
async def handle_command(cmd, cdp, sid, solver_sessions):
    action = cmd.get("action")
    rid = cmd.get("id")
    p = cmd.get("payload") or {}
    try:
        if action == "opencaptcha":
            ok, data = await cmd_opencaptcha(cdp, sid, p, solver_sessions)
        elif action == "inject":
            ok, data = await cmd_inject(cdp, sid, p)
        elif action == "claim":
            ok, data = await cmd_claim(cdp, sid, p)
        elif action == "connect":
            ok, data = await cmd_connect(cdp, sid, p)
        elif action == "grabparam":
            ok, data = await cmd_grabparam(cdp, sid, p)
        elif action == "accounts.list":
            ok, data = await cmd_accounts_list(cdp, sid, p)
        elif action == "accounts.add":
            ok, data = await cmd_accounts_add(cdp, sid, p)
        elif action == "accounts.remove":
            ok, data = await cmd_accounts_remove(cdp, sid, p)
        elif action == "accounts.clear":
            ok, data = await cmd_accounts_clear(cdp, sid, p)
        elif action == "accounts.import":
            ok, data = await cmd_accounts_import(cdp, sid, p)
        elif action == "accounts.export":
            ok, data = await cmd_accounts_export(cdp, sid, p)
        elif action == "batch.run":
            ok, data = await cmd_batch_run(cdp, sid, p)
        elif action == "fs.read":
            ok, data = await cmd_fs_read(cdp, sid, p)
        elif action == "fs.write":
            ok, data = await cmd_fs_write(cdp, sid, p)
        elif action == "results.get":
            ok, data = await cmd_results_get(cdp, sid, p)
        elif action == "status":
            ok, data = await cmd_status(cdp, sid, p)
        elif action == "ping":
            ok, data = await cmd_ping(cdp, sid, p)
        else:
            ok, data = False, {"error": f"unknown action: {action}"}
    except Exception as e:
        ok, data = False, {"error": repr(e)[:200]}
    if rid is not None:
        await reply(cdp, sid, rid, ok, data)


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cdp", default=os.environ.get("BU_CDP_WS"))
    args = ap.parse_args()
    if not args.cdp:
        raise SystemExit("need --cdp or BU_CDP_WS")

    ensure_work()
    with open(DASHBOARD, encoding="utf-8") as f:
        html = f.read()

    cdp = CDP(args.cdp)
    await cdp.connect()
    tid = await pick_page(cdp)
    att = await cdp.send("Target.attachToTarget", {"targetId": tid, "flatten": True})
    sid = att["result"]["sessionId"]
    await cdp.send("Page.enable", {}, session_id=sid)
    await cdp.send("Runtime.enable", {}, session_id=sid)
    await cdp.send("Runtime.addBinding", {"name": "bcodeRpc"}, session_id=sid)

    await cdp.send("Page.navigate",
                   {"url": "https://usercontent.browser-use.tools"}, session_id=sid)
    await asyncio.sleep(2.5)
    await cdp.send("Page.setDocumentContent",
                   {"frameId": tid, "html": html}, session_id=sid)

    print(f"[bridge] console injected (target {tid})", flush=True)
    print(f"[bridge] work dir: {WORK}", flush=True)

    solver_sessions = []

    async def on_binding(payload):
        try:
            cmd = json.loads(payload)
        except Exception:
            return
        print(f"[bridge] rpc: {cmd.get('action')}", flush=True)
        asyncio.create_task(handle_command(cmd, cdp, sid, solver_sessions))

    async def param_poller():
        while True:
            await asyncio.sleep(2)
            for s in list(solver_sessions):
                try:
                    val = await eval_js(
                        cdp, s,
                        "(window.__capParams && window.__capParams.length)"
                        " ? window.__capParams[window.__capParams.length-1] : null")
                except Exception:
                    continue
                if not val:
                    continue
                try:
                    if isinstance(val, dict):
                        val = val.get("captchaVerifyParam") or val.get("data") or json.dumps(val)
                    if not isinstance(val, str):
                        val = str(val)
                    old = safe_read(PARAM_FILE).strip()
                    if val and val != old:
                        with open(PARAM_FILE, "w") as f:
                            f.write(val)
                        await push_log(cdp, sid, "ok",
                                       "captcha solved — param captured automatically")
                        await eval_js(cdp, sid,
                                      "window.__bcodeParam && window.__bcodeParam(%s)"
                                      % json.dumps(val))
                        await push_status(cdp, sid, "claim", "idle", "param ready")
                except Exception as e:
                    await push_log(cdp, sid, "err", f"param persist: {e!r}")

    cdp.on_binding(on_binding)
    asyncio.create_task(param_poller())
    await asyncio.sleep(3600)


if __name__ == "__main__":
    asyncio.run(main())
