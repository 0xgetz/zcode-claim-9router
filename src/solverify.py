"""Solverify (https://solverify.net) API client for Aliyun Captcha 2.0.

Solverify is an async CAPTCHA-solving service.  For Aliyun Captcha 2.0 it runs a
real browser session through a proxy you supply and returns the Aliyun
verification payload (`solution.value`), a base64 JSON blob of the form
``{"certifyId": "...", "sceneId": "...", "deviceToken": "...", "data": "..."}``.

That payload is exactly what ``X-Aliyun-Captcha-Verify-Param`` wants.

Key points from the docs (https://solverify.net/docs/aliyun):
    * ``createTask`` task type is ``aliyun``.
    * Required: ``websiteURL``, ``websiteKey`` (= SceneId), ``prefix``, and the
      proxy fields (``proxyType`` always ``http``, ``proxyAddress``,
      ``proxyPort``).
    * ``region`` is ``sgp`` (default) or ``cn``.
    * ``solution.value`` may be a JSON-encoded string or a dict; it is the value
      you pass straight through as the captcha-verify param.
    * A full solve is ~10-60s; the worker timeout is ~120s.
    * The Aliyun device token is bound to the network path that produced it, so
      the follow-up request should go out through the same proxy.

Pricing: Aliyun is $0.20 / 1000 solves ($0.0002 each).
"""

import base64
import json
import time
import urllib.error
import urllib.request

BASE = "https://solver.solverify.net"


class SolverifyError(Exception):
    pass


def _post(path, payload, timeout=40):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(BASE + path, data=data,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode())
        except Exception:
            raise SolverifyError(f"HTTP {e.code} on {path}")


def balance(client_key):
    return _post("/getBalance", {"clientKey": client_key})


def profile(client_key):
    return _post("/profile", {"clientKey": client_key})


def active_tasks(client_key):
    return _post("/activeTasks", {"clientKey": client_key})


def create_aliyun_task(client_key, website_url, scene_id, prefix,
                       proxy, region="sgp", useragent=None, timeout=40):
    """Create an Aliyun task. `proxy` is "host:port" (or host, port tuple)."""
    if isinstance(proxy, str):
        host, _, port = proxy.partition(":")
    else:
        host, port = proxy
    task = {
        "type": "aliyun",
        "websiteURL": website_url,
        "websiteKey": scene_id,
        "prefix": prefix,
        "region": region,
        "proxyType": "http",
        "proxyAddress": host,
        "proxyPort": str(port),
    }
    if useragent:
        task["useragent"] = useragent
    resp = _post("/createTask", {"clientKey": client_key, "task": task},
                 timeout=timeout)
    if resp.get("errorId") != 0:
        raise SolverifyError(
            f"{resp.get('errorCode')}: {resp.get('errorDescription')}")
    return resp["taskId"]


def get_result(client_key, task_id, timeout=30):
    return _post("/getTaskResult",
                 {"clientKey": client_key, "taskId": task_id}, timeout=timeout)


def _decode_value(value):
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(base64.b64decode(value).decode())
    except Exception:
        try:
            return json.loads(value)
        except Exception:
            return value


def solve_aliyun(client_key, website_url, scene_id, prefix, proxy,
                 region="sgp", deadline=180, poll=5, log=print,
                 require_real=True):
    """Create a task, poll to completion, and return (raw_value, decoded).

    ``raw_value`` is what you put in ``X-Aliyun-Captcha-Verify-Param``.
    ``decoded`` is the parsed dict (for inspection).

    When ``require_real`` is set, a payload lacking Aliyun's ``data`` /
    ``deviceToken`` fields is treated as a soft failure (the solver only
    produced a stub) and an exception is raised so the caller can retry with a
    different proxy.
    """
    tid = create_aliyun_task(client_key, website_url, scene_id, prefix, proxy,
                             region=region)
    log(f"  solverify task {tid} via {proxy}")
    start = time.time()
    while time.time() - start < deadline:
        time.sleep(poll)
        g = get_result(client_key, tid)
        st = g.get("status")
        if st == "completed":
            raw = g["solution"]["value"]
            dec = _decode_value(raw)
            if require_real and isinstance(dec, dict) and not (
                    dec.get("data") or dec.get("deviceToken")):
                raise SolverifyError(f"solverify returned a stub payload: {dec}")
            if isinstance(raw, (dict, list)):
                raw = json.dumps(raw)
            return raw, dec
        if st == "failed":
            raise SolverifyError(
                f"task failed: {g.get('errorCode')} {g.get('errorDescription')}")
    raise SolverifyError("solverify timeout")


def solve_aliyun_retry(client_key, website_url, scene_id, prefix, proxies,
                       region="sgp", attempts=3, log=print):
    """Try each proxy (and retry) until a *real* payload comes back.

    Returns (raw_value, decoded, proxy_used) or raises SolverifyError.
    """
    last = None
    for attempt in range(attempts):
        for proxy in proxies:
            try:
                raw, dec = solve_aliyun(
                    client_key, website_url, scene_id, prefix, proxy,
                    region=region, log=log)
                return raw, dec, proxy
            except SolverifyError as e:
                last = e
                log(f"  proxy {proxy} failed: {e}")
    raise SolverifyError(f"no real solve after {attempts} attempt(s): {last}")


if __name__ == "__main__":
    import os
    import sys
    key = os.environ.get("SOLVERIFY_API_KEY") or (
        sys.argv[1] if len(sys.argv) > 1 else "")
    if not key:
        print("usage: SOLVERIFY_API_KEY=... python solverify.py")
        sys.exit(1)
    print("balance:", balance(key))
    print("profile:", profile(key))
