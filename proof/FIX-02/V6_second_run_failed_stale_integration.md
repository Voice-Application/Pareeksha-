# V6: Duplicate delivery and worker crash give one evaluation and one CRM note

Run at 2026-10-27T19:25:10Z on commit edf6aa9

local HTTPS webhook sink: https://host.docker.internal:18443 (pid 30555, log kept in this step's evidence below)
```
.........                                                                [100%]
9 passed in 61.91s (0:01:01)
```
```
{'integration': 'e7cd9c72-7512-483d-b358-23487e3ef858', 'test': {'ok': True, 'detail': 'HTTP 200'}}
```
```
{'run_id': 'fdfff6bc-a94a-44a7-a95d-5e02f9262c07', 'wall_s': 150.3, 'items': ['evaluated']}
```
sink hits before replay: 2
```
re-published the original evaluation.completed 2 time(s)
```
sink log lines (all): 3
```
{"t": 1793129283.000034, "path": "/hook", "headers": {"Host": "host.docker.internal:18443", "Accept": "*/*", "Accept-Encoding": "gzip, deflate", "Connection": "keep-alive", "User-Agent": "python-httpx/0.28.1", "Content-Type": "application/json", "X-Pareeksha-Timestamp": "1793129282", "X-Pareeksha-Signature": "v1=5168112d47ccc215a46fde968607784058965cd469f34d1d73a39181ab05b58c", "Content-Length": "16"}, "body": {"type": "ping"}}
{"t": 1793129428.5002525, "path": "/hook", "headers": {"Host": "host.docker.internal:18443", "Accept": "*/*", "Accept-Encoding": "gzip, deflate", "Connection": "keep-alive", "User-Agent": "python-httpx/0.28.1", "Content-Type": "application/json", "X-Pareeksha-Event-Id": "6acbd09d-b5b3-5a2b-b4ca-4524bf4b9e85", "X-Pareeksha-Timestamp": "1793129428", "X-Pareeksha-Signature": "v1=bc44df4573ccf378bc0a9806a74b1fdd6fca860d57b122642ff58852be711e73", "Content-Length": "1516"}, "body": {"data": {"agent": {"id": "767eac68-4d7e-41d4-b996-40981ae4e30d", "name": "EMI Reminder Bot"}, "call_id": "7a8135cf-d65c-5f51-bb0d-cbdd05c09932", "critical_failure": false, "duration_ms": 139816, "external_id": null, "failure_types": [], "language": "kn-IN", "link": "http://localhost:3000/calls/7a8135cf-d65c-5f51-bb0d-cbdd05c09932", "metadata": {"barge_in_attempts": "[{'cancelled': False, 'started_ms': 4778, 'scheduled_ms': 2036, 'planned_offset_ms': 1533, 'agent_speech_start_ms': 503, 'agent_speaking_at_start': True}, {'cancelled': False, 'started_ms': 71958, 'scheduled_ms': 6810```
webhook sink receiver hits for this call: 2
call 7a8135cf-d65c-5f51-bb0d-cbdd05c09932: evaluations before/after = 1/1; deliveries before=3; duplicate delivery keys=0; duplicate CRM note ids=0

STATUS: FAIL
REASON: evaluations=1 duplicate deliveries=0 duplicate notes=0
