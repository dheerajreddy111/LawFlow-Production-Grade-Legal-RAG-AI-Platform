"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

/**
 * /admin → /admin/overview. The layout's role gate already handles the
 * not-authed case, so this page only fires the redirect.
 */
export default function AdminIndex() {
  const router = useRouter();
  useEffect(() => {
    router.replace("/admin/overview");
  }, [router]);
  return null;
}
