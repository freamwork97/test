import { redirect } from "next/navigation";
import { verifySession } from "@/lib/auth";
import DashboardClient from "./DashboardClient";

export default async function DashboardPage() {
  // DAL-level re-verification (CVE-2025-29927 대응: middleware 우회 차단)
  const session = await verifySession();
  if (!session) {
    redirect("/login");
  }

  return <DashboardClient userId={session.sub} />;
}
