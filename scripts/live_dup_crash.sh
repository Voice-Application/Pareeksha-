#!/usr/bin/env bash
# LIVE-ACCEPT (GOAL item 6, live): re-publish one real evaluation.completed twice, SIGKILL the integrations worker,
# then count the HubSpot notes on the test contact through the HubSpot API. Args: call_id contact_id.
# Env: HUBSPOT_ACCESS_TOKEN, COMPOSE (docker compose command), PAREEKSHA_API_URL/KEY.
cd "$(dirname "$0")/.." && source scripts/verify/lib.sh
call_id=$1; contact=$2
notes() { curl -s "https://api.hubapi.com/crm/v4/objects/contacts/$contact/associations/notes" -H "Authorization: Bearer $HUBSPOT_ACCESS_TOKEN" | $PY -c 'import json,sys; r=json.load(sys.stdin)["results"]; print(len(r), sorted(x["toObjectId"] for x in r))'; }
echo "notes on contact before: $(notes)"
$COMPOSE exec -T api python - "$call_id" <<'PYEOF'
import asyncio, json, sys
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from pareeksha.events.settings import EventSettings
from pareeksha.events.topics import Topics
async def main(call_id):
    s = EventSettings.from_env()
    cons = AIOKafkaConsumer(Topics.EVALUATION_COMPLETED.value, bootstrap_servers=s.bootstrap_servers, group_id=None,
                            auto_offset_reset="earliest", enable_auto_commit=False, consumer_timeout_ms=15000)
    await cons.start(); prod = AIOKafkaProducer(bootstrap_servers=s.bootstrap_servers); await prod.start()
    sent = 0
    try:
        async for m in cons:
            if json.loads(m.value)["payload"].get("call_id") == call_id:
                for _ in range(2):
                    await prod.send_and_wait(m.topic, m.value, key=m.key, headers=m.headers); sent += 1
                break
    finally:
        await cons.stop(); await prod.stop()
    print(f"re-published the original evaluation.completed {sent} time(s)")
asyncio.run(main(sys.argv[1]))
PYEOF
$COMPOSE kill -s KILL integrations >/dev/null 2>&1; echo "integrations worker SIGKILLed at $(date -u +%T)"
$COMPOSE up -d integrations >/dev/null 2>&1; echo "integrations worker restarted"
sleep 60
echo "notes on contact after: $(notes)"
echo "evaluations for call: $(psql_q "SELECT count(*) FROM evaluations WHERE call_id='$call_id'")"
echo "deliveries (integration,event,status,external_id) for call's event:"
psql_q "SELECT integration_id, direction, status, external_id, attempts FROM integration_deliveries ORDER BY created_at" 2>&1 | tail -8
