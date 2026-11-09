import { connection } from "next/server";
import type { ReactNode } from "react";
import { DashboardAuth } from "@/components/dashboard-auth";

/** Read deployment auth settings for dashboard requests, including reused production builds. */
export default async function DashboardLayout({ children }: { children: ReactNode }) {
  await connection();
  return <DashboardAuth authDisabled={process.env.AUTH_DISABLED === "1"}>{children}</DashboardAuth>;
}
