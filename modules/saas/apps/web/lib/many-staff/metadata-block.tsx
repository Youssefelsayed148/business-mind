"use client";

import { useState } from "react";

import { Button } from "@/lib/ui";

import { metadataKeyLabel, metadataValueText } from "./event-presentation";

/** One log row's metadata: a readable list and the raw JSON, both hidden until asked for. */
export function MetadataBlock({
  metadata,
}: {
  metadata: Record<string, unknown>;
}) {
  const [open, setOpen] = useState(false);
  const [rawOpen, setRawOpen] = useState(false);
  const entries = Object.entries(metadata || {});
  return (
    <div className="staff-many-metadata">
      <Button
        variant="quiet"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
        data-testid="log-metadata-toggle"
      >
        {open ? "Hide metadata" : "Show metadata"}
      </Button>
      {open && (
        <div className="staff-many-metadata-body" data-testid="log-metadata">
          {entries.length > 0 ? (
            <dl>
              {entries.map(([key, value]) => (
                <div key={key}>
                  <dt>{metadataKeyLabel(key)}</dt>
                  <dd dir="auto">{metadataValueText(value)}</dd>
                </div>
              ))}
            </dl>
          ) : (
            <p className="muted">No metadata available.</p>
          )}
          <Button
            variant="quiet"
            aria-expanded={rawOpen}
            onClick={() => setRawOpen(!rawOpen)}
          >
            {rawOpen ? "Hide raw JSON" : "View raw JSON"}
          </Button>
          {rawOpen && <pre dir="ltr">{JSON.stringify(metadata, null, 2)}</pre>}
        </div>
      )}
    </div>
  );
}
