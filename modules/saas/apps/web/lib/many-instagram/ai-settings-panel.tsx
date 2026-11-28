"use client";

import { useState } from "react";

import { ManyError } from "@/lib/many";
import { Button, Field, Notice, Switch } from "@/lib/ui";

import { staffSend } from "./calls";
import type {
  AiSettingsBody,
  BusinessVertical,
  InstagramAccount,
} from "./types";

const VERTICALS: { value: BusinessVertical; label: string }[] = [
  { value: "general", label: "General" },
  { value: "restaurant", label: "Restaurant" },
  { value: "real_estate", label: "Real estate" },
  { value: "clinical", label: "Clinical" },
];

/** AI conversation assistant settings for one account (PATCH .../ai-settings). */
export function AiSettingsPanel({
  account,
  onSaved,
}: {
  account: InstagramAccount;
  onSaved: () => void;
}) {
  const [form, setForm] = useState<AiSettingsBody>({
    business_vertical:
      (account.business_vertical as BusinessVertical) || "general",
    ai_enabled: account.ai_enabled || false,
    ai_cold_dm_enabled: account.ai_cold_dm_enabled || false,
    ai_business_profile: account.ai_business_profile || "",
    ai_tone_instructions: account.ai_tone_instructions || "",
    ai_daily_message_cap: account.ai_daily_message_cap ?? 100,
  });
  const [saving, setSaving] = useState(false);
  const [result, setResult] = useState<{
    text: string;
    tone: "info" | "error";
  } | null>(null);

  async function save() {
    setSaving(true);
    setResult(null);
    try {
      await staffSend<InstagramAccount>(
        "PATCH",
        `/instagram/accounts/${encodeURIComponent(account.id)}/ai-settings`,
        form,
      );
      setResult({ text: "AI settings saved.", tone: "info" });
      onSaved();
    } catch (caught) {
      setResult({
        text:
          caught instanceof ManyError
            ? caught.message
            : "Could not save the AI settings.",
        tone: "error",
      });
    } finally {
      setSaving(false);
    }
  }

  return (
    <section
      className="ig-subpanel"
      data-testid="ig-ai-settings"
      aria-label="AI conversation assistant"
    >
      <header className="ig-subpanel-head">
        <div>
          <h3>AI conversation assistant</h3>
          <p className="muted">
            Shared across all campaigns on this account. Used only once a lead
            replies inside a DM thread.
          </p>
        </div>
      </header>
      <Switch
        label="Enabled"
        checked={form.ai_enabled}
        onChange={(next) => setForm((f) => ({ ...f, ai_enabled: next }))}
        data-testid="ig-ai-enabled"
      />
      <Switch
        label="Also let AI answer unsolicited DMs"
        hint="Separate opt-in. When on, the AI also replies to people who message this account directly without going through a campaign. Campaign conversations only need the main switch."
        checked={form.ai_cold_dm_enabled}
        disabled={!form.ai_enabled}
        onChange={(next) =>
          setForm((f) => ({ ...f, ai_cold_dm_enabled: next }))
        }
      />
      <div className="ig-grid-2">
        <Field
          label="Business vertical"
          hint="Applies non-overridable safety rules (for example, clinics never give medical advice)."
        >
          {(control) => (
            <select
              {...control}
              value={form.business_vertical}
              onChange={(event) =>
                setForm((f) => ({
                  ...f,
                  business_vertical: event.target.value as BusinessVertical,
                }))
              }
            >
              {VERTICALS.map((v) => (
                <option key={v.value} value={v.value}>
                  {v.label}
                </option>
              ))}
            </select>
          )}
        </Field>
        <Field
          label="Daily message cap"
          hint={`Shared budget across all campaigns on this account. Sent today: ${account.ai_messages_sent_today ?? 0}.`}
        >
          {(control) => (
            <input
              {...control}
              type="number"
              min={0}
              max={5000}
              value={form.ai_daily_message_cap}
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
        hint="Facts the AI should know: what the business offers, hours, delivery area, who to contact. A sparse profile leads to vague or unsafe answers."
      >
        {(control) => (
          <textarea
            {...control}
            dir="auto"
            rows={5}
            value={form.ai_business_profile}
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
        label="Tone / style (optional)"
        hint="For example: Friendly and casual, use emojis sparingly."
      >
        {(control) => (
          <textarea
            {...control}
            dir="auto"
            rows={2}
            value={form.ai_tone_instructions}
            onChange={(event) =>
              setForm((f) => ({
                ...f,
                ai_tone_instructions: event.target.value,
              }))
            }
          />
        )}
      </Field>
      <div className="action-row">
        <Button
          disabled={saving}
          data-testid="ig-ai-save"
          onClick={() => void save()}
        >
          {saving ? "Saving..." : "Save AI settings"}
        </Button>
      </div>
      {result && (
        <Notice tone={result.tone} message={result.text} scope="item" />
      )}
    </section>
  );
}
