#!/usr/bin/env python3
"""DOC-03-REC: record the product demo as one clip per shot (Playwright chromium, 1920x1080, real clicks on the
real web app). Pre-run data comes from scripts/demo/prerun.py and dialect_load.py (ids in proof/DOC-03/*.json).

    python3 scripts/demo/record_demo.py [shot ...]      # shots: runs call promote compare dialect audit hubspot github
Outputs: proof/DOC-03/clips/<shot>.webm and clips/timings.json (seconds from clip start of key events).
"""
import hashlib, hmac, json, os, sys, time, uuid
import urllib.request
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "proof/DOC-03/clips"; OUT.mkdir(parents=True, exist_ok=True)
WEB, API = "http://localhost:3000", "http://localhost:8000/api/v1"
PRE = json.loads((ROOT / "proof/DOC-03/prerun.json").read_text())
BUG_RUN, CLEAN_RUN, BUG_CALL = PRE["bug_run"]["run_id"], PRE["clean_run"]["run_id"], PRE["bug_run"]["call_id"]
DIALECT = json.loads((ROOT / "proof/DOC-03/dialect.json").read_text())["report_id"]
REC = os.path.expanduser("~/demo/call.wav")
PHONE = "+919999900077"  # synthetic HubSpot test contact
ENV = dict(l.split("=", 1) for l in (ROOT / ".env").read_text().splitlines() if "=" in l and not l.startswith("#"))
KEY = ENV["PAREEKSHA_API_KEY"]
TIMINGS = OUT / "timings.json"
timings = json.loads(TIMINGS.read_text()) if TIMINGS.exists() else {}


def api(method, path, body=None):
    req = urllib.request.Request(API + path, json.dumps(body).encode() if body is not None else None,
                                 {"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"}, method=method)
    return json.load(urllib.request.urlopen(req))


class Shot:
    """One browser context with video; `t()` is seconds since the clip started."""
    def __init__(self, pw, name, url):
        self.name = name
        self.browser = pw.chromium.launch(executable_path="/opt/pw-browsers/chromium", args=["--no-sandbox"])
        self.ctx = self.browser.new_context(viewport={"width": 1920, "height": 1080}, device_scale_factor=1,
                                            record_video_dir=str(OUT / "_tmp"), record_video_size={"width": 1920, "height": 1080})
        self.page = self.ctx.new_page(); self.t0 = time.time(); self.ev = {}
        self.page.goto(url); self.page.wait_for_timeout(2500)

    def t(self): return round(time.time() - self.t0, 2)
    def mark(self, k): self.ev[k] = self.t()
    def pause(self, s=1.0): self.page.wait_for_timeout(int(s * 1000))

    def click(self, loc, hover=0.9):
        box = loc.first.bounding_box()
        self.page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, steps=35)
        self.pause(hover); loc.first.click(); self.pause(0.8)

    def scroll(self, dy, steps=12):
        for _ in range(steps): self.page.mouse.wheel(0, dy / steps); self.page.wait_for_timeout(80)

    def end(self):
        video = self.page.video; self.ctx.close(); vp = video.path(); self.browser.close()
        Path(vp).replace(OUT / f"{self.name}.webm"); timings[self.name] = {**self.ev, "length": self.t()}
        TIMINGS.write_text(json.dumps(timings, indent=1))


def shot_runs(pw):
    s = Shot(pw, "01_runs", WEB + "/")
    s.click(s.page.get_by_role("link", name="Runs", exact=True)); s.pause(1.5)
    s.click(s.page.get_by_role("link", name="demo-bug-no_amount_confirm").or_(s.page.get_by_text("demo-bug-no_amount_confirm")))
    s.pause(2.5); s.mark("heatmap")
    s.click(s.page.locator("[role=grid] a[href^='/calls/']"), hover=1.5)
    s.page.wait_for_url("**/calls/**"); s.pause(3); s.end()


def shot_call(pw):
    s = Shot(pw, "02_call", f"{WEB}/calls/{BUG_CALL}")
    s.pause(1.5)
    s.click(s.page.get_by_role("button", name="Evidence 3").or_(s.page.get_by_text("Evidence 3")), hover=1.2)
    s.pause(1.5)
    s.click(s.page.locator("button[aria-label^='Seek to turn 6']"), hover=1.2)
    s.pause(1.5); s.mark("play")
    s.click(s.page.locator("button[aria-label='Play']"), hover=1.0)
    s.pause(6); s.mark("play_end"); s.end()


