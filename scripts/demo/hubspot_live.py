#!/usr/bin/env python3
"""DOC-03-REC: real HubSpot integration (match_by phone) + one signed webhook delivery of the synthetic recording
for the synthetic test contact; waits for the delivery row. Writes proof/DOC-03/hubspot.json."""
import hashlib, hmac, json, os, sys, time, urllib.request, uuid
sys.path.insert(0, "scripts/verify"); import vapi
URL = "https://raw.githubusercontent.com/Voice-Application/Pareeksha-/task/DOC-03-REC/proof/DOC-03/demo_call.wav"
PHONE = "+919999900077"
agent = next(a for a in vapi.items("/agents") if a["name"] == "EMI Reminder Bot")
secret = uuid.uuid4().hex
inb = vapi.request("POST", "/integrations", {"connector": "webhook", "name": "demo-inbound",
    "config": {"url": "https://example.com/sink", "events": ["evaluation.completed"], "default_agent_id": agent["id"]},
    "secrets": {"signing_secret": secret}})
hub = vapi.request("POST", "/integrations", {"connector": "hubspot", "name": "HubSpot (demo)",
    "config": {"match_by": "phone", "only_failed": False}, "secrets": {"private_app_token": os.environ["HUBSPOT_ACCESS_TOKEN"]}})
body = json.dumps({"external_id": f"demo-{uuid.uuid4().hex[:8]}", "recording_url": URL, "agent_name": agent["name"],
                   "language": "hi-IN", "metadata": {"phone": PHONE}}).encode()
ts = str(int(time.time()))
sig = hmac.new(inb["signing_secret"].encode(), ts.encode() + b"." + body, hashlib.sha256).hexdigest()
req = urllib.request.Request(inb["inbound_url"], body, {"Content-Type": "application/json", "X-Pareeksha-Timestamp": ts, "X-Pareeksha-Signature": f"v1={sig}"})
posted = time.time(); call_id = json.load(urllib.request.urlopen(req))["call_id"]; print("call", call_id, flush=True)
note = None
while time.time() - posted < 600 and not note:
    time.sleep(5)
    for d in vapi.request("GET", f"/integrations/{hub['id']}/deliveries?limit=20")["items"]:
        print(d.get("status"), d.get("external_id"), flush=True)
        if d.get("status") == "succeeded" and d.get("external_id"): note = d["external_id"]
out = {"call_id": call_id, "hubspot_integration_id": hub["id"], "webhook_integration_id": inb["id"], "note_id": note, "seconds_to_note": round(time.time() - posted, 1) if note else None}
json.dump(out, open("proof/DOC-03/hubspot.json", "w"), indent=1); print(out)
