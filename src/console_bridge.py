#!/usr/bin/env python3
"""ZCode Pipeline Console - CDP bridge.

Injects a control-panel page into the Browser Use cloud browser and relays its
button clicks to the local pipeline (`zcode_claim.py`). No ports or tunnels are
needed: the page and the bridge live on the same cloud-browser CDP session and
talk over `Runtime.addBinding` / `Runtime.evaluate`.

Usage:
    python console_bridge.py --cdp "$BU_CDP_WS"
"""

import argparse
import asyncio
import json
import os
import subprocess
import sys

import websockets

HERE = os.path.dirname(os.path.abspath(__file__))
DASHBOARD = os.path.join(HERE, "console.html")
PIPELINE = os.path.join(HERE, "zcode_claim.py")

# Installed on every new document in the z.ai solver tab: wraps initAliyunCaptcha
# so the moment the slider passes, the produced captchaVerifyParam is stashed in
# window.__capParams AND persisted server-side by the bridge (see param_poller).
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
                    if params.get("name") == "bcodeCmd" and self._binding_event:
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
        return await asyncio.wait_for(fut, timeout=60)

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


async def set_status(cdp, sid, stage, state, msg=""):
    try:
        await eval_js(cdp, sid,
                      "window.__bcodeStatus && window.__bcodeStatus(%s,%s,%s)"
                      % (json.dumps(stage), json.dumps(state), json.dumps(msg)))
    except Exception:
        pass


async def run_pipeline(args_list, cdp, sid):
    """Run zcode_claim.py, streaming stdout lines into the dashboard."""
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-u", PIPELINE, *args_list,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=HERE,
    )
    while True:
        line = await proc.stdout.readline()
        if not line:
            break
        await push_log(cdp, sid, "out", line.decode(errors="replace").rstrip("\n"))
    await proc.wait()
    return proc.returncode


