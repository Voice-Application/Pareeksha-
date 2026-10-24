"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api/client";
import { call, ApiError } from "@/lib/api/call";
import { PageHeader, Panel } from "@/components/ui/layout";
import { FormSkeleton, PageError } from "@/components/ui/states";
import { NoiseEditor } from "./noise-editor";

/** Deep link `/noise-profiles/[id]` (and `/noise-profiles/new`). */
export function NoisePage({ profileId }: { profileId?: string }) {
  const profile = useQuery({
    queryKey: ["noise-profile", profileId],
    queryFn: () => call(api.GET("/api/v1/noise-profiles/{noise_profile_id}", { params: { path: { noise_profile_id: profileId! } } })),
    enabled: !!profileId,
    retry: (n, e) => !(e instanceof ApiError && e.status === 404) && n < 1,
  });
  const crumb = (
    <>
      <Link href="/noise-profiles" className="text-accent-fg underline underline-offset-2">
        Noise profiles
      </Link>{" "}
      / {profileId ? (profile.data?.name ?? "") : "New"}
    </>
  );
  if (profileId && profile.isPending) {
    return (
      <>
        <PageHeader eyebrow={crumb} title="Noise profile" />
        <FormSkeleton sections={2} />
      </>
    );
  }
  if (profileId && profile.isError) {
    return (
      <>
        <PageHeader eyebrow={crumb} title="Noise profile" />
        <PageError error={profile.error} onRetry={() => void profile.refetch()} backHref="/noise-profiles" backLabel="Back to noise profiles" />
      </>
    );
  }
  return (
    <>
      <PageHeader eyebrow={crumb} title={profile.data?.name ?? "New noise profile"} description="The phone line the caller is on: codec, band-limit, background, SNR and packet loss." />
      <div className="max-w-[560px]">
        <Panel>
          <NoiseEditor key={profile.data?.id ?? "new"} profile={profile.data} mode="page" />
        </Panel>
      </div>
    </>
  );
}
