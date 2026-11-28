"use client";

import { useEffect, useState } from "react";

import * as api from "./api";
import type { CustomerOverview } from "./api";
import { RANGE_OPTIONS, costText, platformLabel } from "./customer-links";
import { Card, DataTable, Field, Loading } from "./ui";

/** Combined numbers for one organization, each labelled with where it comes from. */
export function CustomerOverviewCard({ tenantId }: { tenantId: string }) {
  const [days, setDays] = useState<number>(30);
  const [data, setData] = useState<CustomerOverview | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let cancelled = false;
    api
      .customerOverview(tenantId, days)
      .then((result) => {
        if (cancelled) return;
        setData(result);
        setFailed(false);
      })
      .catch(() => !cancelled && setFailed(true));
    return () => {
      cancelled = true;
    };
  }, [tenantId, days]);
  if (failed) return null;
  if (!data) return <Loading />;
  const rows = Object.entries(data.people.by_platform);
  return (
    <Card title={`Overview, last ${data.range.days} days`}>
      <Field label="Period">
        {(control) => (
          <select
            {...control}
            value={days}
            onChange={(event) => setDays(Number(event.target.value))}
          >
            {RANGE_OPTIONS.map((option) => (
              <option key={option} value={option}>
                Last {option} days
              </option>
            ))}
          </select>
        )}
      </Field>
      <DataTable
        data-testid="overview-people"
        caption="People by channel"
        rows={rows}
        rowKey={([platform]) => platform}
        columns={[
          {
            key: "channel",
            header: "Channel",
            cell: ([platform]) => platformLabel(platform),
          },
          { key: "total", header: "People", cell: ([, v]) => v.total },
          { key: "linked", header: "Linked", cell: ([, v]) => v.linked },
          {
            key: "many",
            header: "Outreach only",
            cell: ([, v]) => v.many_only,
          },
          { key: "chat", header: "Chat only", cell: ([, v]) => v.saas_only },
          {
            key: "review",
            header: "Needs review",
            cell: ([, v]) => v.conflict,
          },
        ]}
      />
      <dl className="contacts-list" data-testid="overview-numbers">
        <div>
          <dt>Chat inbox</dt>
          <dd>
            {data.chat.conversations} conversations ({data.chat.handoffs} handed
            to a person), {data.chat.messages.visitor} visitor,{" "}
            {data.chat.messages.ai} bot and {data.chat.messages.agent} agent
            messages; {data.chat.new_contacts} new contacts.
          </dd>
        </div>
        <div>
          <dt>Bot usage</dt>
          <dd>
            {data.ai.calls} calls, {data.ai.tokens.toLocaleString("en-GB")}{" "}
            tokens. Cost: {costText(data.ai.calls_with_cost, data.ai.cost_usd)}.
          </dd>
        </div>
        <div>
          <dt>Outreach service</dt>
          <dd>
            {data.people.known_to_outreach} people known. Not available here:{" "}
            {data.not_available.join("; ")}.
          </dd>
        </div>
      </dl>
    </Card>
  );
}