async def handle_command(cmd, cdp, sid, solver_sessions):
    action = cmd.get("action")
    p = cmd.get("payload") or {}

    try:
        if action == "ping":
            await push_log(cdp, sid, "ok", "bridge alive")
            return

        if action == "inject":
            token = (p.get("token") or "").strip()
            cookies = (p.get("cookies") or "").strip()
            email = (p.get("email") or "").strip()
            if not token and not cookies:
                await set_status(cdp, sid, "inject", "error", "need token or cookies")
                return
            await set_status(cdp, sid, "inject", "running", "minting ZCode JWT...")
            a = ["--cdp", cdp.ws_url, "--no-claim",
                 "--out", "/tmp/bcode/console_inject.json"]
            if token:
                a += ["--token", token]
            if cookies:
                a += ["--cookies", cookies]
            if email:
                a += ["--email", email]
            rc = await run_pipeline(a, cdp, sid)
            await set_status(cdp, sid, "inject", "done" if rc == 0 else "error", f"exit {rc}")
            return

        if action == "claim":
            param = (p.get("captcha_param") or "").strip()
            email = (p.get("email") or "").strip()
            if not param:
                await set_status(cdp, sid, "claim", "error",
                                 "paste the captcha param (solve the slider first)")
                return
            await set_status(cdp, sid, "claim", "running", "claiming Start Plan...")
            a = ["--captcha-param", param, "--out", "/tmp/bcode/console_claim.json"]
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
            rc = await run_pipeline(a, cdp, sid)
            await set_status(cdp, sid, "claim", "done" if rc == 0 else "error", f"exit {rc}")
            return

        if action == "connect":
            base = (p.get("base") or "http://localhost:20128").strip()
            pw = (p.get("password") or "123456").strip()
            await set_status(cdp, sid, "connect", "running", "registering to 9Router...")
            a = ["--connect", "--base", base, "--9router-password", pw,
                 "--out", "/tmp/bcode/console_connect.json"]
            jwt = (p.get("jwt") or "").strip()
            token = (p.get("token") or "").strip()
            cookies = (p.get("cookies") or "").strip()
            if jwt:
                a += ["--jwt-file", jwt]
            elif token:
                a += ["--token", token]
            elif cookies:
                a += ["--cookies", cookies]
            rc = await run_pipeline(a, cdp, sid)
            await set_status(cdp, sid, "connect", "done" if rc == 0 else "error", f"exit {rc}")
            return

        if action == "opencaptcha":
            await set_status(cdp, sid, "log", "running", "opening z.ai tab")
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
                           f"opened z.ai auth tab ({new_tid[:8]}…) — solve the slider there, "
                           "the param is captured automatically")
            await set_status(cdp, sid, "log", "done", "ready")
            return

        if action == "grabparam":
            path = "/tmp/bcode/login_param.txt"
            if not os.path.exists(path):
                await push_log(cdp, sid, "err",
                               "no captured param yet — solve the slider in the z.ai tab first")
                return
            with open(path, encoding="utf-8") as f:
                val = f.read().strip()
            if not val:
                await push_log(cdp, sid, "err", "captured param file is empty")
                return
            await eval_js(cdp, sid,
                          "document.getElementById('param').value=%s" % json.dumps(val))
            await push_log(cdp, sid, "ok", "param loaded into box 2 (first 60 chars): " + val[:60])
            return

        await push_log(cdp, sid, "err", f"unknown action: {action}")
    except Exception as e:
        await push_log(cdp, sid, "err", f"handler error: {e!r}")
        await set_status(cdp, sid, action, "error", str(e)[:120])


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cdp", default=os.environ.get("BU_CDP_WS"))
    args = ap.parse_args()
    if not args.cdp:
        raise SystemExit("need --cdp or BU_CDP_WS")

    with open(DASHBOARD, encoding="utf-8") as f:
        html = f.read()

    cdp = CDP(args.cdp)
    await cdp.connect()
    tid = await pick_page(cdp)
    att = await cdp.send("Target.attachToTarget", {"targetId": tid, "flatten": True})
    sid = att["result"]["sessionId"]
    await cdp.send("Page.enable", {}, session_id=sid)
    await cdp.send("Runtime.enable", {}, session_id=sid)
    await cdp.send("Runtime.addBinding", {"name": "bcodeCmd"}, session_id=sid)

    await cdp.send("Page.navigate",
                   {"url": "https://usercontent.browser-use.tools"}, session_id=sid)
    await asyncio.sleep(2.5)
    await cdp.send("Page.setDocumentContent",
                   {"frameId": tid, "html": html}, session_id=sid)

    print(f"[bridge] dashboard injected (target {tid})", flush=True)

    solver_sessions = []

    async def on_binding(payload):
        try:
            cmd = json.loads(payload)
        except Exception:
            return
        print(f"[bridge] cmd: {cmd.get('action')}", flush=True)
        asyncio.create_task(handle_command(cmd, cdp, sid, solver_sessions))

    async def param_poller():
        """Watch the solver tab(s) for a captured captchaVerifyParam and persist it."""
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
                    old = ""
                    if os.path.exists("/tmp/bcode/login_param.txt"):
                        old = open("/tmp/bcode/login_param.txt").read().strip()
                    if val and val != old:
                        os.makedirs("/tmp/bcode", exist_ok=True)
                        with open("/tmp/bcode/login_param.txt", "w") as f:
                            f.write(val)
                        await push_log(cdp, sid, "ok",
                                       "captcha solved — param captured! "
                                       "Now paste box 2 or click Claim.")
                        await eval_js(cdp, sid,
                                      "document.getElementById('param').value=%s"
                                      % json.dumps(val))
                        await set_status(cdp, sid, "claim", "idle", "param ready")
                except Exception as e:
                    await push_log(cdp, sid, "err", f"param persist: {e!r}")

    cdp.on_binding(on_binding)
    await asyncio.create_task(param_poller())
    await asyncio.sleep(3600)


if __name__ == "__main__":
    asyncio.run(main())
