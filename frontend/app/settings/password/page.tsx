"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { AuthShell } from "../../components/auth/AuthShell";
import { ChangePasswordCard } from "../../components/auth/ChangePasswordCard";
import { useAuth } from "../../lib/auth/context";

/**
 * User-facing change-password page (top-level, no admin chrome).
 *
 * Unauthenticated users are bounced to /login. Admins are welcome here
 * too — the AdminTopBar offers an admin-themed entry point at
 * /admin/settings/password.
 */
export default function ChangePasswordPage() {
  const router = useRouter();
  const { status, session } = useAuth();

  useEffect(() => {
    if (status === "loading") return;
    if (!session) router.replace("/login?next=/settings/password");
  }, [status, session, router]);

  if (status === "loading" || !session) {
    return (
      <AuthShell title="Account security" subtitle="Loading your account…">
        <div className="h-32 animate-pulse rounded-lg bg-slate-100" />
      </AuthShell>
    );
  }

  return (
    <AuthShell
      title="Change password"
      subtitle={`Signed in as ${session.user.email}.`}
    >
      <ChangePasswordCard />
      <div className="pt-3 text-center text-[12px] text-slate-500">
        <Link
          href="/"
          className="text-[#9E6A0E] underline-offset-4 hover:underline"
        >
          ← Back to LawFlow
        </Link>
      </div>
    </AuthShell>
  );
}
