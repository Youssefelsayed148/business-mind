"use client";

import { useState, type FormEvent } from "react";

import { manyRequest, type ManyScope } from "@/lib/many";
import { Button, Card, Field, Notice, Switch } from "@/lib/ui";

import {
  parseKeywords,
  type CampaignPage,
  type FacebookCampaign,
  type FacebookCampaignKeyword,
} from "./types";

function errorText(caught: unknown, fallback: string): string {
  return caught instanceof Error && caught.message ? caught.message : fallback;
}

/**
 * Create or edit one Facebook comment-to-message campaign (POST or PATCH
 * facebook/campaigns, campaigns.manage: Manager and above). When editing, keywords are
 * added and removed one at a time (POST facebook/campaigns/<id>/keywords with {keyword},
 * DELETE .../keywords/<keyword id>); when creating they are one comma-separated field.
 * The old editor had no keyword editing after creation; this adds it with the same routes.
 */
export function FacebookCampaignForm({
  scope,
  pages,
  campaign,
  onSaved,
  onCancel,
  onKeywordsChanged,
}: {
  scope: ManyScope;
  pages: CampaignPage[];
  campaign: FacebookCampaign | null;
  onSaved: () => void;
  onCancel: () => void;
  onKeywordsChanged: () => void;
}) {
  const [form, setForm] = useState({
    facebook_page_id: campaign?.facebook_page_id
      ? String(campaign.facebook_page_id)
      : pages[0]
        ? String(pages[0].id)
        : "",
    name: campaign?.name ?? "",
    match_type: campaign?.match_type ?? "contains",
    message_template: campaign?.message_template ?? "",
    target_post_id: campaign?.target_post_id ?? "",
    cooldown_hours: campaign?.cooldown_hours ?? 168,
    comment_reply_enabled: campaign?.comment_reply_enabled ?? false,
    comment_reply_text: campaign?.comment_reply_text ?? "",
    ai_enabled: campaign?.ai_enabled ?? false,
    keywords: "",
  });
  const [keywords, setKeywords] = useState<FacebookCampaignKeyword[]>(
    campaign?.keywords ?? [],
  );
  const [newKeyword, setNewKeyword] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function set<K extends keyof typeof form>(key: K, value: (typeof form)[K]) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    if (!form.facebook_page_id) {
      setError("Connect a Facebook Page first.");
      return;
    }
    if (!form.name.trim()) {
      setError("Give the campaign a name.");
      return;
    }
    setSaving(true);
    try {
      const shared = {
        name: form.name,
        match_type: form.match_type,
        message_template: form.message_template,
        target_scope: form.target_post_id ? "specific_post" : "any_post",
        target_post_id: form.target_post_id || null,
        cooldown_hours: form.cooldown_hours,
        comment_reply_enabled: form.comment_reply_enabled,
        comment_reply_text: form.comment_reply_text || null,
        ai_enabled: form.ai_enabled,
      };
      if (campaign) {
        await manyRequest(
          scope,
          "PATCH",
          `facebook/campaigns/${encodeURIComponent(String(campaign.id))}`,
          shared,
        );
      } else {
        await manyRequest(scope, "POST", "facebook/campaigns", {
          facebook_page_id: form.facebook_page_id,
          ...shared,
          keywords: parseKeywords(form.keywords),
        });
      }
      onSaved();
    } catch (caught) {
      setError(errorText(caught, "Could not save the campaign."));
    } finally {
      setSaving(false);
    }
  }

  async function addKeyword() {
    if (!campaign) return;
    const keyword = newKeyword.trim();
    if (!keyword) return;
    setError(null);
    try {
      const created = await manyRequest<FacebookCampaignKeyword>(
        scope,
        "POST",
        `facebook/campaigns/${encodeURIComponent(String(campaign.id))}/keywords`,
        { keyword },
      );
      setKeywords((current) => [...current, created]);
      setNewKeyword("");
      onKeywordsChanged();
    } catch (caught) {
      setError(errorText(caught, "Could not add the keyword."));
    }
  }

  async function removeKeyword(keyword: FacebookCampaignKeyword) {
    if (!campaign) return;
    setError(null);
    try {
      await manyRequest(
        scope,
        "DELETE",
        `facebook/campaigns/${encodeURIComponent(String(campaign.id))}/keywords/${encodeURIComponent(String(keyword.id))}`,
      );
      setKeywords((current) => current.filter((row) => row.id !== keyword.id));
      onKeywordsChanged();
    } catch (caught) {
      setError(errorText(caught, "Could not remove the keyword."));
    }
  }

  return (
    <Card
      title={campaign ? "Edit campaign" : "New campaign"}
      data-testid="campaign-form"
    >
      <form onSubmit={(event) => void submit(event)} className="mf-form">
        {error && <Notice message={error} tone="error" scope="item" />}
        <div className="mf-grid">
          <Field label="Facebook Page" required>
            {(control) => (
              <select
                {...control}
                value={form.facebook_page_id}
                disabled={!!campaign}
                onChange={(event) =>
                  set("facebook_page_id", event.target.value)
                }
              >
                {pages.map((page) => (
                  <option key={String(page.id)} value={String(page.id)}>
                    {page.page_name || page.page_id}
                  </option>
                ))}
              </select>
            )}
          </Field>
          <Field label="Campaign name" required>
            {(control) => (
              <input
                {...control}
                dir="auto"
                value={form.name}
                onChange={(event) => set("name", event.target.value)}
              />
            )}
          </Field>
          <Field label="Match type">
            {(control) => (
              <select
                {...control}
                value={form.match_type}
                onChange={(event) => set("match_type", event.target.value)}
              >
                <option value="contains">Contains</option>
                <option value="exact">Exact</option>
                <option value="starts_with">Starts with</option>
              </select>
            )}
          </Field>
          <Field
            label="Target post ID (optional)"
            hint="Leave blank to match comments on any post."
          >
            {(control) => (
              <input
                {...control}
                dir="ltr"
                value={form.target_post_id}
                onChange={(event) => set("target_post_id", event.target.value)}
              />
            )}
          </Field>
        </div>

        {campaign ? (
          <div className="field" data-testid="keyword-editor">
            <span className="field-label">Trigger keywords</span>
            <ul className="mf-keywords">
              {keywords.map((keyword) => (
                <li key={String(keyword.id)} className="mf-keyword">
                  <span dir="auto">{keyword.normalized_keyword}</span>
                  <button
                    type="button"
                    className="quiet-button"
                    aria-label={`Remove keyword ${keyword.normalized_keyword}`}
                    onClick={() => void removeKeyword(keyword)}
                  >
                    Remove
                  </button>
                </li>
              ))}
            </ul>
            <div className="mf-add-keyword">
              <input
                dir="auto"
                aria-label="New keyword"
                value={newKeyword}
                onChange={(event) => setNewKeyword(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") {
                    event.preventDefault();
                    void addKeyword();
                  }
                }}
              />
              <Button
                variant="quiet"
                data-testid="add-keyword"
                disabled={!newKeyword.trim()}
                onClick={() => void addKeyword()}
              >
                Add keyword
              </Button>
            </div>
          </div>
        ) : (
          <Field
            label="Trigger keywords (comma-separated)"
            hint="For example: promo, discount, price"
          >
            {(control) => (
              <input
                {...control}
                dir="auto"
                value={form.keywords}
                onChange={(event) => set("keywords", event.target.value)}
              />
            )}
          </Field>
        )}

        <Field
          label="Private reply message"
          hint="Sent once, as a private reply to the matching comment. Meta allows exactly one per comment."
        >
          {(control) => (
            <textarea
              {...control}
              dir="auto"
              rows={4}
              value={form.message_template}
              onChange={(event) => set("message_template", event.target.value)}
            />
          )}
        </Field>

        <Field label="Cooldown (hours)">
          {(control) => (
            <input
              {...control}
              type="number"
              min={0}
              value={form.cooldown_hours}
              onChange={(event) =>
                set("cooldown_hours", Number(event.target.value))
              }
            />
          )}
        </Field>

        <Switch
          label="Also post a public comment reply"
          hint="Sent right after the private reply succeeds."
          checked={form.comment_reply_enabled}
          onChange={(next) => set("comment_reply_enabled", next)}
        />
        {form.comment_reply_enabled && (
          <Field label="Public comment reply text">
            {(control) => (
              <input
                {...control}
                dir="auto"
                value={form.comment_reply_text}
                onChange={(event) =>
                  set("comment_reply_text", event.target.value)
                }
              />
            )}
          </Field>
        )}

        <Switch
          label="Let AI continue the conversation"
          hint="If the lead replies in Messenger after the private reply, the AI assistant continues the thread, using the Page's AI settings (business profile, tone, budget)."
          checked={form.ai_enabled}
          onChange={(next) => set("ai_enabled", next)}
        />

        <div className="mf-actions">
          <Button variant="quiet" onClick={onCancel}>
            Cancel
          </Button>
          <Button type="submit" data-testid="save-campaign" disabled={saving}>
            {saving
              ? "Saving..."
              : campaign
                ? "Save changes"
                : "Create campaign"}
          </Button>
        </div>
      </form>
    </Card>
  );
}
