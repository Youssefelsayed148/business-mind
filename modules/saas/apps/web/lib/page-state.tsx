"use client";

/** The four states every ported page shows (docs/PHASE-4-PLAN.md 12.6, Phase 4B). */

import Link from "next/link";
import type { ReactNode } from "react";

import type { ManyFailure } from "./many";
import { MANY_FAILURE_MESSAGE } from "./many";
import { Empty, Loading, Notice } from "./ui";

export type PageStatus =
  | { kind: "loading" }
  | { kind: "ready" }
  /** Nothing to show yet: one sentence and, when the role may, one action. */
  | { kind: "empty"; message: string; action?: ReactNode }
  | { kind: "failed"; failure: ManyFailure; onRetry?: () => void };

export function PageState({
  status,
  homeHref = "/app",
  children,
}: {
  status: PageStatus;
  homeHref?: string;
  children: ReactNode;
}) {
  switch (status.kind) {
    case "loading":
      return <Loading />;
    case "empty":
      return (
        <div data-testid="page-empty">
          <Empty>{status.message}</Empty>
          {status.action}
        </div>
      );
    case "failed":
      return <FailureView {...status} homeHref={homeHref} />;
    case "ready":
      return <>{children}</>;
  }
}

function FailureView({
  failure,
  onRetry,
  homeHref,
}: {
  failure: ManyFailure;
  onRetry?: () => void;
  homeHref: string;
}) {
  const message = MANY_FAILURE_MESSAGE[failure];
  // A 403 is a state of the page, not a toast: say why and link home.
  if (failure === "forbidden" || failure === "not_available") {
    return (
      <div data-testid={`page-${failure}`}>
        <Notice message={message} scope="item" />
        <p>
          <Link href={homeHref}>Go back</Link>
        </p>
      </div>
    );
  }
  if (failure === "session") {
    return (
      <div data-testid="page-session">
        <Notice message={message} scope="item" />
        <p>
          <Link href="/login">Sign in</Link>
        </p>
      </div>
    );
  }
  return (
    <div data-testid={`page-${failure}`}>
      <Notice
        message={message}
        tone="error"
        onRetry={onRetry}
        retryLabel="Try again"
        scope={onRetry ? "page" : "item"}
      />
    </div>
  );
}
