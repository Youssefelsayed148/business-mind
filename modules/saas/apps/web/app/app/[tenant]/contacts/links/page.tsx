"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import * as api from "@/lib/api";
import type { CustomerLink } from "@/lib/api";
import {
  PAGE_SIZE,
  nextOffset,
  personName,
  platformLabel,
  previousOffset,
  stateHelp,
  stateLabel,
  stateTone,
} from "@/lib/customer-links";
import { roleSatisfies, useSession } from "@/lib/session";
import {
  Button,
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

export default function PeopleAcrossChannelsPage() {
  const { tenant: tenantId } = useParams<{ tenant: string }>();
  const { roleIn } = useSession();
  const allowed = roleSatisfies(roleIn(tenantId), "admin");
  const [platform, setPlatform] = useState("");
  const [state, setState] = useState("");
  const [query, setQuery] = useState("");
  const [offset, setOffset] = useState(0);
  const [rows, setRows] = useState<CustomerLink[] | null>(null);
  const [total, setTotal] = useState(0);
  const [failure, setFailure] = useState<Failure>(null);

  const load = useCallback(async () => {
    try {
      const result = await api.customerLinks(tenantId, {
        platform,
        state,
        q: query.trim(),
        limit: PAGE_SIZE,
        offset,
      });
      setRows(result.items);
      setTotal(result.total);
      setFailure(null);
    } catch (caught) {
      const status = caught instanceof api.ApiError ? caught.status : 0;
      setRows(null);
      setFailure(
        status === 404 ? "off" : status === 403 ? "forbidden" : "failed",
      );
    }
  }, [tenantId, platform, state, query, offset]);

  useEffect(() => {
    if (!allowed) return;
    const timer = setTimeout(() => void load(), 0);
    return () => clearTimeout(timer);
  }, [load, allowed]);

  const next = nextOffset(offset, total);
  const previous = previousOffset(offset);

  return (
    <main className="contacts-page">
      <PageHeader
        title="People across channels"
        purpose="Everyone known on WhatsApp, Instagram and Facebook, and whether they are also a contact in the chat inbox."
      />
      {!allowed && (
        <Notice
          tone="info"
          message="Only Owners and Admins can see this page."
        />
      )}
      {allowed && failure === "off" && (
        <Notice
          tone="info"
          message="This view is not turned on for your workspace yet."
        />
      )}
      {allowed && failure === "forbidden" && (
        <Notice
          tone="error"
          message="Your access does not include this view."
        />
      )}
      {allowed && failure === "failed" && (
        <Notice
          tone="error"
          message="Could not load people. Try again in a moment."
        />
      )}
      {allowed && !failure && (
        <>
          <Card title="Filters">
            <div className="contacts-form">
              <Field label="Channel">
                {(control) => (
                  <select
                    {...control}
                    value={platform}
                    onChange={(e) => {
                      setPlatform(e.target.value);
                      setOffset(0);
                    }}
                  >
                    <option value="">All channels</option>
                    <option value="whatsapp">WhatsApp</option>
                    <option value="instagram">Instagram</option>
                    <option value="facebook">Facebook</option>
                  </select>
                )}
              </Field>
              <Field label="Status">
                {(control) => (
                  <select
                    {...control}
                    value={state}
                    onChange={(e) => {
                      setState(e.target.value);
                      setOffset(0);
                    }}
                  >
                    <option value="">All</option>
                    <option value="linked">Linked</option>
                    <option value="many_only">Outreach only</option>
                    <option value="saas_only">Chat only</option>
                    <option value="conflict">Needs review</option>
                  </select>
                )}
              </Field>
              <Field label="Search name">
                {(control) => (
                  <input
                    {...control}
                    dir="auto"
                    value={query}
                    maxLength={100}
                    onChange={(e) => {
                      setQuery(e.target.value);
                      setOffset(0);
                    }}
                  />
                )}
              </Field>
            </div>
          </Card>
          {rows === null ? (
            <Loading />
          ) : (
            <Card title={`${total} ${total === 1 ? "person" : "people"}`}>
              <DataTable
                data-testid="people-across-channels"
                caption="People across channels"
                rows={rows}
                rowKey={(row) => row.id}
                empty={
                  <p className="muted">
                    No one matches. People appear after staff run the sync for
                    your workspace.
                  </p>
                }
                columns={[
                  {
                    key: "name",
                    header: "Name",
                    cell: (row) => (
                      <strong dir="auto">{personName(row)}</strong>
                    ),
                  },
                  {
                    key: "channel",
                    header: "Channel",
                    cell: (row) => platformLabel(row.platform),
                  },
                  {
                    key: "status",
                    header: "Status",
                    cell: (row) => (
                      <StatusBadge
                        value={row.state}
                        tone={stateTone(row.state)}
                        title={stateHelp(row.state)}
                      >
                        {stateLabel(row.state)}
                      </StatusBadge>
                    ),
                  },
                  {
                    key: "contact",
                    header: "Chat contact",
                    cell: (row) =>
                      row.contact_id ? (
                        <Link
                          href={`/app/${tenantId}/contacts/${row.contact_id}`}
                        >
                          Open contact
                        </Link>
                      ) : (
                        <span className="muted">None</span>
                      ),
                  },
                  {
                    key: "seen",
                    header: "First seen",
                    cell: (row) =>
                      row.seen_at
                        ? new Date(row.seen_at).toLocaleDateString("en-GB")
                        : "Unknown",
                  },
                ]}
              />
              {(previous !== null || next !== null) && (
                <div className="contacts-actions">
                  <Button
                    variant="quiet"
                    disabled={previous === null}
                    onClick={() => previous !== null && setOffset(previous)}
                  >
                    Previous
                  </Button>
                  <Button
                    variant="quiet"
                    disabled={next === null}
                    onClick={() => next !== null && setOffset(next)}
                  >
                    Next
                  </Button>
                </div>
              )}
            </Card>
          )}
        </>
      )}
    </main>
  );
}
