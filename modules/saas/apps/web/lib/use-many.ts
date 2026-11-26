"use client";

import { useCallback, useEffect, useState } from "react";

import { manyFailureKind, type ManyFailure } from "./many";
import type { PageStatus } from "./page-state";

/**
 * Load one thing from Many and expose it as a PageStatus for `PageState`.
 * `key` re-runs the load when it changes (an organization, a filter, a page number).
 * `isEmpty` turns a successful empty answer into the empty state.
 */
export function useManyData<T>(
  load: () => Promise<T>,
  key: string,
  options: { isEmpty?: (data: T) => boolean; emptyMessage?: string } = {},
): {
  data: T | null;
  status: PageStatus;
  reload: () => void;
  failure: ManyFailure | null;
} {
  const [data, setData] = useState<T | null>(null);
  const [failure, setFailure] = useState<ManyFailure | null>(null);
  const [tick, setTick] = useState(0);
  const reload = useCallback(() => setTick((value) => value + 1), []);

  useEffect(() => {
    let cancelled = false;
    // Deferred so the effect does not set state synchronously.
    const timer = setTimeout(() => {
      setFailure(null);
      load().then(
        (result) => {
          if (!cancelled) setData(result);
        },
        (caught: unknown) => {
          if (!cancelled) {
            setData(null);
            setFailure(manyFailureKind(caught));
          }
        },
      );
    }, 0);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
    // `load` is rebuilt every render; `key` and `tick` say when to load again.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, tick]);

  let status: PageStatus;
  if (failure) status = { kind: "failed", failure, onRetry: reload };
  else if (data === null) status = { kind: "loading" };
  else if (options.isEmpty?.(data))
    status = {
      kind: "empty",
      message: options.emptyMessage ?? "Nothing here yet.",
    };
  else status = { kind: "ready" };
  return { data, status, reload, failure };
}
