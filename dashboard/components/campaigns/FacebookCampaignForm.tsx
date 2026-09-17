"use client";

import { FormEvent, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Field, Select, TextArea } from "@/components/ui/Field";
import { Panel } from "@/components/ui/Panel";
import { api } from "@/lib/api";
import { useToast } from "@/components/ToastProvider";
import type { FacebookCampaign, FacebookPage } from "@/lib/types";

/** Deliberately separate from CampaignForm.tsx (Instagram's) rather than a
 * shared component — per the design doc, Facebook's fields diverge enough
 * (post_id instead of media_id, no follow-prompt fields at all per the
 * multi-platform expansion's Phase 3 research spike) that forcing a shared
 * form would need heavy conditional logic for no real benefit. */
export function FacebookCampaignForm({
  pages,
  campaign,
  onSaved,
  onCancel,
}: {
  pages: FacebookPage[];
  campaign?: FacebookCampaign | null;
  onSaved: () => void;
  onCancel: () => void;
}) {
  const [form, setForm] = useState({
    facebook_page_id: campaign?.facebook_page_id ? String(campaign.facebook_page_id) : pages[0]?.id ? String(pages[0].id) : "",
    name: campaign?.name || "",
    match_type: campaign?.match_type || "contains",
    message_template: campaign?.message_template || "",
    target_post_id: campaign?.target_post_id || "",
    cooldown_hours: campaign?.cooldown_hours ?? 168,
    comment_reply_enabled: campaign?.comment_reply_enabled || false,
    comment_reply_text: campaign?.comment_reply_text || "",
    ai_enabled: campaign?.ai_enabled || false,
    keywords: campaign?.keywords.map((k) => k.normalized_keyword).join(", ") || "",
  });
  const [saving, setSaving] = useState(false);
  const toast = useToast();

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!form.facebook_page_id) {
      toast.error("Connect a Facebook Page first.");
      return;
    }
    setSaving(true);
    try {
      const keywords = form.keywords
        .split(",")
        .map((k) => k.trim().toLowerCase())
        .filter(Boolean);

      if (campaign) {
        await api.patch(`/facebook/campaigns/${campaign.id}`, {
          name: form.name,
          match_type: form.match_type,
          message_template: form.message_template,
          target_scope: form.target_post_id ? "specific_post" : "any_post",
          target_post_id: form.target_post_id || null,
          cooldown_hours: form.cooldown_hours,
          comment_reply_enabled: form.comment_reply_enabled,
          comment_reply_text: form.comment_reply_text || null,
          ai_enabled: form.ai_enabled,
        });
        // Keyword diffing is out of scope for this lean editor — keywords
        // are only settable at creation time; use the campaign list's
        // per-keyword delete plus re-add for edits.
      } else {
        await api.post("/facebook/campaigns", {
          facebook_page_id: form.facebook_page_id,
          name: form.name,
          match_type: form.match_type,
          message_template: form.message_template,
          target_scope: form.target_post_id ? "specific_post" : "any_post",
          target_post_id: form.target_post_id || null,
          cooldown_hours: form.cooldown_hours,
          comment_reply_enabled: form.comment_reply_enabled,
          comment_reply_text: form.comment_reply_text || null,
          ai_enabled: form.ai_enabled,
          keywords,
        });
      }
      toast.success(campaign ? "Campaign updated." : "Campaign created.");
      onSaved();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to save campaign");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Panel>
      <form onSubmit={submit} className="grid gap-4">
        <div className="grid gap-4 md:grid-cols-2">
          <Select
            label="Facebook Page"
            value={form.facebook_page_id}
            disabled={!!campaign}
            required
            onChange={(e) => setForm((f) => ({ ...f, facebook_page_id: e.target.value }))}
          >
            {pages.map((page) => (
              <option key={page.id} value={page.id}>
                {page.page_name || page.page_id}
              </option>
            ))}
          </Select>
          <Field
            label="Campaign name"
            value={form.name}
            required
            onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
          />
        </div>

        <div className="grid gap-4 md:grid-cols-2">
          <Select
            label="Match type"
            value={form.match_type}
            onChange={(e) => setForm((f) => ({ ...f, match_type: e.target.value }))}
          >
            <option value="contains">Contains</option>
            <option value="exact">Exact</option>
            <option value="starts_with">Starts with</option>
          </Select>
          <Field
            label="Target post ID (optional)"
            hint="Leave blank to match comments on any post."
            value={form.target_post_id}
            onChange={(e) => setForm((f) => ({ ...f, target_post_id: e.target.value }))}
          />
        </div>

        {!campaign ? (
          <Field
            label="Trigger keywords (comma-separated)"
            hint="e.g. promo, discount, price"
            value={form.keywords}
            onChange={(e) => setForm((f) => ({ ...f, keywords: e.target.value }))}
          />
        ) : null}

        <TextArea
          label="Private reply message"
          hint="Sent once, via a private reply to the matching comment. Meta allows exactly one per comment."
          rows={4}
          value={form.message_template}
          onChange={(e) => setForm((f) => ({ ...f, message_template: e.target.value }))}
        />

        <Field
          label="Cooldown (hours)"
          type="number"
          min={0}
          value={form.cooldown_hours}
          onChange={(e) => setForm((f) => ({ ...f, cooldown_hours: Number(e.target.value) }))}
        />

        <label className="flex items-start gap-2 rounded-lg border border-line/70 bg-slate-50/60 p-3 text-sm text-ink">
          <input
            type="checkbox"
            checked={form.comment_reply_enabled}
            onChange={(e) => setForm((f) => ({ ...f, comment_reply_enabled: e.target.checked }))}
            className="mt-0.5 h-4 w-4 rounded border-line accent-accent"
          />
          <span>
            <span className="font-semibold">Also post a public comment reply</span>
            <span className="mt-0.5 block text-xs text-muted">Sent right after the private reply succeeds.</span>
          </span>
        </label>
        {form.comment_reply_enabled ? (
          <Field
            label="Public comment reply text"
            value={form.comment_reply_text}
            onChange={(e) => setForm((f) => ({ ...f, comment_reply_text: e.target.value }))}
          />
        ) : null}

        <label className="flex items-start gap-2 rounded-lg border border-line/70 bg-slate-50/60 p-3 text-sm text-ink">
          <input
            type="checkbox"
            checked={form.ai_enabled}
            onChange={(e) => setForm((f) => ({ ...f, ai_enabled: e.target.checked }))}
            className="mt-0.5 h-4 w-4 rounded border-line accent-accent"
          />
          <span>
            <span className="font-semibold">Let AI continue the conversation</span>
            <span className="mt-0.5 block text-xs text-muted">
              If the lead replies in Messenger after the private reply, the AI assistant continues the thread
              (uses the Page&apos;s AI settings — business profile, tone, budget).
            </span>
          </span>
        </label>

        <div className="flex justify-end gap-2">
          <Button type="button" variant="secondary" onClick={onCancel}>
            Cancel
          </Button>
          <Button type="submit" disabled={saving}>
            {saving ? "Saving..." : campaign ? "Save changes" : "Create campaign"}
          </Button>
        </div>
      </form>
    </Panel>
  );
}
