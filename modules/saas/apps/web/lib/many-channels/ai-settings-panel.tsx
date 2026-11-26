"use client";

import { useState } from "react";

import { manyRequest, type ManyScope } from "@/lib/many";
import { Button, Field } from "@/lib/ui";

import type { ChannelNote } from "./connect-buttons";
import type { AiSettingsFields, AiSettingsPayload } from "./types";

/**
 * The "AI conversation assistant" settings of one Facebook Page or WhatsApp number
 * (PATCH <platform>/accounts/<id>/ai-settings, channels.connect: Admin and Owner).
 * Others see the values read-only. Only Facebook has the "unsolicited DMs" opt-in.
 */
export function AiSettingsPanel({
  scope,
  platform,
  accountId,
  account,
  canManage,
  onSaved,
  onNote,
}: {
  scope: ManyScope;
  platform: "facebook" | "whatsapp";
  accountId: string;
  account: AiSettingsFields;
  canManage: boolean;
  onSaved: () => void;
  onNote: (note: ChannelNote) => void;
}) {
  const isFacebook = platform === "facebook";
  const [form, setForm] = useState<AiSettingsPayload>({
    business_vertical: account.business_vertical || "general",
    ai_enabled: account.ai_enabled ?? false,
    ...(isFacebook
      ? { ai_cold_dm_enabled: account.ai_cold_dm_enabled ?? false }
      : {}),
    ai_business_profile: account.ai_business_profile ?? "",
    ai_tone_instructions: account.ai_tone_instructions ?? "",
    ai_daily_message_cap: account.ai_daily_message_cap ?? 100,
  });
  const [saving, setSaving] = useState(false);

  async function save() {
    setSaving(true);
    try {
      await manyRequest(
        scope,
        "PATCH",
        `${platform}/accounts/${encodeURIComponent(accountId)}/ai-settings`,
        form,
      );
      onNote({ tone: "info", text: "AI settings saved." });
      onSaved();
    } catch (caught) {
      onNote({
        tone: "error",
        text:
          caught instanceof Error && caught.message
            ? caught.message
            : "Could not save the AI settings.",
      });
    } finally {
      setSaving(false);
    }
  }

  return (
    <section
      className="mc-panel"
      data-testid={`ai-settings-${accountId}`}
      aria-label="AI conversation assistant"
    >
      <header className="mc-panel-head">
        <div>
          <h3>AI conversation assistant</h3>
          <p className="field-hint">
            {isFacebook
              ? "Shared across all campaigns on this Page. Used once a lead replies inside a Messenger thread."
              : "Every WhatsApp conversation is reactive: the bot only replies once someone messages this number first."}
          </p>
        </div>
        <label className="mc-check">
          <input
            type="checkbox"
            checked={form.ai_enabled}
            disabled={!canManage}
            onChange={(event) =>
              setForm((f) => ({ ...f, ai_enabled: event.target.checked }))
            }
          />
          Enabled
        </label>
      </header>

      {isFacebook && (
        <label className="mc-check mc-option">
          <input
            type="checkbox"
            checked={form.ai_cold_dm_enabled ?? false}
            disabled={!canManage || !form.ai_enabled}
            onChange={(event) =>
              setForm((f) => ({
                ...f,
                ai_cold_dm_enabled: event.target.checked,
              }))
            }
          />
          <span>
            Also let AI answer unsolicited Messenger messages
            <small className="field-hint">
              Separate opt-in. When on, the AI also replies to people who
              message this Page directly without going through a campaign
              comment.
            </small>
          </span>
        </label>
      )}

      <div className="mc-grid">
        <Field
          label="Business vertical"
          hint="Applies safety rules that cannot be overridden (for example, clinics never give medical advice)."
        >
          {(control) => (
            <select
              {...control}
              value={form.business_vertical}
              disabled={!canManage}
              onChange={(event) =>
                setForm((f) => ({
                  ...f,
                  business_vertical: event.target.value,
                }))
              }
            >
              <option value="general">General</option>
              <option value="restaurant">Restaurant</option>
              <option value="real_estate">Real estate</option>
              <option value="clinical">Clinical</option>
            </select>
          )}
        </Field>
        <Field
          label="Daily message cap"
          hint={`${isFacebook ? "Shared budget across all campaigns on this Page. " : ""}Sent today: ${account.ai_messages_sent_today ?? 0}.`}
        >
          {(control) => (
            <input
              {...control}
              type="number"
              min={0}
              max={5000}
              value={form.ai_daily_message_cap}
              disabled={!canManage}
              onChange={(event) =>
                setForm((f) => ({
                  ...f,
                  ai_daily_message_cap: Number(event.target.value),
                }))
              }
            />
          )}
        </Field>
      </div>

      <Field
        label="Business profile"
        hint="Facts the AI should know: what the business offers, hours, delivery area, who to contact. Be specific."
      >
        {(control) => (
          <textarea
            {...control}
            dir="auto"
            rows={5}
            value={form.ai_business_profile}
            disabled={!canManage}
            onChange={(event) =>
              setForm((f) => ({
                ...f,
                ai_business_profile: event.target.value,
              }))
            }
          />
        )}
      </Field>

      <Field
        label="Tone and style (optional)"
        hint="For example: friendly and casual, emojis sparingly."
      >
        {(control) => (
          <textarea
            {...control}
            dir="auto"
            rows={2}
            value={form.ai_tone_instructions}
            disabled={!canManage}
            onChange={(event) =>
              setForm((f) => ({
                ...f,
                ai_tone_instructions: event.target.value,
              }))
            }
          />
        )}
      </Field>

      {canManage && (
        <div className="mc-actions">
          <Button
            data-testid="save-ai-settings"
            disabled={saving}
            onClick={() => void save()}
          >
            {saving ? "Saving..." : "Save AI settings"}
          </Button>
        </div>
      )}
    </section>
  );
}
