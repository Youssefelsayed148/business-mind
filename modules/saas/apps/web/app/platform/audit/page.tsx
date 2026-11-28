"use client";

import { useCallback, useEffect, useState } from "react";

import * as api from "@/lib/api";
import type { AuditRow } from "@/lib/api";
import { levelTone, sourceLabel } from "@/lib/customer-links";
import {
  Card,
  DataTable,
  Field,
  Loading,
  Notice,
  PageHeader,
  StatusBadge,
} from "@/lib/ui";

import "@/app/contacts-screen.css";

type Failure = "off" | "forbidden" | "failed" | null;

export default function CombinedAuditPage() {
  const [source, setSource] = useState("all");
  const [rows, setRows] = useState<AuditRow[] | null>(null);
  const [notes, setNotes] = useState<string[]>([]);
  const [failure, setFailure] = useState<Failure>(null);

  const load = useCallback(async () => {
    try {
      const result = await api.combinedAudit({ source, limit: 100 });
      setRows(result.items);
      setNotes(result.notes);
      setFailure(null);
    } catch (caught) {
      const status = caught instanceof api.ApiError ? caught.status : 0;
      setRows(null);
      setFailure(
        status === 404 ? "off" : status === 403 ? "forbidden" : "failed",
      );
    }
  }, [source]);
  useEffect(() => {
    const timer = setTimeout(() => void load(), 0);
    return () => clearTimeout(timer);
  }, [load]);

  return (
    <main className="contacts-page">
      <PageHeader
        title="Audit trail"
        purpose="What happened in the chat inbox and the outreach service, newest first. Each row names its source. Platform staff only."
      />
      {failure === "off" && (
        <Notice tone="info" message="This view is not turned on yet." />
      )}
      {failure === "forbidden" && (
        <Notice tone="error" message="Only platform staff can see this page." />
      )}
      {failure === "failed" && (
        <Notice tone="error" message="Could not load the audit trail." />
      )}
      {notes.map((note) => (
        <Notice key={note} tone="info" message={note} />
      ))}
      {!failure && (
        <Card title="Entries">
          <Field label="Source">
            {(control) => (
              <select
                {...control}
                value={source}
                onChange={(e) => setSource(e.target.value)}
              >
                <option value="all">Both</option>
                <option value="saas">Chat inbox</option>
                <option value="many">Outreach service</option>
              </select>
            )}
          </Field>
          {rows === null ? (
            <Loading />
          ) : (
            <DataTable
              data-testid="combined-audit"
              caption="Combined audit trail"
              rows={rows}
              rowKey={(row) => `${row.source}:${row.at}:${row.action}`}
              empty={<p className="muted">No entries yet.</p>}
              columns={[
                {
                  key: "when",
                  header: "When",
                  cell: (row) => new Date(row.at).toLocaleString("en-GB"),
                },
                {
                  key: "source",
                  header: "Source",
                  cell: (row) => sourceLabel(row.source),
                },
                {
                  key: "level",
                  header: "Level",
                  cell: (row) => (
                    <StatusBadge value={row.level} tone={levelTone(row.level)}>
                      {row.level}
                    </StatusBadge>
                  ),
                },
                {
                  key: "action",
                  header: "Event",
                  cell: (row) => <span dir="auto">{row.action}</span>,
                },
                {
                  key: "summary",
                  header: "What happened",
                  cell: (row) => <span dir="auto">{row.summary}</span>,
                },
              ]}
            />
          )}
        </Card>
      )}
    </main>
  );
}
