"use client";

import { useRouter } from "next/navigation";
import { useAuth } from "@/context/AuthContext";

type Props = { userId: string };

export default function DashboardClient({ userId }: Props) {
  const { user, logout } = useAuth();
  const router = useRouter();

  const handleLogout = async () => {
    await logout();
    router.push("/login");
  };

  return (
    <div className="min-h-screen flex flex-col items-center justify-center px-4">
      <div className="w-full max-w-lg bg-white rounded-2xl shadow-sm border border-gray-100 p-8">
        <div className="flex items-center justify-between mb-6">
          <h1 className="text-2xl font-semibold text-gray-900">Dashboard</h1>
          <button
            onClick={handleLogout}
            className="text-sm text-gray-500 hover:text-red-600 transition-colors"
          >
            Sign out
          </button>
        </div>

        <div className="bg-gray-50 rounded-xl p-4 space-y-2">
          <p className="text-sm text-gray-500">Signed in as</p>
          <p className="font-medium text-gray-900">{user?.email ?? "—"}</p>
          <p className="text-xs text-gray-400 font-mono">ID: {userId}</p>
        </div>

        <p className="mt-6 text-sm text-gray-500">
          You are authenticated. This page is protected by both{" "}
          <code className="bg-gray-100 px-1 rounded text-xs">middleware.ts</code> and
          server-side DAL verification (CVE-2025-29927 hardened).
        </p>
      </div>
    </div>
  );
}
