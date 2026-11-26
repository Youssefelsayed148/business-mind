import type { ManyLead } from "./types";

export interface LeadFilterValues {
  campaignId: string;
  accountId: string;
  platform: string;
  search: string;
}

export const NO_LEAD_FILTERS: LeadFilterValues = {
  campaignId: "",
  accountId: "",
  platform: "",
  search: "",
};

/**
 * The query string for GET /leads (the same parameters the old page sent). The platform filter
 * is not sent: the old page applied it on the loaded rows.
 */
export function leadsQuery(filters: LeadFilterValues): string {
  const params = new URLSearchParams();
  if (filters.campaignId) params.set("campaign_id", filters.campaignId);
  if (filters.accountId) params.set("instagram_account_id", filters.accountId);
  const search = filters.search.trim();
  if (search) params.set("search", search);
  return params.toString();
}

export function filterLeadsByPlatform(
  leads: ManyLead[],
  platform: string,
): ManyLead[] {
  return platform ? leads.filter((lead) => lead.platform === platform) : leads;
}

/** The account a lead came through, whatever the channel. */
export function leadAccountName(lead: ManyLead): string {
  return (
    lead.instagram_account_username ||
    lead.whatsapp_account_username ||
    lead.facebook_page_username ||
    "Unknown account"
  );
}

export function leadSourceLabel(source?: string | null): string {
  return source === "cold_dm" ? "Cold DM" : "Campaign";
}

export function leadCampaignLabel(lead: ManyLead): string {
  return lead.lead_source === "cold_dm"
    ? "Cold DM"
    : lead.source_campaign || "Unknown campaign";
}
