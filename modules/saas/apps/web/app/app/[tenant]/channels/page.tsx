"use client";

import { useParams } from "next/navigation";
import { useMemo, useState } from "react";

import { AccountSection } from "@/lib/many-channels/account-section";
import {
  FacebookConnect,
  WhatsappConnect,
  type ChannelNote,
} from "@/lib/many-channels/connect-buttons";
import type { FacebookPage, WhatsappAccount } from "@/lib/many-channels/types";
import { manyRequest, type ManyScope } from "@/lib/many";
import { orgRoleSatisfies } from "@/lib/org-role";
import { PageState } from "@/lib/page-state";
import { Notice, PageHeader } from "@/lib/ui";
import { useManyData } from "@/lib/use-many";
import { useOrgRole } from "@/lib/use-org-role";

import "@/app/channels-screen-many.css";

interface Accounts {
  whatsapp: WhatsappAccount[];
  facebook: FacebookPage[];
}

/**
 * Facebook Pages and WhatsApp numbers of one organization, through the SaaS proxy.
 * Everyone with channel access reads. Admin connects and disconnects and edits AI and
 * delegation; Owner may delete for good. Instagram is a staff page, not shown here.
 */
export default function ChannelsPage() {
  const params = useParams<{ tenant: string }>();
  const tenantId = params.tenant;
  const scope = useMemo<ManyScope>(
    () => ({ kind: "org", tenantId }),
    [tenantId],
  );
  const { role } = useOrgRole(tenantId);
  const canConnect = orgRoleSatisfies(role, "admin");
  const canHardDelete = orgRoleSatisfies(role, "owner");
  const [note, setNote] = useState<ChannelNote | null>(null);

  const { data, status, reload } = useManyData<Accounts>(async () => {
    const [whatsapp, facebook] = await Promise.all([
      manyRequest<WhatsappAccount[]>(scope, "GET", "whatsapp/accounts"),
      manyRequest<FacebookPage[]>(scope, "GET", "facebook/accounts"),
    ]);
    return { whatsapp, facebook };
  }, tenantId);

  return (
    <>
      <PageHeader
        title="Channels"
        purpose="Facebook Pages and WhatsApp numbers connected to this organization."
      />
      {note && (
        <div data-testid="channels-note">
          <Notice message={note.text} tone={note.tone} scope="item" />
        </div>
      )}
      <PageState status={status} homeHref={`/app/${tenantId}`}>
        {data && (
          <div className="mc-sections" data-testid="channels-page">
            <AccountSection
              scope={scope}
              platform="facebook"
              title="Facebook Pages"
              purpose="Comment-to-message campaigns and AI replies for connected Facebook Pages."
              noun="Page"
              accounts={data.facebook}
              emptyMessage="No Facebook Pages connected yet."
              connectButton={
                <FacebookConnect
                  scope={scope}
                  onConnected={reload}
                  onNote={setNote}
                />
              }
              canConnect={canConnect}
              canDisconnect={canConnect}
              canHardDelete={canHardDelete}
              onChanged={reload}
              onNote={setNote}
            />
            <AccountSection
              scope={scope}
              platform="whatsapp"
              title="WhatsApp numbers"
              purpose="AI replies to inbound WhatsApp messages, within Meta's 24-hour customer service window."
              noun="number"
              accounts={data.whatsapp}
              emptyMessage="No WhatsApp numbers connected yet."
              connectButton={
                <WhatsappConnect
                  scope={scope}
                  onConnected={reload}
                  onNote={setNote}
                />
              }
              canConnect={canConnect}
              canDisconnect={canConnect}
              canHardDelete={canHardDelete}
              onChanged={reload}
              onNote={setNote}
            />
          </div>
        )}
      </PageState>
    </>
  );
}
