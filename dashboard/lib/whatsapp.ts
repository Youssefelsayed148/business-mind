export type WhatsappContact = {
  id: string;
  whatsapp_account_id: string;
  wa_id: string;
  display_name?: string | null;
  marketing_consent: string;
  consent_source?: string | null;
  consent_at?: string | null;
  opted_out_at?: string | null;
  created_at: string;
};

export type ConsentEvent = {
  id: string;
  event_type: string;
  source: string;
  evidence: Record<string, unknown>;
  actor_user_id?: string | null;
  created_at: string;
};

export type WhatsappContactDetail = WhatsappContact & {
  consent_history: ConsentEvent[];
};

export type TemplateComponent = {
  type: string;
  text?: string;
  example?: unknown;
  [key: string]: unknown;
};
export type WhatsappTemplate = {
  id: string;
  whatsapp_account_id: string;
  name: string;
  language: string;
  category: string;
  status: string;
  components: TemplateComponent[];
  meta_template_id?: string | null;
  rejection_reason?: string | null;
  quality_score?: string | null;
  last_synced_at?: string | null;
  created_at: string;
};

export type WhatsappCampaign = {
  id: string;
  whatsapp_account_id: string;
  template_id: string;
  name: string;
  status: string;
  scheduled_at?: string | null;
  completed_at?: string | null;
  throttle_per_minute: number;
  variable_mapping: Record<string, unknown>;
  total_recipients: number;
  sent_count: number;
  delivered_count: number;
  read_count: number;
  failed_count: number;
  skipped_count: number;
  created_at: string;
};

export type DryRun = {
  eligible: number;
  terminal_skips: { count: number; reasons: Record<string, number> };
  deferrable_blocks: { count: number; reasons: Record<string, number> };
  estimated_days_to_finish: number;
  daily_cap: number;
  used_in_rolling_24h: number;
};

export type CampaignStats = {
  campaign: WhatsappCampaign;
  recipient_statuses: Record<string, number>;
  reasons: Record<string, number>;
  row_count: number;
};

export type OutreachHealth = {
  quality_rating?: string | null;
  messaging_limit_tier?: string | null;
  outreach_paused: boolean;
  outreach_paused_reason?: string | null;
  outreach_paused_at?: string | null;
  health_checked_at?: string | null;
  health_age_seconds?: number | null;
  sent_recipient_count_24h: number;
  daily_cap: number;
  outreach_enabled: boolean;
  ctwa_counts_as_consent: boolean;
  transactional_utility_attested: boolean;
  opt_in_keywords: string[] | null;
  opt_out_keywords: string[] | null;
  outreach_daily_cap: number;
};

export type OutreachSettings = {
  ctwa_counts_as_consent: boolean;
  transactional_utility_attested: boolean;
  opt_out_keywords: string[] | null;
  opt_in_keywords: string[] | null;
  outreach_daily_cap: number;
};

export const reasonLabel = (value: string) =>
  ({
    no_marketing_consent: "No marketing permission",
    opted_out: "Opted out",
    template_not_approved: "Template is not approved",
    variable_unresolved: "A message variable could not be filled",
    daily_cap_reached: "Daily sending cap reached — queued for later",
    outreach_paused: "Outreach is paused",
    quality_red: "Account quality is red",
    health_stale: "Health check is out of date",
    health_unknown: "Account health has not been checked",
    outcome_unknown: "Provider outcome unknown",
  })[value] ??
  value.replaceAll("_", " ").replace(/\b\w/g, (c) => c.toUpperCase());

export function formatDate(value?: string | null) {
  return value ? new Date(value).toLocaleString() : "Not available";
}
