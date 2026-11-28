/**
 * WhatsApp outreach types and pure helpers, copied from the old Many dashboard
 * (`dashboard/lib/whatsapp.ts`) and extended with the small pure helpers the pages share
 * (Phase 4C). No imports: the unit tests load this file on its own.
 */

export type WhatsappAccount = {
  id: string;
  phone_number_id: string;
  display_phone_number?: string | null;
  whatsapp_business_account_id?: string | null;
  status?: string | null;
};

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

export type VariableSpec = {
  source: string;
  value?: string;
  fallback?: string;
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

/** A status or source word in plain English ("opted_in" -> "Opted In"). */
export function statusLabel(value?: string | null) {
  if (!value) return "Unknown";
  return value.replaceAll("_", " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

/** Badge tone for a status word (the StatusBadge tones). */
export function statusTone(
  value: string,
): "neutral" | "success" | "warning" | "danger" | "info" {
  const tones: Record<
    string,
    "neutral" | "success" | "warning" | "danger" | "info"
  > = {
    opted_in: "success",
    approved: "success",
    active: "success",
    completed: "success",
    running: "success",
    opted_out: "danger",
    rejected: "danger",
    failed: "danger",
    cancelled: "danger",
    disabled: "danger",
    paused: "warning",
    pending: "warning",
    scheduled: "info",
    draft: "info",
    unknown: "neutral",
  };
  return tones[value] ?? "neutral";
}

/** The numbers of `{{1}}`-style placeholders in a text, unique and ascending. */
export function placeholderIndexes(text: string): number[] {
  return Array.from(
    new Set(
      Array.from(text.matchAll(/{{\s*(\d+)\s*}}/g), (match) =>
        Number(match[1]),
      ),
    ),
  ).sort((a, b) => a - b);
}

/** The text with each placeholder replaced by its example (or left as it is). */
export function renderPreview(
  text: string,
  examples: Record<number, string>,
): string {
  return text.replace(
    /{{\s*(\d+)\s*}}/g,
    (_, n) => examples[Number(n)] || `{{${n}}}`,
  );
}

/** The placeholder numbers used by all the text of a template. */
export function templateIndexes(template?: {
  components: TemplateComponent[];
}): number[] {
  return placeholderIndexes(
    template?.components.map((c) => c.text || "").join(" ") || "",
  );
}

/** A template name as Meta wants it: lowercase letters, digits and underscores. */
export function normalizeTemplateName(value: string): string {
  return value.toLowerCase().replace(/[^a-z0-9_]/g, "_");
}

/** Comma-separated keywords to a clean list (no blanks). */
export function parseKeywords(value: string): string[] {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

/** The example values saved in a BODY component (`example.body_text`), by placeholder number. */
export function exampleValues(
  component: TemplateComponent | undefined,
  indexes: number[],
): Record<number, string> {
  const example = component?.example as { body_text?: unknown } | undefined;
  const raw = example?.body_text;
  const row = Array.isArray(raw) && Array.isArray(raw[0]) ? raw[0] : raw;
  if (!Array.isArray(row)) return {};
  const out: Record<number, string> = {};
  indexes.forEach((n, position) => {
    const item = row[position];
    if (typeof item === "string" && item) out[n] = item;
  });
  return out;
}

/** How fresh the stored health check is. */
export function healthFreshness(ageSeconds?: number | null): string {
  if (ageSeconds == null) return "Never checked";
  if (ageSeconds < 300) return "Fresh";
  if (ageSeconds < 1800) return "A few minutes old";
  return "Stale";
}

/** Has every placeholder a non-blank mapping? (the dry-run needs all of them). */
export function mappingComplete(
  indexes: number[],
  mapping: Record<number, VariableSpec>,
): boolean {
  return indexes.every((i) => {
    const spec = mapping[i];
    if (!spec) return false;
    return spec.source === "literal"
      ? Boolean(spec.value?.trim())
      : Boolean(spec.fallback?.trim());
  });
}

/** Campaign states that no longer change (the detail page stops polling). */
export function campaignIsFinal(status: string): boolean {
  return ["completed", "cancelled", "failed"].includes(status);
}
