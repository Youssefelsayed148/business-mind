/** Types for the Instagram pages (read from the old dashboard's lib/types.ts). */

export type Id = string;

export type CampaignStatus = "draft" | "active" | "paused" | "archived";
export type TargetScope = "any_media" | "specific_media";
export type TargetMediaType = "post" | "reel" | "story" | "unknown";
export type MatchType = "contains" | "exact" | "starts_with";
export type DeliveryMode = "instant" | "follow_prompt";
export type BusinessVertical =
  "general" | "restaurant" | "real_estate" | "clinical";

export interface CampaignKeyword {
  id: Id;
  campaign_id: Id;
  normalized_keyword: string;
  created_at: string;
}

export interface Campaign {
  id: Id;
  workspace_id: Id;
  instagram_account_id: Id;
  name: string;
  description?: string | null;
  media_id?: string | null;
  media_url?: string | null;
  target_scope: TargetScope;
  target_media_url?: string | null;
  target_media_shortcode?: string | null;
  target_media_id?: string | null;
  target_media_type: TargetMediaType;
  target_media_label?: string | null;
  match_type: MatchType;
  message_template: string;
  link_url?: string | null;
  cooldown_hours: number;
  status: CampaignStatus;
  delivery_mode: DeliveryMode;
  follow_prompt_title?: string | null;
  follow_prompt_description?: string | null;
  follow_prompt_profile_url?: string | null;
  comment_reply_enabled?: boolean;
  comment_reply_text?: string | null;
  total_triggers: number;
  successful_sends: number;
  failed_sends: number;
  ai_enabled?: boolean;
  ai_handoff_after_turns?: number;
  created_at: string;
  updated_at: string;
  keywords: CampaignKeyword[];
}

/** The body of POST /campaigns (the old CampaignPayload). */
export interface CampaignCreateBody {
  instagram_account_id: Id;
  name: string;
  description: string | null;
  media_id: null;
  media_url: string | null;
  target_scope: TargetScope;
  target_media_url: string | null;
  target_media_shortcode: string | null;
  target_media_id: string | null;
  target_media_type: TargetMediaType;
  target_media_label: string | null;
  match_type: MatchType;
  message_template: string;
  link_url: string | null;
  cooldown_hours: number;
  status: "draft";
  keywords: string[];
  delivery_mode: DeliveryMode;
  follow_prompt_title: string | null;
  follow_prompt_description: string | null;
  follow_prompt_profile_url: string | null;
  comment_reply_enabled: boolean;
  comment_reply_text: string | null;
  ai_enabled: boolean;
  ai_handoff_after_turns: number;
}

/** The body of PATCH /campaigns/{id}: the create body without account, status and keywords. */
export type CampaignPatchBody = Omit<
  CampaignCreateBody,
  "instagram_account_id" | "status" | "keywords"
>;

export interface InstagramAccount {
  id: Id;
  ig_user_id: string;
  username?: string | null;
  account_type?: string | null;
  status?: string | null;
  expires_at?: string | null;
  business_vertical?: BusinessVertical | string;
  ai_enabled?: boolean;
  ai_cold_dm_enabled?: boolean;
  ai_business_profile?: string | null;
  ai_tone_instructions?: string | null;
  ai_daily_message_cap?: number;
  ai_messages_sent_today?: number;
  ai_handoff_after_turns?: number;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface AiSettingsBody {
  business_vertical: BusinessVertical;
  ai_enabled: boolean;
  ai_cold_dm_enabled: boolean;
  ai_business_profile: string;
  ai_tone_instructions: string;
  ai_daily_message_cap: number;
}

export interface AccountHealth {
  account_id: string;
  has_token: boolean;
  status: string;
}

export interface InstagramMedia {
  media_id: string;
  caption: string;
  label: string;
  media_type: string;
  media_url?: string | null;
  permalink?: string | null;
  thumbnail_url?: string | null;
  timestamp?: string | null;
}

export interface InstagramMediaResponse {
  account_id: string;
  media: InstagramMedia[];
  next_cursor?: string | null;
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

export interface SimulationResult {
  matched: boolean;
  matched_keyword?: string | null;
  rendered_message?: string | null;
}

export interface CampaignMessage {
  id: Id;
  status: string;
  username?: string | null;
  message_type?: string | null;
  error_message?: string | null;
  sent_at?: string | null;
  created_at?: string | null;
  [key: string]: unknown;
}

export interface CampaignLog {
  id: Id;
  event_type: string;
  message: string;
  metadata: Record<string, unknown>;
  created_at?: string | null;
}

export interface CampaignStats {
  campaign_id: Id;
  name: string;
  status: CampaignStatus;
  created_at?: string | null;
  created_by?: string | null;
  account_username?: string | null;
  account_ig_user_id?: string | null;
  target_scope: TargetScope;
  target_media_label?: string | null;
  target_media_type: TargetMediaType;
  target_media_url?: string | null;
  keywords: string[];
  match_type: MatchType;
  cooldown_hours: number;
  delivery_mode: DeliveryMode;
  message_template: string;
  link_url?: string | null;
  follow_prompt_title?: string | null;
  follow_prompt_description?: string | null;
  follow_prompt_profile_url?: string | null;
  comment_reply_enabled?: boolean;
  comment_reply_text?: string | null;
  last_triggered_at?: string | null;
  new_leads: number;
  total_triggers: number;
  successful_sends: number;
  failed_sends: number;
  expired: number;
  cooldowns: number;
  recent_messages: CampaignMessage[];
  recent_logs: CampaignLog[];
}
