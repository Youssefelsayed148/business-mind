export type Id = string;

export type User = {
  id: Id;
  email: string;
  name?: string | null;
  role: string;
};

export type CampaignKeyword = {
  id: Id;
  campaign_id: Id;
  normalized_keyword: string;
  created_at: string;
};

export type Campaign = {
  id: Id;
  workspace_id: Id;
  instagram_account_id: Id;
  name: string;
  description?: string | null;
  media_id?: string | null;
  media_url?: string | null;
  target_scope: "any_media" | "specific_media";
  target_media_url?: string | null;
  target_media_shortcode?: string | null;
  target_media_id?: string | null;
  target_media_type: "post" | "reel" | "story" | "unknown";
  target_media_label?: string | null;
  match_type: "contains" | "exact" | "starts_with";
  message_template: string;
  link_url?: string | null;
  cooldown_hours: number;
  status: "draft" | "active" | "paused" | "archived";
  delivery_mode: "instant" | "follow_prompt";
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
};

export type CampaignPayload = {
  instagram_account_id: Id;
  name: string;
  description?: string | null;
  media_id?: string | null;
  media_url?: string | null;
  target_scope: "any_media" | "specific_media";
  target_media_url?: string | null;
  target_media_shortcode?: string | null;
  target_media_id?: string | null;
  target_media_type: "post" | "reel" | "story" | "unknown";
  target_media_label?: string | null;
  match_type: "contains" | "exact" | "starts_with";
  message_template: string;
  link_url?: string | null;
  cooldown_hours: number;
  status: "draft" | "active" | "paused";
  keywords: string[];
  delivery_mode: "instant" | "follow_prompt";
  follow_prompt_title?: string | null;
  follow_prompt_description?: string | null;
  follow_prompt_profile_url?: string | null;
  comment_reply_enabled?: boolean;
  comment_reply_text?: string | null;
  ai_enabled?: boolean;
  ai_handoff_after_turns?: number;
};

export type InstagramAccount = {
  id: Id;
  ig_user_id: string;
  username?: string | null;
  account_type?: string | null;
  status?: string | null;
  expires_at?: string | null;
  business_vertical?: "general" | "restaurant" | "real_estate" | "clinical" | string;
  ai_enabled?: boolean;
  ai_cold_dm_enabled?: boolean;
  ai_business_profile?: string | null;
  ai_tone_instructions?: string | null;
  ai_daily_message_cap?: number;
  ai_messages_sent_today?: number;
  ai_handoff_after_turns?: number;
  created_at?: string | null;
  updated_at?: string | null;
};

export type AISettingsPayload = {
  business_vertical?: "general" | "restaurant" | "real_estate" | "clinical";
  ai_enabled?: boolean;
  ai_cold_dm_enabled?: boolean;
  ai_business_profile?: string | null;
  ai_tone_instructions?: string | null;
  ai_daily_message_cap?: number;
};

export type LeadSource = "campaign" | "cold_dm" | string;

export type Conversation = {
  id: Id;
  lead_id: Id;
  lead_username?: string | null;
  lead_source?: LeadSource | null;
  campaign_id?: Id | null;
  campaign_name?: string | null;
  instagram_account_id: Id;
  status: "bot_active" | "handed_off" | "closed" | string;
  handoff_reason?: string | null;
  turn_count: number;
  last_message_at?: string | null;
  last_message_preview?: string | null;
  created_at?: string | null;
};

export type ConversationMessage = {
  id: Id;
  direction: "inbound" | "outbound" | null;
  content?: string | null;
  status: string;
  error_message?: string | null;
  created_at?: string | null;
};

export type ConversationDetail = Conversation & {
  messages: ConversationMessage[];
};

export type OverviewStats = {
  active_campaigns: number;
  triggers_today: number;
  messages_sent_today: number;
  failed_messages_today: number;
  new_leads_today: number;
};

export type ActivityLog = {
  id: Id;
  level: string;
  campaign_id?: Id | null;
  campaign?: string | null;
  event_type: string;
  message: string;
  metadata: Record<string, unknown>;
  actor_email?: string | null;
  entity_type?: string | null;
  entity_name?: string | null;
  severity?: string | null;
  created_at?: string | null;
};

export type Lead = {
  id: Id;
  username?: string | null;
  ig_user_id: string;
  lead_source?: LeadSource | null;
  source_campaign_id?: Id | null;
  source_campaign?: string | null;
  source_media_id?: string | null;
  source_media_type?: string | null;
  source_media_label?: string | null;
  keyword?: string | null;
  instagram_account_id?: Id | null;
  instagram_account_username?: string | null;
  tags: string[];
  first_seen?: string | null;
  last_seen?: string | null;
  captured_at?: string | null;
};

export type Message = {
  id: Id;
  campaign_id: Id;
  lead_id: Id;
  comment_id?: Id | null;
  source_media_id?: string | null;
  source_media_type?: string | null;
  source_media_label?: string | null;
  status: string;
  rendered_body?: string | null;
  message_type?: "follow_prompt" | "final_delivery" | "ai_conversation" | string | null;
  direction?: "inbound" | "outbound" | null;
  conversation_id?: Id | null;
  provider_message_id?: string | null;
  error_code?: string | null;
  error_message?: string | null;
  trigger_keyword?: string | null;
  username?: string | null;
  sent_at?: string | null;
  retryable: boolean;
  retry_count: number;
  created_at?: string | null;
};

export type CampaignStats = {
  campaign_id: Id;
  name: string;
  status: Campaign["status"];
  created_at?: string | null;
  created_by?: string | null;
  account_username?: string | null;
  account_ig_user_id?: string | null;
  target_scope: Campaign["target_scope"];
  target_media_label?: string | null;
  target_media_type: Campaign["target_media_type"];
  target_media_url?: string | null;
  keywords: string[];
  match_type: Campaign["match_type"];
  cooldown_hours: number;
  delivery_mode: Campaign["delivery_mode"];
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
  recent_messages: Message[];
  recent_logs: ActivityLog[];
};

export type SimulationResult = {
  matched: boolean;
  matched_keyword?: string | null;
  rendered_message?: string | null;
};

export type InstagramMedia = {
  media_id: string;
  caption: string;
  label: string;
  media_type: string;
  media_url?: string | null;
  permalink?: string | null;
  thumbnail_url?: string | null;
  timestamp?: string | null;
};

export type InstagramMediaResponse = {
  account_id: string;
  media: InstagramMedia[];
  next_cursor?: string | null;
};
