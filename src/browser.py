#!/usr/bin/env python3
"""Browser connection resolver.

The toolkit must run anywhere: a laptop with Chrome, a headless VPS, or a
Browser Use cloud browser.  Every stage talks to Chromium over CDP, so all we
need is a reachable CDP endpoint.  This module finds one.

Resolution order (first hit wins):

  1. explicit URL       --cdp "ws://..."  or  BU_CDP_WS
  2. explicit endpoint  --connect host:port          -> http://host:port
  3. already-running    probe 127.0.0.1:$CDP_PORT    (default 9222)
  4. auto-launch        start a local Chrome/Chromium with remote debugging
                        (headless on a VPS / --headless, else a real window)

Public API
----------
    resolve_cdp(cdp=None, connect=None, port=9222, launch=True,
                headless=None, user_data_dir=None, profile=None, log=print)
        -> ws URL string

    launch_chrome(port=9222, headless=True, user_data_dir=None,
                  executable=None, log=print) -> (ws_url, process)

    attach(cdp_ws_or_none, **kw) -> str            # convenience alias
"""

import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import time
import urllib.request

DEFAULT_PORT = int(os.environ.get("CDP_PORT", "9222"))
_LOCAL_DIR = os.path.join(os.path.expanduser("~"), ".cache", "zcode-claim-chrome")

# A broad list of Chrome/Chromium/Edge/Brave binary names across OSes.
_BIN_NAMES = [
    "google-chrome", "google-chrome-stable", "chromium", "chromium-browser",
    "chrome", "google-chrome-beta", "google-chrome-unstable",
    "microsoft-edge", "microsoft-edge-stable", "brave-browser", "brave",
]
_MAC_PATHS = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
]
_WIN_NAMES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]


def find_chrome(explicit=None):
    """Return a path to a Chrome/Chromium executable, or None."""
    if explicit:
        return explicit if os.path.exists(explicit) else shutil.which(explicit)
    for name in _BIN_NAMES:
        p = shutil.which(name)
        if p:
            return p
    if platform.system() == "Darwin":
        for p in _MAC_PATHS:
            if os.path.exists(p):
                return p
    if platform.system() == "Windows":
        for p in _WIN_PATHS:
            if os.path.exists(p):
                return p
    # Playwright's bundled chromium: scan the cache dir directly (robust even
    # when the playwright driver itself cannot start, e.g. under LD_LIBRARY_PATH).
    import glob
    cache_root = os.path.join(os.path.expanduser("~"), ".cache", "ms-playwright")
    for pat in ("chromium-*/chrome-linux*/chrome",
                "chromium_headless_shell-*/chrome-linux*/headless_shell",
                "chromium-*/chrome-mac*/Chromium.app/Contents/MacOS/Chromium",
                "chromium-*/chrome-win*/chrome.exe"):
        hits = sorted(glob.glob(os.path.join(cache_root, pat)))
        for h in hits:
            if os.path.exists(h):
                return h
    # last resort: ask playwright
    try:
        from playwright.sync_api import sync_playwright  # noqa
        with sync_playwright() as pw:
            p = pw.chromium.executable_path
            if p and os.path.exists(p):
                return p
    except Exception:
        pass
    return None


