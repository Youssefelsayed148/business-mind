/** Shapes of the Facebook and WhatsApp account answers from Many (ported from the old dashboard). */

export type BusinessVertical =
  "general" | "restaurant" | "real_estate" | "clinical";

export interface AiSettingsFields {
  business_vertical?: BusinessVertical | string;
  ai_enabled?: boolean;
  ai_cold_dm_enabled?: boolean;
  ai_business_profile?: string | null;
  ai_tone_instructions?: string | null;
  ai_daily_message_cap?: number;
  ai_messages_sent_today?: number;
}

export interface WhatsappAccount extends AiSettingsFields {
  id: string | number;
  phone_number_id: string;
  display_phone_number?: string | null;
  status?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface FacebookPage extends AiSettingsFields {
  id: string | number;
  page_id: string;
  page_name?: string | null;
  status?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface AiSettingsPayload {
  business_vertical: string;
  ai_enabled: boolean;
  ai_cold_dm_enabled?: boolean;
  ai_business_profile: string;
  ai_tone_instructions: string;
  ai_daily_message_cap: number;
}

export interface SaasDelegationConfig {
  saas_delegation_enabled: boolean;
  saas_connection_id: string | null;
  saas_base_url: string | null;
  secret_set: boolean;
  previous_secret_active: boolean;
  previous_secret_expires_at: string | null;
  last_forward_status: string | null;
  last_forward_at: string | null;
  queue_depth: number | null;
  failed_events: number | null;
  retryable_failed_events: number | null;
  degraded: boolean;
}

export type SaasDelegationRetryResult = SaasDelegationConfig & {
  requeued: number;
};

/** A plain date and time, or a fallback; never "Invalid Date". */
export function formatWhen(value: string | null | undefined): string {
  if (!value) return "Not available";
  const time = new Date(value);
  return Number.isNaN(time.getTime()) ? "Not available" : time.toLocaleString();
}
