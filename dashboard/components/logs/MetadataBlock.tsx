"use client";

import { useState } from "react";
import { Button } from "@/components/ui/Button";

function labelForKey(key: string) {
  return key.replaceAll("_", " ").replace(/\b\w/g, (char) => char.toUpperCase());
}

function formatValue(value: unknown) {
  if (value === null || value === undefined || value === "") return "None";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
  return JSON.stringify(value, null, 2);
}

export function MetadataBlock({ metadata }: { metadata: Record<string, unknown> }) {
  const [open, setOpen] = useState(false);
  const [rawOpen, setRawOpen] = useState(false);
  const entries = Object.entries(metadata || {});

  return (
    <div className="grid gap-3">
      <Button type="button" variant="secondary" className="w-fit" onClick={() => setOpen(!open)}>
        {open ? "Hide metadata" : "Show metadata"}
      </Button>
      {open ? (
        <div className="grid gap-3 rounded-xl border border-slate-200 bg-slate-50/80 p-4">
          {entries.length > 0 ? (
            <dl className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
              {entries.map(([key, value]) => (
                <div key={key} className="rounded-lg border border-slate-200 bg-white p-3">
                  <dt className="text-xs font-semibold uppercase tracking-wide text-slate-500">{labelForKey(key)}</dt>
                  <dd className="mt-1 max-h-28 overflow-auto whitespace-pre-wrap break-words font-mono text-xs leading-5 text-slate-800">
                    {formatValue(value)}
                  </dd>
                </div>
              ))}
            </dl>
          ) : (
            <p className="text-sm text-muted">No metadata available.</p>
          )}
          <div className="grid gap-2">
            <button
              type="button"
              className="w-fit text-xs font-semibold text-slate-500 transition hover:text-ink"
              onClick={() => setRawOpen(!rawOpen)}
            >
              {rawOpen ? "Hide raw JSON" : "View raw JSON"}
            </button>
            {rawOpen ? (
              <pre className="max-h-72 overflow-auto rounded-lg border border-slate-200 bg-slate-950/[0.03] p-4 font-mono text-xs leading-5 text-slate-700 shadow-inner">
                {JSON.stringify(metadata, null, 2)}
              </pre>
            ) : null}
          </div>
        </div>
      ) : null}
    </div>
  );
}