def _http_ok(host, port, timeout=1.0):
    try:
        with urllib.request.urlopen(f"http://{host}:{port}/json/version",
                                    timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


def _port_free(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


def _ws_from_devtools(host, port):
    """Read the browser websocket URL from /json/version."""
    with urllib.request.urlopen(f"http://{host}:{port}/json/version", timeout=3) as r:
        data = json.loads(r.read().decode())
    ws = data.get("webSocketDebuggerUrl")
    if not ws:
        raise RuntimeError("no webSocketDebuggerUrl from /json/version")
    # On a remote host the response may say 127.0.0.1; rewrite to the real host.
    if host not in ("127.0.0.1", "localhost"):
        ws = ws.replace("127.0.0.1", host).replace("localhost", host)
    return ws


def _is_ws(url):
    return isinstance(url, str) and (url.startswith("ws://") or url.startswith("wss://"))


def launch_chrome(port=DEFAULT_PORT, headless=True, user_data_dir=None,
                  executable=None, log=print, extra_args=None):
    """Launch a local Chrome/Chromium with remote debugging. Returns (ws_url, proc)."""
    exe = find_chrome(executable)
    if not exe:
        raise RuntimeError(
            "no Chrome/Chromium found. Install one (apt install chromium-browser, "
            "brew install --cask google-chrome, or 'python -m playwright install "
            "chromium') or point at a running browser with --cdp/--connect.")
    if not user_data_dir:
        user_data_dir = os.path.join(_LOCAL_DIR, f"profile-{port}")
    os.makedirs(user_data_dir, exist_ok=True)

    if not _port_free(port):
        # something is already listening; reuse it
        if _http_ok("127.0.0.1", port):
            log(f"[browser] reusing browser already on port {port}")
            return _ws_from_devtools("127.0.0.1", port), None

    args = [
        exe,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={user_data_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-background-networking",
        "--disable-sync",
        "--disable-dev-shm-usage",
        "--disable-features=Translate,MediaRouter",
        "--window-size=1280,800",
        "about:blank",
    ]
    if headless:
        args.insert(1, "--headless=new")
        args.insert(2, "--disable-gpu")
        args.insert(3, "--no-sandbox")
    if extra_args:
        args[1:1] = list(extra_args)

    log(f"[browser] launching {os.path.basename(exe)} on port {port}"
        f"{' (headless)' if headless else ''}")
    proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            stdin=subprocess.DEVNULL, start_new_session=True)

    deadline = time.time() + 30
    while time.time() < deadline:
        if _http_ok("127.0.0.1", port):
            ws = _ws_from_devtools("127.0.0.1", port)
            log("[browser] ready")
            return ws, proc
        if proc.poll() is not None:
            raise RuntimeError("browser exited during startup "
                               "(try --headless or a different --port)")
        time.sleep(0.4)
    raise RuntimeError("browser did not expose a debug port in time")


def resolve_cdp(cdp=None, connect=None, port=None, launch=True, headless=None,
                user_data_dir=None, profile=None, log=print):
    """Return a CDP websocket URL, launching a browser if needed."""
    port = port or DEFAULT_PORT

    # 1) explicit websocket URL
    url = cdp or os.environ.get("BU_CDP_WS") or os.environ.get("CDP_WS")
    if _is_ws(url):
        log(f"[browser] using CDP url")
        return url

    # env may hold a bare host:port or an http:// URL
    env_ep = os.environ.get("CDP_URL") or os.environ.get("CDP_ENDPOINT")
    if env_ep and not connect:
        connect = env_ep

    # 2) explicit host:port endpoint
    if connect:
        connect = connect.replace("http://", "").replace("https://", "").rstrip("/")
        if ":" not in connect:
            connect = f"{connect}:{port}"
        host, p = connect.rsplit(":", 1)
        if _http_ok(host, int(p)):
            log(f"[browser] connecting to {host}:{p}")
            return _ws_from_devtools(host, int(p))
        raise RuntimeError(f"no CDP endpoint at {host}:{p}")

    # profile name -> reuse a named user-data-dir (persists logins)
    if profile:
        user_data_dir = os.path.join(_LOCAL_DIR, f"profile-{profile}")

    # 3) already-running browser on the local debug port
    if _http_ok("127.0.0.1", port):
        log(f"[browser] found a browser on 127.0.0.1:{port}")
        return _ws_from_devtools("127.0.0.1", port)

    # 4) auto-launch
    if not launch:
        raise RuntimeError(
            f"no browser found and auto-launch disabled. Start one with "
            f"--remote-debugging-port={port} or pass --cdp/--connect.")
    if headless is None:
        # headless when there is no display (VPS), windowed on a desktop
        headless = _no_display()
    ws, _proc = launch_chrome(port=port, headless=headless,
                              user_data_dir=user_data_dir, log=log)
    return ws


def _no_display():
    if platform.system() in ("Windows", "Darwin"):
        return False
    return not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def attach(cdp=None, **kw):
    return resolve_cdp(cdp=cdp, **kw)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Resolve a CDP endpoint / launch a browser")
    ap.add_argument("--cdp")
    ap.add_argument("--connect")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--no-launch", action="store_true")
    a = ap.parse_args()
    ws = resolve_cdp(cdp=a.cdp, connect=a.connect, port=a.port,
                     launch=not a.no_launch,
                     headless=True if a.headless else None)
    print(ws)
