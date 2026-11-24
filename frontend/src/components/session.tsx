"use client";

import { useRouter } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { api, ApiError, type Me } from "@/lib/api";
import { getSupabase } from "@/lib/supabase";
import { Alert, Spinner } from "./ui";

type Ctx = { me: Me; refresh: () => Promise<void> };
const SessionContext = createContext<Ctx | null>(null);

export function useSession(): Ctx {
  const ctx = useContext(SessionContext);
  if (!ctx) throw new Error("useSession outside SessionGate");
  return ctx;
}

/**
 * Requires a signed-in user. `need` controls the extra requirement:
 * - "business": redirect to onboarding if the user has no business yet
 * - "admin": only BILEKSA admins (the API enforces this too)
 * - "none": signed in is enough (onboarding)
 */
export function SessionGate({
  need,
  children,
}: {
  need: "business" | "admin" | "none";
  children: ReactNode;
}) {
  const router = useRouter();
  const [me, setMe] = useState<Me | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (): Promise<Me | null> => {
    const { data } = await getSupabase().auth.getSession();
    if (!data.session) {
      router.replace("/login");
      return null;
    }
    return api<Me>("/api/me");
  }, [router]);

  const onError = useCallback(
    (e: unknown) => {
      if (e instanceof ApiError && e.status === 401) router.replace("/login");
      else setError(e instanceof Error ? e.message : "Could not load your account");
    },
    [router],
  );

  const refresh = useCallback(async () => {
    try {
      const result = await load();
      if (result) setMe(result);
    } catch (e) {
      onError(e);
    }
  }, [load, onError]);

  useEffect(() => {
    let alive = true;
    load()
      .then((result) => alive && result && setMe(result))
      .catch((e) => alive && onError(e));
    return () => {
      alive = false;
    };
  }, [load, onError]);

  if (error)
    return (
      <div className="mx-auto max-w-lg p-8">
        <Alert>{error}</Alert>
      </div>
    );
  if (!me) return <Spinner />;
  if (need === "business" && !me.business)
    return (
      <div className="mx-auto max-w-lg p-8">
        <Alert tone="blue">
          Your account is not linked to a business yet. BILEKSA sets up client accounts; if you were
          invited, use the link in your invitation email, or contact BILEKSA support.
          {me.is_admin && " You are a BILEKSA admin: open the admin area at /admin."}
        </Alert>
      </div>
    );
  if (need === "admin" && !me.is_admin)
    return (
      <div className="mx-auto max-w-lg p-8">
        <Alert>This area is for BILEKSA staff only.</Alert>
      </div>
    );
  return <SessionContext.Provider value={{ me, refresh }}>{children}</SessionContext.Provider>;
}

export async function signOut(router: ReturnType<typeof useRouter>) {
  await getSupabase().auth.signOut();
  router.replace("/login");
}
