"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { isApiError } from "@/lib/api";
import { SessionProvider } from "@/lib/auth";

export function makeQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        refetchOnWindowFocus: true,
        // Client errors will not fix themselves; only retry network/server hiccups.
        retry: (count, error) =>
          count < 2 && !(isApiError(error) && error.status >= 400 && error.status < 500),
      },
    },
  });
}

/** Query cache and session, scoped to the admin tree only. */
export function AdminProviders({ children }: { children: ReactNode }) {
  const [client] = useState(makeQueryClient);
  return (
    <QueryClientProvider client={client}>
      <SessionProvider>{children}</SessionProvider>
    </QueryClientProvider>
  );
}
