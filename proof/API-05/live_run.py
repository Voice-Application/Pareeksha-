"""API-05 acceptance run on real infrastructure.

Real Kafka, real Postgres (Alembic-migrated), the real API over HTTP (uvicorn), the real outbox
relay and the real `generator` consumer with **real DeepSeek**. Evaluated calls are seeded straight
into the tables (the simulator / evaluator workers belong to other tasks); everything API-05 owns
runs for real:

  1. scenario generation: POST -> outbox -> Kafka -> generator -> DeepSeek -> poll the draft
  2. promote a failed call -> promoted scenario + regression test, linked to the call
  3. POST /runs:regression -> run row + `run.requested` read back from the Kafka topic
  4. suite verdict (finalizer's summarize_run over the run's items from the database)
  5. human reviews + GET /calibration

    INFRA_TEST_KAFKA_BOOTSTRAP=localhost:19094 PG=postgresql://pareeksha:pareeksha@localhost:5432 \
        python3 proof/API-05/live_run.py
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx
import psycopg
from alembic import command
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.pool import NullPool

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from pareeksha.db.session import make_engine  # noqa: E402
from pareeksha.evaluation.handlers import RunState, summarize_run  # noqa: E402
from pareeksha.regression.outcomes import run_outcomes  # noqa: E402
from pareeksha.schemas.scenarios import ScenarioCreate  # noqa: E402
from tests.conftest import alembic_config, new_tenant  # noqa: E402
from tests.integration.domain import (  # noqa: E402
    build_world,
    dimensions,
    make_call,
    make_run,
)
from tests.integration.support import read_topic, wait_for  # noqa: E402
from pareeksha.events.topics import Topics  # noqa: E402

KAFKA = os.environ.get("INFRA_TEST_KAFKA_BOOTSTRAP", "localhost:19094")
PG = os.environ.get("PG", "postgresql://pareeksha:pareeksha@localhost:5432")
DB = "pareeksha_api05"
PORT = 18006
MIX = {"happy_path": 3, "edge_case": 4, "adversarial": 3}


def spawn(*cmd: str, log: str) -> subprocess.Popen[bytes]:
    env = {
        **os.environ,
        "KAFKA_BOOTSTRAP_SERVERS": KAFKA,
        "DATABASE_URL": f"postgresql+psycopg://{PG.split('://', 1)[1]}/{DB}",
        "PYTHONPATH": str(ROOT / "backend"),
    }
    return subprocess.Popen(cmd, env=env, stdout=(HERE / log).open("wb"), stderr=subprocess.STDOUT)


async def main() -> None:
    with psycopg.connect(f"{PG}/postgres", autocommit=True) as c:
        c.execute(f'DROP DATABASE IF EXISTS "{DB}" WITH (FORCE)')
        c.execute(f'CREATE DATABASE "{DB}"')
    url = f"postgresql+psycopg://{PG.split('://', 1)[1]}/{DB}"
    command.upgrade(alembic_config(url), "head")
    engine = make_engine(url, poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    tenant = await new_tenant(factory)

    procs = [
        spawn(sys.executable, "-m", "uvicorn", "pareeksha.api.main:app", "--port", str(PORT),
              log="api.log"),
        spawn(sys.executable, "-m", "pareeksha.workers.outbox_relay", log="outbox_relay.log"),
        spawn(sys.executable, "-m", "pareeksha.workers.generator", log="generator_worker.log"),
    ]
    out: dict[str, Any] = {}
    try:
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{PORT}", timeout=60) as api:
            for _ in range(60):
                try:
                    if (await api.get("/health")).status_code in (200, 503):
                        break
                except httpx.HTTPError:
                    await asyncio.sleep(1)
            world = await build_world(api, tenant)
            auth = tenant.admin
            read = tenant.read

            # 1. scenario generation (real DeepSeek) -----------------------------------------
            t0 = time.time()
            r = await api.post(f"/api/v1/agents/{world.agent_id}/scenarios:generate",
                               json={"count": 10, "mix": MIX}, headers=auth)
            r.raise_for_status()
            draft_id = r.json()["draft_id"]
            while True:
                draft = (await api.get(f"/api/v1/scenario-drafts/{draft_id}", headers=read)).json()
                if draft["status"] != "pending":
                    break
                if time.time() - t0 > 240:
                    raise SystemExit("generation timed out")
                await asyncio.sleep(2)
            out["generation"] = {
                "status": draft["status"], "error": draft["error"], "seconds": round(time.time() - t0),
                "count": len(draft["drafts"]),
            }
            valid = [ScenarioCreate.model_validate(d) for d in draft["drafts"]]
            kinds = [next(t for t in s.tags if t in MIX) for s in valid]
            out["generation"]["schema_valid"] = len(valid)
            out["generation"]["mix"] = {k: kinds.count(k) for k in MIX}
            out["generation"]["titles"] = [s.title for s in valid]
            (HERE / "scenario_drafts.json").write_text(
                json.dumps(draft, indent=2, ensure_ascii=False))
            print("generation:", json.dumps({k: v for k, v in out["generation"].items()
                                              if k != "titles"}))

            # 2. promote a failed call -----------------------------------------------------
            failed = await make_call(factory, world, score=41,
                                     summary="Agent quoted 4500 although the EMI is 4000.")
            promo = await api.post(f"/api/v1/calls/{failed.call_id}/promote", headers=auth,
                                   json={"failure_type": "wrong_fact", "baseline_score": 80,
                                         "notes": "Amount read-back"})
            promo.raise_for_status()
            scenario = (await api.get(f"/api/v1/scenarios/{promo.json()['scenario_id']}",
                                      headers=read)).json()
            tests = (await api.get("/api/v1/regression-tests", headers=read,
                                   params={"agent_id": str(world.agent_id)})).json()["items"]
            out["promote"] = {"ids": promo.json(), "scenario_source": scenario["source"],
                              "scenario_source_call_id": scenario["source_call_id"],
                              "call_id": str(failed.call_id), "regression_test": tests[0]}

            # 3. regression run -> run.requested on Kafka ---------------------------------
            run = await api.post("/api/v1/runs:regression", headers=auth,
                                 json={"agent_id": str(world.agent_id),
                                       "config": {"max_concurrency": 2}})
            run.raise_for_status()
            run_id = run.json()["id"]
            out["regression_run"] = run.json()

            async def on_topic() -> Any:
                got = await read_topic(Topics.RUN_REQUESTED, key=run_id)
                return got or None

            msgs = await wait_for(on_topic, timeout=60, what="run.requested on Kafka")
            out["regression_run"]["kafka_message"] = json.loads(msgs[0].value)

            # 4. suite verdict from the database ------------------------------------------
            finished = await make_run(factory, world)
            test_id = tests[0]["id"]
            from uuid import UUID

            await make_call(factory, world, run_id=finished, regression_test_id=UUID(test_id),
                            score=76)
            async with factory() as session:
                items = await run_outcomes(session, finished)
            ok = summarize_run(RunState(finished, world.agent_id, "regression", "running", items))
            bad_run = await make_run(factory, world)
            await make_call(factory, world, run_id=bad_run, regression_test_id=UUID(test_id),
                            score=74)
            async with factory() as session:
                items = await run_outcomes(session, bad_run)
            bad = summarize_run(RunState(bad_run, world.agent_id, "regression", "running", items))
            out["suite"] = {"score_76_baseline_80_tol_5": ok.suite_passed,
                            "score_74_baseline_80_tol_5": bad.suite_passed}
            listed = (await api.get("/api/v1/regression-tests", headers=read)).json()["items"][0]
            out["suite"]["list_after"] = {k: listed[k] for k in
                                          ("last_run_id", "last_score", "last_passed")}

            # 5. reviews and calibration -----------------------------------------------------
            cases = [(92, 4, True, 4), (85, 3, True, 3), (60, 2, False, 1), (82, 3, False, 2)]
            for score, jd, hp, hd in cases:
                call = await make_call(factory, world, score=score, judge_dims=dimensions(jd))
                rr = await api.post(
                    f"/api/v1/calls/{call.call_id}/review", headers=auth,
                    json={"reviewer": "preetham", "passed": hp,
                          "dimensions": {k: {"score": hd} for k in dimensions()}})
                rr.raise_for_status()
            out["calibration"] = (await api.get("/api/v1/calibration", headers=read)).json()
            print("calibration:", out["calibration"])

        with psycopg.connect(f"{PG}/{DB}") as c:
            out["api_usage"] = [
                list(r) for r in c.execute(
                    "SELECT provider, operation, sum(units)::float, unit_type, count(*) "
                    "FROM api_usage GROUP BY 1,2,4")
            ]
        print("usage:", out["api_usage"])
    finally:
        for p in procs:
            p.terminate()
        for p in procs:
            p.wait(timeout=20)
        await engine.dispose()
    (HERE / "live_result.json").write_text(json.dumps(out, indent=2, ensure_ascii=False,
                                                      default=str))


if __name__ == "__main__":
    asyncio.run(main())
