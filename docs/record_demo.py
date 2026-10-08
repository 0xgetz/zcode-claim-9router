#!/usr/bin/env python3
"""Record a demo video of the ZCode Console.

Strategy: drive a scripted walkthrough of the UI and grab a screenshot frame
after every small step (Page.captureScreenshot), then encode the frames to MP4.
This is deterministic and does not depend on screencast timing.
"""

import asyncio, json, base64, os, io, subprocess
import websockets
from PIL import Image
import imageio_ffmpeg

WS = "wss://8d8c898d-9035-49fb-8409-d572a81423df.cdp.browser-use.com/devtools/browser/606a5997-93fa-422d-ac7b-3e7d94ce42bc"
OUTDIR = "docs"
W, H = 1280, 720
FPS = 15


class C:
    def __init__(self, ws):
        self.ws = ws; self.i = 0; self.pending = {}; self.sid = None

    async def recv_loop(self):
        async for raw in self.ws:
            m = json.loads(raw)
            if "id" in m and m["id"] in self.pending:
                f = self.pending.pop(m["id"])
                if not f.done(): f.set_result(m)

    async def cmd(self, method, params=None, sid=None):
        self.i += 1; mid = self.i
        d = {"id": mid, "method": method, "params": params or {}}
        if sid: d["sessionId"] = sid
        f = asyncio.get_event_loop().create_future(); self.pending[mid] = f
        await self.ws.send(json.dumps(d))
        return await asyncio.wait_for(f, timeout=60)


class Rec:
    def __init__(self, c): self.c = c; self.frames = []

    async def ev(self, expr):
        r = await self.c.cmd("Runtime.evaluate",
                             {"expression": expr, "returnByValue": True}, self.c.sid)
        return r.get("result", {}).get("result", {}).get("value")

    async def frame(self, n=1, gap=1 / FPS):
        for _ in range(n):
            r = await self.c.cmd("Page.captureScreenshot",
                                 {"format": "jpeg", "quality": 80}, self.c.sid)
            self.frames.append(base64.b64decode(r["result"]["data"]))
            await asyncio.sleep(gap)

    async def hold(self, sec):
        await self.frame(max(1, int(sec * FPS)))

    async def scroll_to(self, y, sec=0.8):
        cur = await self.ev("window.scrollY") or 0
        n = max(1, int(sec * FPS))
        for k in range(1, n + 1):
            yy = int(cur + (y - cur) * k / n)
            await self.ev(f"window.scrollTo(0,{yy})")
            await self.frame(1, 1 / FPS)

    async def click_page(self, name):
        await self.ev(f"document.querySelector('nav button[data-page={name}]').click()")


async def main():
    async with websockets.connect(WS, max_size=256 * 1024 * 1024) as ws:
        c = C(ws); asyncio.create_task(c.recv_loop())
        t = await c.cmd("Target.getTargets")
        tid = [x["targetId"] for x in t["result"]["targetInfos"]
               if x["type"] == "page" and "usercontent" in x["url"]][0]
        a = await c.cmd("Target.attachToTarget", {"targetId": tid, "flatten": True})
        c.sid = a["result"]["sessionId"]
        await c.cmd("Page.enable", {}, c.sid)
        await c.cmd("Runtime.enable", {}, c.sid)

        rec = Rec(c)

        # seed demo state
        await rec.ev("""(()=>{
          document.getElementById('token').value='eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.demo.token';
          document.getElementById('cookies').value='session=abc123; token=eyJ...';
          document.getElementById('email').value='dev@zai-account.io';
          document.getElementById('param').value='eyJjZXJ0aWZ5SWQiOiJkZW1vIiwic2NlbmVJZCI6IjExeHlndHZkIiwiaXNTaWduIjp0cnVlfQ==';
          document.getElementById('base').value='http://localhost:20128';
        })()""")

        # scene 1 — dashboard
        await rec.click_page("dashboard")
        await rec.ev("window.scrollTo(0,0)")
        await rec.hold(1.8)
        await rec.scroll_to(380, 0.9)
        await rec.hold(1.2)
        await rec.scroll_to(0, 0.8)
        await rec.hold(1.0)

        # scene 2 — accounts: add + import
        await rec.click_page("accounts")
        await rec.ev("window.scrollTo(0,0)")
        await rec.hold(1.4)
        await rec.ev("document.getElementById('acc-email').value='batch1@zai-account.io'; document.getElementById('acc-token').value='eyJhbGciOiJIUzI1NiJ9.batch1.token'; addAccount()")
        await rec.hold(1.8)
        await rec.ev("document.getElementById('import-text').value='teammate@zai.io,eyJhbGciOiJIUzI1NiJ9.import1.token\\nsecond@zai.io,password123'; importAccounts()")
        await rec.hold(2.0)
        await rec.scroll_to(520, 0.9)
        await rec.hold(1.6)

        # scene 3 — capture / upload
        await rec.click_page("capture")
        await rec.ev("window.scrollTo(0,0)")
        await rec.hold(1.4)
        await rec.ev("document.getElementById('cap-param').value=document.getElementById('param').value")
        await rec.hold(1.4)

        # scene 4 — results
        await rec.click_page("results")
        await rec.ev("refreshResults()")
        await rec.ev("window.scrollTo(0,0)")
        await rec.hold(2.0)
        await rec.scroll_to(320, 0.8)
        await rec.hold(1.4)
        await rec.scroll_to(0, 0.6)
        await rec.hold(1.0)

        print("frames:", len(rec.frames), flush=True)

        # encode: normalize every frame to WxH on a dark canvas
        import shutil
        tmp = "/tmp/bcode/vframes"; shutil.rmtree(tmp, ignore_errors=True); os.makedirs(tmp)
        for i, fb in enumerate(rec.frames):
            im = Image.open(io.BytesIO(fb)).convert("RGB")
            if im.size != (W, H):
                canvas = Image.new("RGB", (W, H), (11, 13, 18))
                im = im.resize((W, min(H, int(im.height * W / im.width))), Image.LANCZOS)
                canvas.paste(im, (0, 0))
                im = canvas
            im.save(f"{tmp}/f{i:05d}.jpg", quality=88)
        ff = imageio_ffmpeg.get_ffmpeg_exe()
        out = f"{OUTDIR}/demo.mp4"
        subprocess.run([ff, "-y", "-framerate", str(FPS), "-i", f"{tmp}/f%05d.jpg",
                        "-c:v", "libx264", "-preset", "medium", "-crf", "23",
                        "-pix_fmt", "yuv420p", "-movflags", "+faststart", out],
                       check=True, capture_output=True)
        print("wrote", out, os.path.getsize(out) // 1024, "KB", flush=True)


asyncio.run(main())
