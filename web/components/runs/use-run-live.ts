"use client";

import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { getRun, listRunItems, type Run, type RunItem } from "@/lib/api/runs";

export type LiveState = "connecting" | "live" | "reconnecting" | "polling" | "closed";

async function fetchAllItems(runId: string): Promise<RunItem[]> {
  const out: RunItem[] = [];
  let cursor: string | null | undefined = null;
  do {
    const page = await listRunItems(runId, cursor);
    out.push(...page.items);
    cursor = page.next_cursor;
  } while (cursor);
  return out;
}

const TERMINAL = new Set(["completed", "partial", "cancelled", "failed"]);

/** Run + items kept fresh by SSE (snapshot, item.status, call.evaluated, run.completed); 5 s polling when the stream is down (08-run-detail). */
export function useRunLive(runId: string) {
  const qc = useQueryClient();
  const [live, setLive] = useState<LiveState>("connecting");
  const [updatedAt, setUpdatedAt] = useState<number>(() => Date.now());
  const [flash, setFlash] = useState<Set<string>>(new Set());
  const errors = useRef(0);

  const run = useQuery({ queryKey: ["run", runId], queryFn: () => getRun(runId) });
  const items = useQuery({ queryKey: ["run-items", runId], queryFn: () => fetchAllItems(runId) });
  const terminal = run.data ? TERMINAL.has(run.data.status) : false;

  useEffect(() => {
    if (terminal) return;
    if (typeof EventSource === "undefined") {
      queueMicrotask(() => setLive("polling"));
      return;
    }
    const es = new EventSource(`/api/proxy/api/v1/runs/${runId}/events`);
    const touch = () => setUpdatedAt(Date.now());
    const patchItem = (id: string, patch: Partial<RunItem>) =>
      qc.setQueryData<RunItem[]>(["run-items", runId], (old) => (old ? old.map((i) => (i.id === id ? { ...i, ...patch } : i)) : old));
    const refreshRun = () => void qc.invalidateQueries({ queryKey: ["run", runId] });

    es.onopen = () => {
      errors.current = 0;
      setLive("live");
    };
    es.addEventListener("snapshot", (e) => {
      const d = JSON.parse((e as MessageEvent).data) as { run: Run; items: RunItem[] };
      qc.setQueryData(["run", runId], d.run);
      qc.setQueryData(["run-items", runId], d.items);
      setLive("live");
      touch();
    });
    es.addEventListener("item.status", (e) => {
      const d = JSON.parse((e as MessageEvent).data) as { run_item_id: string; status: RunItem["status"] };
      patchItem(d.run_item_id, { status: d.status });
      touch();
    });
    es.addEventListener("call.evaluated", (e) => {
      const d = JSON.parse((e as MessageEvent).data) as { run_item_id: string; call_id: string; overall_score: number; passed: boolean; critical_failure: boolean };
      patchItem(d.run_item_id, { status: "evaluated", call_id: d.call_id, overall_score: d.overall_score, passed: d.passed, critical_failure: d.critical_failure });
      setFlash((f) => new Set(f).add(d.run_item_id));
      setTimeout(() => setFlash((f) => { const n = new Set(f); n.delete(d.run_item_id); return n; }), 900);
      refreshRun();
      touch();
    });
    es.addEventListener("run.completed", () => {
      refreshRun();
      void qc.invalidateQueries({ queryKey: ["run-items", runId] });
      setLive("closed");
      es.close();
      touch();
    });
    es.onerror = () => {
      errors.current += 1;
      if (errors.current >= 3) {
        setLive("polling");
        es.close();
      } else setLive("reconnecting");
    };
    return () => es.close();
  }, [runId, terminal, qc]);

  // Fallback polling.
  useEffect(() => {
    if (live !== "polling") return;
    const t = setInterval(() => {
      void run.refetch();
      void items.refetch();
      setUpdatedAt(Date.now());
    }, 5000);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [live]);

  return { run, items, live: terminal ? ("closed" as LiveState) : live, updatedAt, flash };
}
