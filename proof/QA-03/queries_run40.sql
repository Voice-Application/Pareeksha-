select status, count(*) from run_items where run_id='8422cb13-0f26-4afa-98ef-77a7abb5ea70' group by 1 order by 1;
select ri.status item_status, c.status call_status, c.end_reason, left(coalesce(c.error,''),120) err, e.status eval_status from run_items ri left join calls c on c.run_item_id=ri.id left join evaluations e on e.call_id=c.id where ri.run_id='8422cb13-0f26-4afa-98ef-77a7abb5ea70' and (ri.status<>'evaluated' or e.status<>'ok' or c.status='error');
select count(*) calls_total, count(*) filter (where c.status='error') calls_error, count(*) filter (where c.status<>'error') calls_ok from run_items ri join calls c on c.run_item_id=ri.id where ri.run_id='8422cb13-0f26-4afa-98ef-77a7abb5ea70';
select count(*) dead_letters from dead_letters;
select consumer, count(*) from processed_events group by 1 order by 1;
select count(*) unpublished_outbox from outbox where published_at is null;
select status, active_calls, started_at, finished_at, finished_at-started_at wall from test_runs where id='8422cb13-0f26-4afa-98ef-77a7abb5ea70';
