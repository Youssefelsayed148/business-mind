"use client";

import { Field, Select } from "@/components/ui/Field";
import type { Campaign, InstagramAccount } from "@/lib/types";

export function LeadFilters({
  campaigns,
  accounts,
  campaignId,
  accountId,
  platform,
  search,
  onChange,
}: {
  campaigns: Campaign[];
  accounts: InstagramAccount[];
  campaignId: string;
  accountId: string;
  platform: string;
  search: string;
  onChange: (next: { campaignId: string; accountId: string; platform: string; search: string }) => void;
}) {
  return (
    <div className="grid gap-4 md:grid-cols-4">
      <Select
        label="Platform"
        value={platform}
        onChange={(e) => onChange({ campaignId, accountId, platform: e.target.value, search })}
      >
        <option value="">All platforms</option>
        <option value="instagram">Instagram</option>
        <option value="whatsapp">WhatsApp</option>
        <option value="facebook">Facebook</option>
      </Select>
      <Select label="Campaign" value={campaignId} onChange={(e) => onChange({ campaignId: e.target.value, accountId, platform, search })}>
        <option value="">All campaigns</option>
        {campaigns.map((campaign) => <option key={campaign.id} value={campaign.id}>{campaign.name}</option>)}
      </Select>
      <Select label="Instagram Account" value={accountId} onChange={(e) => onChange({ campaignId, accountId: e.target.value, platform, search })}>
        <option value="">All accounts</option>
        {accounts.map((account) => (
          <option key={account.id} value={account.id}>
            {account.username || account.ig_user_id}
          </option>
        ))}
      </Select>
      <Field label="Search username" value={search} onChange={(e) => onChange({ campaignId, accountId, platform, search: e.target.value })} />
    </div>
  );
}
