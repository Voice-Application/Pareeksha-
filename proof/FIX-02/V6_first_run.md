# V6: Duplicate delivery and worker crash give one evaluation and one CRM note

Run at 2026-10-27T19:17:37Z on commit edf6aa9

local HTTPS webhook sink: https://host.docker.internal:18443 (pid 25017, log kept in this step's evidence below)
```
.........                                                                [100%]
9 passed in 61.83s (0:01:01)
```
```
{'integration': 'f16282c6-930c-4d76-89cd-aeca9a7e163d', 'test': {'ok': False, 'detail': "transport error: ConnectError('[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: self-signed certificate (_ssl.c:1011)')"}}
```
```
{'run_id': '7af28341-5efb-4ca0-b231-13bf7050fa9e', 'wall_s': 120.2, 'items': ['evaluated']}
```
sink hits before replay: 1
```
re-published the original evaluation.completed 2 time(s)
```
sink log lines (all): 1
```
{"t": 1793128942.44821, "path": "/hook", "headers": {"Host": "host.docker.internal:18443", "Accept": "*/*", "Accept-Encoding": "gzip, deflate", "Connection": "keep-alive", "User-Agent": "python-httpx/0.28.1", "Content-Type": "application/json", "X-Pareeksha-Event-Id": "b24043e7-3e96-5160-80cb-1d4798ddefef", "X-Pareeksha-Timestamp": "1793128942", "X-Pareeksha-Signature": "v1=70bdf0613f783a2176969b5872c309afc9dffb10a970a1c67c190f5d648b1359", "Content-Length": "1551"}, "body": {"data": {"agent": {"id": "767eac68-4d7e-41d4-b996-40981ae4e30d", "name": "EMI Reminder Bot"}, "call_id": "f2e5a5a8-21c7-5277-86df-e0f69b3754ad", "critical_failure": false, "duration_ms": 111557, "external_id": null, "failure_types": [], "language": "kn-IN", "link": "http://localhost:3000/calls/f2e5a5a8-21c7-5277-86df-e0f69b3754ad", "metadata": {"barge_in_attempts": "[{'cancelled': False, 'started_ms': 7276, 'scheduled_ms': 5133, 'planned_offset_ms': 1533, 'agent_speech_start_ms': 3600, 'agent_speaking_at_start': True}, {'cancelled': True, 'started_ms': None, 'scheduled_ms': 99746, 'planned_offset_ms': 1307, 'agent_speech_start_ms': 98439, 'agent_speaking_at_start': None}]", "glass_box": "True", "noise_profile_id": "9fefddcd-7b48-4159-a001-21e8e2e17850", "persona_id": "fc119b9d-3786-4f20-b27b-9d9e980e95d9", "run_id": "7af28341-5efb-4ca0-b231-13bf7050fa9e", "scenario_id": "cadd8035-6838-45e8-a324-9b4e73aca7bc", "seed": "447309011160298238"}, "overall_score": 95.0, "passed": true, "persona": "Kiran — IT em```
webhook sink receiver hits for this call: 1
call f2e5a5a8-21c7-5277-86df-e0f69b3754ad: evaluations before/after = 1/1; deliveries before=1; duplicate delivery keys=0; duplicate CRM note ids=0

STATUS: PASS
REASON: one evaluation, no duplicate delivery after replay x2 and SIGKILL
