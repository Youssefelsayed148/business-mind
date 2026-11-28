"use client";

import { useEffect, useState } from "react";

import * as api from "./api";
import type { CustomerLink } from "./api";
import {
  platformLabel,
  stateHelp,
  stateLabel,
  stateTone,
} from "./customer-links";
import { roleSatisfies, useSession } from "./session";
import { Card, StatusBadge } from "./ui";

/** "Channels across systems" for one contact; renders nothing unless the view answers. */
export function ContactChannelLinks({
  tenantId,
  contactId,
}: {
  tenantId: string;
  contactId: string;
}) {
  const { roleIn } = useSession();
  const allowed = roleSatisfies(roleIn(tenantId), "admin");
  const [items, setItems] = useState<CustomerLink[] | null>(null);
  useEffect(() => {
    if (!allowed) return;
    let cancelled = false;
    api
      .contactCustomerLinks(tenantId, contactId)
      .then((result) => !cancelled && setItems(result.items))
      .catch(() => !cancelled && setItems(null));
    return () => {
      cancelled = true;
    };
  }, [tenantId, contactId, allowed]);
  if (!allowed || items === null) return null;
  return (
    <Card title="Channels across systems" data-testid="contact-channel-links">
      {items.length ? (
        <ul className="contacts-list">
          {items.map((link) => (
            <li key={link.id}>
              {platformLabel(link.platform)}{" "}
              <StatusBadge
                value={link.state}
                tone={stateTone(link.state)}
                title={stateHelp(link.state)}
              >
                {stateLabel(link.state)}
              </StatusBadge>
            </li>
          ))}
        </ul>
      ) : (
        <p className="muted">
          No outreach or channel link is recorded for this contact yet.
        </p>
      )}
    </Card>
  );
}
