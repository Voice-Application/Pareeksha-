\echo '== run'
select id, name, status, active_calls, config->>'max_concurrency' as cap, started_at, finished_at, finished_at-started_at as took from test_runs;
\echo '== items'
select status, count(*) from run_items group by 1;
\echo '== calls (one per item)'
select c.id as call_id, c.run_item_id, c.end_reason, c.status, c.duration_ms, (select count(*) from turns t where t.call_id=c.id) as turns, (select count(*) from tool_calls t where t.call_id=c.id) as tools, c.recording_mixed is not null as has_audio from calls c order by c.started_at;
\echo '== evaluations'
select e.call_id, e.status, e.overall_score, e.passed, e.critical_failure, e.needs_human_review, e.judge_model from evaluations e order by e.created_at;
\echo '== usage by provider/operation'
select provider, operation, unit_type, count(*) as rows, round(sum(units)::numeric,1) as units from api_usage group by 1,2,3 order by 1,2;
\echo '== processed_events per consumer group'
select consumer_group, count(*) from processed_events group by 1 order by 1;
\echo '== dead letters'
select count(*) as dead_letters from dead_letters;
\echo '== outbox'
select count(*) filter (where published_at is null) as unpublished, count(*) as total from outbox_events;