def shot_promote(pw):
    s = Shot(pw, "03_promote", f"{WEB}/calls/{BUG_CALL}")
    s.pause(1.0)
    s.click(s.page.get_by_role("button", name="Promote to regression"), hover=1.2)
    s.pause(2.0)
    s.click(s.page.locator("dialog[open] button", has_text="Promote to regression"), hover=1.2)
    s.pause(2.5); s.mark("toast")
    s.click(s.page.locator("dialog[open] button", has_text="Close"), hover=0.8)
    s.click(s.page.get_by_role("link", name="Regression", exact=True)); s.pause(3); s.end()


def shot_compare(pw):
    s = Shot(pw, "04_compare", f"{WEB}/runs/{CLEAN_RUN}")
    s.pause(2.0)
    s.click(s.page.get_by_role("link", name="Compare"), hover=1.2); s.pause(2.5)
    s.page.get_by_label("Base run").select_option(BUG_RUN); s.pause(1.5)
    s.page.get_by_label("Head run").select_option(CLEAN_RUN); s.pause(1.5)
    s.click(s.page.get_by_role("button", name="Compare"), hover=1.0); s.pause(3.5)
    s.mark("diff"); s.scroll(500); s.pause(2.5); s.end()


def shot_dialect(pw):
    s = Shot(pw, "05_dialect", WEB + "/")
    s.click(s.page.get_by_role("link", name="Dialect", exact=True)); s.pause(1.5)
    s.click(s.page.get_by_text("Report 3b5f0df0")); s.pause(3.0)
    s.scroll(500); s.pause(3.0); s.end()


def shot_audit(pw):
    s = Shot(pw, "06_audit", WEB + "/")
    s.click(s.page.get_by_role("link", name="Audits", exact=True)); s.pause(1.5)
    s.click(s.page.get_by_role("link", name="Upload").or_(s.page.get_by_text("Upload recording")))
    s.pause(1.5)
    s.page.locator("input[type=file]").set_input_files(REC); s.pause(1.0)
    sel = s.page.get_by_label("Agent")
    sel.select_option(label="EMI Reminder Bot"); s.pause(0.8)
    for l in s.page.get_by_role("checkbox").all():
        pass
    s.page.get_by_label("kn-IN").uncheck() if s.page.get_by_label("kn-IN").count() else None
    s.page.get_by_label("hi-IN").check(); s.pause(0.8)
    s.page.get_by_label("Stereo channels are speakers").check(); s.pause(0.8)
    s.page.get_by_label("Confirm").check() if s.page.get_by_label("Confirm").count() else s.page.locator("input[type=checkbox]").last.check()
    s.pause(1.0)
    btn = s.page.get_by_role("button", name="Upload").or_(s.page.get_by_role("button", name="Submit"))
    s.click(btn, hover=1.2); s.mark("submitted")
    s.page.wait_for_url("**/calls/**"); s.pause(2); s.mark("waiting")
    cid = s.page.url.rsplit("/", 1)[-1].split("?")[0]; s.ev["call_id"] = cid
    while api("GET", f"/calls/{cid}")["status"] not in ("completed", "failed"): s.pause(5)
    s.page.reload(); s.page.get_by_text("Overall score", exact=False).first.wait_for(timeout=30000); s.mark("done")
    s.pause(3); s.scroll(500); s.pause(3); s.end()


def hubspot_setup():
    """Real HubSpot integration + one signed webhook delivery of the same recording with the synthetic phone."""
    agent = next(a for a in api("GET", "/agents?limit=100")["items"] if a["name"] == "EMI Reminder Bot")
    secret = uuid.uuid4().hex
    inb = api("POST", "/integrations", {"connector": "webhook", "name": "demo-inbound",
        "config": {"url": "https://example.com/sink", "events": ["evaluation.completed"], "default_agent_id": agent["id"]},
        "secrets": {"signing_secret": secret}})
    hub = api("POST", "/integrations", {"connector": "hubspot", "name": "HubSpot (demo)",
        "config": {"match_by": "phone", "only_failed": False}, "secrets": {"private_app_token": os.environ["HUBSPOT_ACCESS_TOKEN"]}})
    # recording served over the local web host is private; use a public-less local https? -> see recording.md
    return agent, inb, hub


if __name__ == "__main__":
    shots = {"runs": shot_runs, "call": shot_call, "promote": shot_promote, "compare": shot_compare,
             "dialect": shot_dialect, "audit": shot_audit}
    want = sys.argv[1:] or list(shots)
    with sync_playwright() as pw:
        for n in want: shots[n](pw); print("recorded", n, flush=True)
