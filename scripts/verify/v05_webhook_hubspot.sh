#!/usr/bin/env bash
# V5 (FR-IN-7, FR-IN-8, NFR-15): a signed webhook delivers a consented REAL recording; it is audited and a HubSpot
# note exists within 3 minutes of the POST. Needs owner inputs (reported PENDING when absent):
#   HUBSPOT_TOKEN          private-app token (crm.objects.contacts.read/write)
#   VERIFY_RECORDING_URL   public https URL of a consented real recording (WAV/MP3, < 10 MB)
#   VERIFY_CONTACT_PHONE   phone number of a HubSpot contact you created for this test
#   VERIFY_RECORDING_LANGUAGE  optional BCP-47 language of the recording (default kn-IN)
#   (HUBSPOT_ACCESS_TOKEN is accepted as an alias of HUBSPOT_TOKEN)
# Not exercised here: the HubSpot screenshot (take it of the contact's activity feed and add it to proof/QA-05/).
cd "$(dirname "$0")/../.." && source scripts/verify/lib.sh
begin 5 "Webhook-imported real recording audited, HubSpot note within 3 min"
token=${HUBSPOT_TOKEN:-${HUBSPOT_ACCESS_TOKEN:-$(grep -E '^HUBSPOT_TOKEN=' .env 2>/dev/null | cut -d= -f2)}}
url=${VERIFY_RECORDING_URL:-}; phone=${VERIFY_CONTACT_PHONE:-}
missing=()
[ -n "$token" ] || missing+=(HUBSPOT_TOKEN); [ -n "$url" ] || missing+=(VERIFY_RECORDING_URL); [ -n "$phone" ] || missing+=(VERIFY_CONTACT_PHONE)
if [ ${#missing[@]} -gt 0 ]; then
  note "Not run: missing owner inputs: ${missing[*]}. Nothing was faked."
  finish PENDING "needs ${missing[*]} (HubSpot token, a consented real recording URL and a test contact)"
fi

out=$($PY - "$url" "$phone" "$token" <<'PYEOF'
import hashlib, hmac, json, os, sys, time, urllib.request, uuid
sys.path.insert(0, "scripts/verify")
import vapi
rec, phone, token = sys.argv[1:4]
agent = next(a for a in vapi.items("/agents") if a["name"] == "EMI Reminder Bot")
secret = uuid.uuid4().hex
integ = vapi.request("POST", "/integrations", {"connector": "webhook", "name": f"verify-inbound-{int(time.time())}",
    "config": {"url": "https://example.com/sink", "events": ["evaluation.completed"], "default_agent_id": agent["id"]},
    "secrets": {"signing_secret": secret}})
hub = vapi.request("POST", "/integrations", {"connector": "hubspot", "name": f"verify-hubspot-{int(time.time())}",
    "config": {"match_by": "phone", "only_failed": False}, "secrets": {"private_app_token": token}})
body = json.dumps({"external_id": f"verify-{uuid.uuid4().hex[:8]}", "recording_url": rec, "agent_name": agent["name"],
                   "language": os.environ.get("VERIFY_RECORDING_LANGUAGE", "kn-IN"), "metadata": {"phone": phone}}).encode()
ts = str(int(time.time()))
sig = hmac.new(integ["signing_secret"].encode(), ts.encode() + b"." + body, hashlib.sha256).hexdigest()
req = urllib.request.Request(integ["inbound_url"], body, {"Content-Type": "application/json",
    "X-Pareeksha-Timestamp": ts, "X-Pareeksha-Signature": f"v1={sig}"})
posted = time.time()
call_id = json.load(urllib.request.urlopen(req))["call_id"]
note_id = None
while time.time() - posted < 600 and not note_id:
    time.sleep(5)
    for d in vapi.request("GET", f"/integrations/{hub['id']}/deliveries?limit=20")["items"]:
        if d.get("status") == "succeeded" and d.get("external_id"):
            note_id, noted = d["external_id"], time.time()
print(json.dumps({"call_id": call_id, "note_id": note_id, "posted_at": posted,
                  "seconds_to_note": round(noted - posted, 1) if note_id else None}))
PYEOF
)
echo "$out" | block
secs=$(echo "$out" | $PY -c 'import json,sys; v=json.load(sys.stdin)["seconds_to_note"]; print(v if v is not None else 99999)' 2>/dev/null || echo 99999)
awk "BEGIN{exit !($secs < 180)}" && finish PASS "HubSpot note created ${secs}s after the signed POST" 
finish FAIL "no HubSpot note within 180 s (took ${secs}s)"
