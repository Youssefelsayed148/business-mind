/** Shapes of Facebook campaign answers from Many (ported from the old dashboard). */

export interface FacebookCampaignKeyword {
  id: string | number;
  normalized_keyword: string;
}

export interface FacebookCampaign {
  id: string | number;
  facebook_page_id: string | number;
  name: string;
  match_type: string;
  message_template: string;
  target_scope?: string;
  target_post_id?: string | null;
  cooldown_hours: number;
  status: string;
  comment_reply_enabled: boolean;
  comment_reply_text?: string | null;
  ai_enabled: boolean;
  total_triggers: number;
  keywords: FacebookCampaignKeyword[];
}

export interface CampaignPage {
  id: string | number;
  page_id: string;
  page_name?: string | null;
}

/** Pure: "Promo, discount ,," becomes ["promo", "discount"]. */
export function parseKeywords(text: string): string[] {
  return text
    .split(",")
    .map((word) => word.trim().toLowerCase())
    .filter(Boolean);
}
