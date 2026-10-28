"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { Scale } from "lucide-react";
import { api } from "@/lib/api/client";
import { call } from "@/lib/api/call";
import { RUBRIC } from "@/lib/api/calls";
import { PageHeader, Panel } from "@/components/ui/layout";
import { LinkButton } from "@/components/ui/button";
import { ErrorPanel, NotEnabled, isNotImplemented, Skeleton, Strip } from "@/components/ui/states";
import { StatTile, TileRow } from "@/components/ui/measure";

const TARGET_KAPPA = 0.6;

export function CalibrationPage() {
  const q = useQuery({ queryKey: ["calibration"], retry: false, queryFn: () => call(api.GET("/api/v1/calibration")) });
  const next = useQuery({ queryKey: ["calls", "unlabelled"], queryFn: () => call(api.GET("/api/v1/calls", { params: { query: { reviewed: false, source: ["simulation", "upload", "import"], limit: 1 } } })) });
  const nextId = next.data?.items?.[0]?.id;
  if (q.isError && isNotImplemented(q.error))
    return (
      <>
        <PageHeader eyebrow="Calibration" title="Calibration" description="Compare the judge with your own labels on pass or fail and per dimension." />
        <Panel><NotEnabled icon={Scale} what="Calibration" error={q.error} /></Panel>
      </>
    );
  const d = q.data;
  const kappa = d?.kappa_pass_fail ?? null;
  const n = d?.n ?? 0;
  const mae = Object.entries(d?.dimension_mae ?? {}).sort((a, b) => b[1] - a[1]);
  const label = (k: string) => RUBRIC.find((r) => r.key === k)?.label ?? k;
  return (
    <>
      <PageHeader
        eyebrow="Rubric rubric-2026-10-v1"
        title={!d ? "Calibration" : n === 0 ? "No labelled calls yet" : kappa === null ? `${n} labelled calls, agreement not computable yet` : `The judge agrees with your pass or fail labels with kappa ${kappa.toFixed(2)} over ${n} calls`}
        description={d && n > 0 ? [d.spearman_overall != null ? `Overall scores correlate at rho ${d.spearman_overall.toFixed(2)}.` : "", mae[0] ? `Largest gap: ${mae[0][0]} (MAE ${mae[0][1].toFixed(1)}).` : "", kappa !== null && kappa < TARGET_KAPPA ? `Below the ${TARGET_KAPPA} target. The rubric should be revised and re-calibrated.` : ""].filter(Boolean).join(" ") : "Label calls without seeing the judge, then compare."}
        actions={nextId ? <LinkButton variant="primary" href={`/calls/${nextId}`}>Start labelling</LinkButton> : undefined}
      />
      {q.isError && <div className="mb-6"><ErrorPanel error={q.error} what="calibration" onRetry={() => void q.refetch()} /></div>}
      {q.isPending ? <Skeleton className="h-24 w-full" /> : d && (
        <>
          {n > 0 && n < 10 && <div className="mb-6"><Strip tone="warn">Only {n} labelled calls. Agreement numbers are unreliable below 30.</Strip></div>}
          <TileRow cols="grid-cols-2 min-[860px]:grid-cols-4">
            <StatTile label="Kappa pass/fail" value={kappa === null ? "-" : kappa.toFixed(2)} threshold={kappa === null || n < 10 ? null : kappa >= TARGET_KAPPA ? "ok" : "fail"} caption={kappa === null ? "needs both passing and failing calls" : `target at least ${TARGET_KAPPA}`} />
            <StatTile label="Spearman, overall" value={d.spearman_overall == null ? "-" : d.spearman_overall.toFixed(2)} caption="judge score against yours" />
            <StatTile label="Labelled calls" value={n} caption="30 or more recommended" />
            <StatTile label="Largest dimension gap" value={mae[0] ? mae[0][1].toFixed(1) : "-"} caption={mae[0] ? label(mae[0][0]) : "no labels yet"} />
          </TileRow>
          <div className="grid items-start gap-6 min-[1180px]:grid-cols-[minmax(0,1fr)_408px]">
            <Panel title="Per-dimension error (MAE, 0-4 scale)">
              {mae.length === 0 ? <p className="text-sm text-subtle">No dimension labels yet.</p> : (
                <ul className="flex flex-col gap-3">
                  {mae.map(([k, v]) => (
                    <li key={k} className="grid grid-cols-[160px_1fr_40px] items-center gap-3 text-sm">
                      <span>{label(k)}</span>
                      <span className="h-2 rounded-xs bg-sunken"><span className="block h-full rounded-xs" style={{ width: `${Math.min(100, (v / 4) * 100)}%`, background: "var(--series-1)" }} /></span>
                      <span className="mono text-right">{v.toFixed(1)}</span>
                    </li>
                  ))}
                </ul>
              )}
            </Panel>
            <Panel title="Label queue">
              <p className="text-sm text-muted">{nextId ? "Open the next unlabelled call, listen, and save your own scores with Override judge score." : "No unlabelled calls. Run a few calls first."}</p>
              <p className="mt-3 text-xs text-subtle">Blind mode and the disagreement list need a list of human-reviewed evaluations that the API does not expose yet (gap G-13). <Link className="underline" href="/runs">Open runs</Link></p>
            </Panel>
          </div>
        </>
      )}
    </>
  );
}
