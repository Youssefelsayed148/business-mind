/** Shapes of the Many rows the staff pages read (copied from the old dashboard's lib/types.ts). */

export type Platform = "instagram" | "whatsapp" | "facebook" | string;

export interface ManyCampaign {
  id: string;
  name: string;
  status?: string;
}

export interface ManyInstagramAccount {
  id: string;
  username?: string | null;
  ig_user_id: string;
}

export interface ManyLead {
  id: string;
  username?: string | null;
  ig_user_id: string;
  lead_source?: string | null;
  platform?: Platform | null;
  source_campaign_id?: string | null;
  source_campaign?: string | null;
  keyword?: string | null;
  instagram_account_id?: string | null;
  instagram_account_username?: string | null;
  whatsapp_account_username?: string | null;
  facebook_page_username?: string | null;
  first_seen?: string | null;
  captured_at?: string | null;
}

export interface ManyMessage {
  id: string;
  campaign_id?: string | null;
  lead_id: string;
  comment_id?: string | null;
  status: string;
  message_type?: string | null;
  error_message?: string | null;
  trigger_keyword?: string | null;
  retryable: boolean;
  retry_count: number;
  created_at?: string | null;
}

export interface ManyLog {
  id: string;
  level: string;
  campaign_id?: string | null;
  campaign?: string | null;
  event_type: string;
  message: string;
  metadata: Record<string, unknown>;
  actor_email?: string | null;
  entity_name?: string | null;
  created_at?: string | null;
}

export interface ManyConversation {
  id: string;
  lead_id: string;
  lead_username?: string | null;
  lead_source?: string | null;
  platform?: Platform | null;
  campaign_id?: string | null;
  campaign_name?: string | null;
  /** True when the channel is delegated to the shared inbox: Many must not act on it. */
  managed_by_saas?: boolean;
  /** Optional: the organization that owns the delegated channel, when Many says so. */
  tenant_id?: string | null;
  status: string;
  turn_count: number;
  last_message_at?: string | null;
}

export interface ManyConversationMessage {
  id: string;
  direction: "inbound" | "outbound" | null;
  content?: string | null;
  status: string;
  created_at?: string | null;
}

export type ManyConversationDetail = ManyConversation & {
  messages: ManyConversationMessage[];
};
