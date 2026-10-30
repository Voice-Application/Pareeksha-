# V6: Duplicate delivery and worker crash give one evaluation and one CRM note

Run at 2026-10-30T16:40:26Z on commit 6ebe99b

local HTTPS webhook sink: https://host.docker.internal:18443 (pid 12057, log kept in this step's evidence below)
pytest interpreter: /home/user/Pareeksha-/.venv-verify/bin/python (Python 3.12.3)
```
.........                                                                [100%]
=============================== warnings summary ===============================
pareeksha/audio/dsp.py:8
  /home/user/Pareeksha-/backend/pareeksha/audio/dsp.py:8: DeprecationWarning: 'audioop' is deprecated and slated for removal in Python 3.13
    import audioop  # stdlib <= 3.12; audioop-lts on >= 3.13 (see requirements.txt)

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
9 passed, 1 warning in 62.70s (0:01:02)
```
```
{'integration': 'b954f598-f932-47b9-8eab-74cf5f6f93d0', 'test': {'ok': True, 'detail': 'HTTP 200'}}
```
```
{'run_id': 'f5feb121-d671-4c1a-9d05-a5fdb967309f', 'wall_s': 60.2, 'items': ['evaluated']}
```
sink hits before replay: 1
```
re-published the original evaluation.completed 2 time(s)
```
sink log lines (all): 2
```
{"t": 1793378589.920015, "path": "/hook/1793378589", "headers": {"Host": "host.docker.internal:18443", "Accept": "*/*", "Accept-Encoding": "gzip, deflate", "Connection": "keep-alive", "User-Agent": "python-httpx/0.28.1", "Content-Type": "application/json", "X-Pareeksha-Timestamp": "1793378589", "X-Pareeksha-Signature": "v1=7feb41aff96e52d0a0088788431f012cf8d3cdf2c9fe278fbe831ad594f057b9", "Content-Length": "16"}, "body": {"type": "ping"}}
{"t": 1793378642.8922365, "path": "/hook/1793378589", "headers": {"Host": "host.docker.internal:18443", "Accept": "*/*", "Accept-Encoding": "gzip, deflate", "Connection": "keep-alive", "User-Agent": "python-httpx/0.28.1", "Content-Type": "application/json", "X-Pareeksha-Event-Id": "36cafb22-2ee5-5c9f-8cec-67cc296a80cb", "X-Pareeksha-Timestamp": "1793378642", "X-Pareeksha-Signature": "v1=4cbb47b746dbdc301482905a41088f84a8c998420d5a6fc7b6ce71a90c516e99", "Content-Length": "1941"}, "body": {"data": {"agent": {"id": "4ecbeba2-f6fc-4d92-8ecd-6c84eb456dad", "name": "EMI Reminder Bot"}, "call_id": "ee6356c4-528f-5dba-a2d7-3067126f9938", "critical_failure": false, "duration_ms": 47169, "external_id": null, "failure_types": ["intent_miss"], "language": "kn-IN", "link": "http://localhost:3000/calls/ee6356c4-528f-5dba-a2d7-3067126f9938", "metadata": {"barge_in_attempts": "[{'cancelled': True, 'started_ms': None, 'scheduled_ms': 9304, 'planned_offset_ms': 807, 'agent_speech_start_ms': 8497, 'agent_speaking_at_start': None}]", "glass_box": "True", "noise```
webhook sink receiver hits for this call: 1
call ee6356c4-528f-5dba-a2d7-3067126f9938: evaluations before/after = 1/1; deliveries before=1; duplicate delivery keys=0; duplicate CRM note ids=0

STATUS: PASS
REASON: one evaluation, no duplicate delivery after replay x2 and SIGKILL
