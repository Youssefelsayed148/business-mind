"use client";

import { useMemo, useState } from "react";

import { Icon } from "@/lib/icons";
import { manyRequest } from "@/lib/many";
import { PageState, type PageStatus } from "@/lib/page-state";
import { useManyData } from "@/lib/use-many";
import { Button, Card, Field, LinkButton, PageHeader } from "@/lib/ui";
import { useAuditViewAvailable } from "@/lib/use-customer-links";
import {
  buildEventTypeOptions,
  eventCategory,
  eventIconName,
  eventLabel,
  eventSeverity,
  formatExactTime,
  formatRelativeTime,
  KNOWN_EVENT_TYPES,
  logsQuery,
  type LogFilterValues,
} from "@/lib/many-staff/event-presentation";
import { groupLogFlow } from "@/lib/many-staff/log-grouping";
import { MetadataBlock } from "@/lib/many-staff/metadata-block";
import type { ManyLog } from "@/lib/many-staff/types";
import { useStaffCampaigns } from "@/lib/many-staff/use-lookups";

import "@/app/staff-many-screen.css";

/** The Many activity log with filters, grouped message flows and metadata (platform staff only). */
export default function StaffLogsPage() {
  const auditAvailable = useAuditViewAvailable();
  const campaigns = useStaffCampaigns();
  const [filters, setFilters] = useState<LogFilterValues>({
    level: "",
    campaign_id: "",
    event_type: "",
    limit: "100",
  });
  const [seenTypes, setSeenTypes] = useState<string[]>([]);
  const [openGroups, setOpenGroups] = useState<Record<string, boolean>>({});
  const query = logsQuery(filters);

  const { data, status } = useManyData<ManyLog[]>(async () => {
    const rows = await manyRequest<ManyLog[]>(
      { kind: "staff" },
      "GET",
      `logs${query ? `?${query}` : ""}`,
    );
    setSeenTypes((current) =>
      Array.from(
        new Set([...current, ...rows.map((row) => row.event_type)]),
      ).filter(Boolean),
    );
    return rows;
  }, query);

  const eventTypeOptions = useMemo(
    () => buildEventTypeOptions([...KNOWN_EVENT_TYPES, ...seenTypes]),
    [seenTypes],
  );
  const groups = useMemo(() => groupLogFlow(data ?? []), [data]);

  let shown: PageStatus = status;
  if (status.kind === "ready" && groups.length === 0) {
    shown = {
      kind: "empty",
      message:
        "No logs found. Adjust the filters or wait for campaign activity.",
    };
  }

  return (
    <div className="staff-many-page">
      <PageHeader
        title="Logs"
        purpose="Automation events from the Many activity log, with their metadata. Platform staff only."
        actions={
          auditAvailable ? (
            <LinkButton variant="secondary" href="/platform/audit">
              Combined audit trail
            </LinkButton>
          ) : undefined
        }
      />
      <Card title="Log filters">
        <div className="staff-many-filter-grid">
          <Field label="Level">
            {(control) => (
              <select
                {...control}
                value={filters.level}
                onChange={(event) =>
                  setFilters({ ...filters, level: event.target.value })
                }
              >
                <option value="">All levels</option>
                <option value="info">Info</option>
                <option value="warning">Warning</option>
                <option value="error">Error</option>
              </select>
            )}
          </Field>
          <Field label="Campaign">
            {(control) => (
              <select
                {...control}
                value={filters.campaign_id}
                onChange={(event) =>
                  setFilters({ ...filters, campaign_id: event.target.value })
                }
              >
                <option value="">All campaigns</option>
                {campaigns.map((campaign) => (
                  <option key={campaign.id} value={campaign.id}>
                    {campaign.name}
                    {campaign.status ? ` (${campaign.status})` : ""}
                  </option>
                ))}
              </select>
            )}
          </Field>
          <Field label="Event type">
            {(control) => (
              <select
                {...control}
                value={filters.event_type}
                onChange={(event) =>
                  setFilters({ ...filters, event_type: event.target.value })
                }
              >
                <option value="">All event types</option>
                {eventTypeOptions.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            )}
          </Field>
          <Field label="Limit" hint="1 to 500 events, newest first.">
            {(control) => (
              <input
                {...control}
                type="number"
                min={1}
                max={500}
                dir="ltr"
                value={filters.limit}
                onChange={(event) =>
                  setFilters({ ...filters, limit: event.target.value })
                }
              />
            )}
          </Field>
        </div>
      </Card>
      <PageState status={shown} homeHref="/platform">
        <Card title="Event stream">
          <ol className="staff-many-events" data-testid="staff-logs">
            {groups.map((group) => {
              const log = group.logs[0];
              const severity = eventSeverity(log.event_type, log.level);
              const expanded = !!openGroups[group.id];
              const title =
                group.kind === "group"
                  ? "Message flow"
                  : eventLabel(log.event_type);
              return (
                <li
                  key={group.id}
                  className="staff-many-event"
                  data-severity={severity}
                  data-testid={`log-${group.kind}`}
                >
                  <div className="staff-many-event-head">
                    <span className="staff-many-event-icon" aria-hidden="true">
                      <Icon name={eventIconName(severity)} size={18} />
                    </span>
                    <div>
                      <h3>{title}</h3>
                      <p className="staff-many-event-tags">
                        {group.logs.length > 1 && (
                          <span>{group.logs.length} events</span>
                        )}
                        <span>{eventCategory(log.event_type)}</span>
                        <span>{severity}</span>
                      </p>
                      <p className="muted staff-many-event-meta">
                        <code dir="ltr">{log.event_type}</code>
                        {log.actor_email && (
                          <span dir="ltr">{log.actor_email}</span>
                        )}
                        <span dir="auto">
                          {log.entity_name || log.campaign || "No campaign"}
                        </span>
                        <span>{formatRelativeTime(log.created_at)}</span>
                        <span>{formatExactTime(log.created_at)}</span>
                      </p>
                    </div>
                  </div>
                  <p className="staff-many-event-message" dir="auto">
                    {log.message}
                  </p>
                  {group.logs.length > 1 && (
                    <Button
                      variant="quiet"
                      aria-expanded={expanded}
                      onClick={() =>
                        setOpenGroups({ ...openGroups, [group.id]: !expanded })
                      }
                    >
                      {expanded
                        ? "Collapse grouped events"
                        : "Expand grouped events"}
                    </Button>
                  )}
                  {expanded && (
                    <ul className="staff-many-children">
                      {group.logs.map((child) => (
                        <li key={child.id}>
                          <strong>{eventLabel(child.event_type)}</strong>{" "}
                          <code dir="ltr">{child.event_type}</code>{" "}
                          <span className="muted">
                            {formatRelativeTime(child.created_at)}
                          </span>
                          <p dir="auto">{child.message}</p>
                        </li>
                      ))}
                    </ul>
                  )}
                  <MetadataBlock metadata={log.metadata} />
                </li>
              );
            })}
          </ol>
        </Card>
      </PageState>
    </div>
  );
}
