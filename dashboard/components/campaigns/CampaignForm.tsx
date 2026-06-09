"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { DataState } from "@/components/ui/DataState";
import { Field, Select, TextArea } from "@/components/ui/Field";
import { Panel } from "@/components/ui/Panel";
import { api } from "@/lib/api";
import { useCan } from "@/lib/permissions";
import { useToast } from "@/components/ToastProvider";
import type { Campaign, CampaignPayload, InstagramAccount, SimulationResult } from "@/lib/types";

const variables = ["{{username}}", "{{campaign_name}}", "{{keyword}}", "{{link}}", "{{media_url}}"];

type FormState = {
  name: string;
  description: string;
  instagram_account_id: string;
  target_scope: "any_media" | "specific_media";
  target_media_url: string;
  target_media_shortcode: string;
  target_media_type: "post" | "reel" | "story" | "unknown";
  target_media_label: string;
  keywords: string[];
  keywordInput: string;
  match_type: "contains" | "exact" | "starts_with";
  message_template: string;
  link_url: string;
  cooldown_hours: number;
  status: "draft" | "active" | "paused" | "archived";
  delivery_mode: "instant" | "follow_prompt";
  follow_prompt_title: string;
  follow_prompt_description: string;
  follow_prompt_profile_url: string;
};

function extractInstagramShortcode(value: string): string {
  try {
    const url = new URL(value);
    const parts = url.pathname.split("/").filter(Boolean);
    return ["reel", "p", "tv"].includes(parts[0]) && parts[1] ? parts[1] : "";
  } catch {
    return "";
  }
}

function fromCampaign(campaign?: Campaign): FormState {
  return {
    name: campaign?.name || "",
    description: campaign?.description || "",
    instagram_account_id: campaign?.instagram_account_id || "",
    target_scope: campaign?.target_scope || "any_media",
    target_media_url: campaign?.target_media_url || campaign?.media_url || "",
    target_media_shortcode: campaign?.target_media_shortcode || "",
    target_media_type: campaign?.target_media_type || "unknown",
    target_media_label: campaign?.target_media_label || "",
    keywords: campaign?.keywords.map((keyword) => keyword.normalized_keyword) || [],
    keywordInput: "",
    match_type: campaign?.match_type || "contains",
    message_template: campaign?.message_template || "Hi {{username}}, here is your {{keyword}} link: {{link}}",
    link_url: campaign?.link_url || "",
    cooldown_hours: campaign?.cooldown_hours ?? 168,
    status: campaign?.status || "draft",
    delivery_mode: campaign?.delivery_mode || "instant",
    follow_prompt_title: campaign?.follow_prompt_title || "",
    follow_prompt_description: campaign?.follow_prompt_description || "",
    follow_prompt_profile_url: campaign?.follow_prompt_profile_url || "",
  };
}

export function CampaignForm({ campaign }: { campaign?: Campaign }) {
  const router = useRouter();
  const canManageCampaigns = useCan("manage_campaigns");
  const toast = useToast();
  const [form, setForm] = useState<FormState>(() => fromCampaign(campaign));
  const [accounts, setAccounts] = useState<InstagramAccount[]>([]);
  const [savedCampaign, setSavedCampaign] = useState<Campaign | undefined>(campaign);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [testOpen, setTestOpen] = useState(false);
  const [testInput, setTestInput] = useState({ comment_text: "", username: "" });
  const [simulation, setSimulation] = useState<SimulationResult | null>(null);

  useEffect(() => {
    api.get<InstagramAccount[]>("/instagram/accounts").then(setAccounts).catch(() => setAccounts([]));
  }, []);

  useEffect(() => {
    if (!form.instagram_account_id && accounts[0]) {
      setForm((current) => ({ ...current, instagram_account_id: accounts[0].id }));
    }
  }, [accounts, form.instagram_account_id]);

  const payload = useMemo<CampaignPayload>(() => {
    const targetShortcode = extractInstagramShortcode(form.target_media_url);
    return {
      instagram_account_id: form.instagram_account_id,
      name: form.name,
      description: form.description || null,
      media_id: null,
      media_url: form.target_scope === "specific_media" ? form.target_media_url || null : null,
      target_scope: form.target_scope,
      target_media_url: form.target_scope === "specific_media" ? form.target_media_url || null : null,
      target_media_shortcode: form.target_scope === "specific_media" ? targetShortcode || null : null,
      target_media_id: savedCampaign?.target_media_id || null,
      target_media_type: form.target_scope === "specific_media" ? form.target_media_type : "unknown",
      target_media_label: form.target_scope === "specific_media" ? form.target_media_label || null : null,
      match_type: form.match_type,
      message_template: form.message_template,
      link_url: form.link_url || null,
      cooldown_hours: Number(form.cooldown_hours),
      status: savedCampaign?.status === "active" || savedCampaign?.status === "paused" ? savedCampaign.status : "draft",
      keywords: form.keywords,
      delivery_mode: form.delivery_mode,
      follow_prompt_title: form.delivery_mode === "follow_prompt" ? form.follow_prompt_title : null,
      follow_prompt_description: form.delivery_mode === "follow_prompt" ? form.follow_prompt_description : null,
      follow_prompt_profile_url: form.delivery_mode === "follow_prompt" ? form.follow_prompt_profile_url : null,
    };
  }, [form, savedCampaign?.status, savedCampaign?.target_media_id]);

  function addKeyword() {
    const keyword = form.keywordInput.trim();
    if (!keyword || form.keywords.includes(keyword)) return;
    setForm({ ...form, keywords: [...form.keywords, keyword], keywordInput: "" });
  }

  async function syncKeywords(id: string, existing: Campaign["keywords"]) {
    const current = new Set(existing.map((keyword) => keyword.normalized_keyword));
    const next = new Set(form.keywords);
    await Promise.all(
      form.keywords
        .filter((keyword) => !current.has(keyword))
        .map((keyword) => api.post(`/campaigns/${id}/keywords?keyword=${encodeURIComponent(keyword)}`)),
    );
    await Promise.all(
      existing
        .filter((keyword) => !next.has(keyword.normalized_keyword))
        .map((keyword) => api.delete(`/campaigns/${id}/keywords/${keyword.id}`)),
    );
  }

  async function save(status: "draft" | "active" = "draft") {
    if (!canManageCampaigns) {
      setError("Your role has read-only campaign access.");
      toast.warning("Your role has read-only campaign access.");
      return null;
    }
    setSaving(true);
    setError(null);
    try {
      const nextPayload = { ...payload, status: savedCampaign ? savedCampaign.status : status };
      let saved: Campaign;
      if (savedCampaign) {
        saved = await api.patch<Campaign>(`/campaigns/${savedCampaign.id}`, {
          name: nextPayload.name,
          description: nextPayload.description,
          media_id: nextPayload.media_id,
          media_url: nextPayload.media_url,
          target_scope: nextPayload.target_scope,
          target_media_url: nextPayload.target_media_url,
          target_media_shortcode: nextPayload.target_media_shortcode,
          target_media_id: nextPayload.target_media_id,
          target_media_type: nextPayload.target_media_type,
          target_media_label: nextPayload.target_media_label,
          match_type: nextPayload.match_type,
          message_template: nextPayload.message_template,
          link_url: nextPayload.link_url,
          cooldown_hours: nextPayload.cooldown_hours,
          delivery_mode: nextPayload.delivery_mode,
          follow_prompt_title: nextPayload.follow_prompt_title,
          follow_prompt_description: nextPayload.follow_prompt_description,
          follow_prompt_profile_url: nextPayload.follow_prompt_profile_url,
        });
        await syncKeywords(saved.id, saved.keywords);
        saved = await api.get<Campaign>(`/campaigns/${saved.id}`);
      } else {
        saved = await api.post<Campaign>("/campaigns", { ...nextPayload, status: status === "active" ? "draft" : "draft" });
      }
      if (status === "active") {
        saved = await api.post<Campaign>(`/campaigns/${saved.id}/activate`);
      }
      setSavedCampaign(saved);
      toast.success(status === "active" ? "Campaign activated." : "Campaign saved.");
      router.push(status === "active" ? `/campaigns/${saved.id}` : `/campaigns/${saved.id}`);
      return saved;
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to save campaign";
      setError(message);
      toast.error(message);
      return null;
    } finally {
      setSaving(false);
    }
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    await save("draft");
  }

  async function simulate() {
    if (!canManageCampaigns && !savedCampaign) {
      setError("Save access is required before testing a new campaign.");
      toast.warning("Save access is required before testing a new campaign.");
      return;
    }
    const saved = savedCampaign || await save("draft");
    if (!saved) return;
    setSimulation(await api.post<SimulationResult>(`/campaigns/${saved.id}/simulate`, testInput));
  }

  return (
    <form onSubmit={submit} className="grid gap-6">
      <DataState error={error} />
      {!canManageCampaigns ? (
        <Panel className="border-amber-200 bg-amber-50 text-sm font-semibold text-amber-800">
          Your role has read-only campaign access.
        </Panel>
      ) : null}
      <Panel>
        <h2 className="mb-4 text-lg font-bold text-ink">Step 1: Campaign basics</h2>
        <div className="grid gap-4 md:grid-cols-2">
          <Field label="Name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required />
          <Select label="Instagram account" value={form.instagram_account_id} onChange={(e) => setForm({ ...form, instagram_account_id: e.target.value })} required>
            <option value="">Select account</option>
            {accounts.map((account) => <option key={account.id} value={account.id}>{account.username || account.ig_user_id}</option>)}
          </Select>
          <div className="md:col-span-2">
            <TextArea label="Description" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
          </div>
        </div>
      </Panel>

      <Panel>
        <h2 className="mb-4 text-lg font-bold text-ink">Step 2: Target post/reel</h2>
        <div className="grid gap-3">
          <label className="flex gap-3 rounded-lg border border-line bg-white p-3">
            <input
              type="radio"
              name="target_scope"
              value="any_media"
              checked={form.target_scope === "any_media"}
              onChange={() => setForm({ ...form, target_scope: "any_media" })}
              className="mt-1 h-4 w-4 border-slate-300 text-accent focus:ring-accent/30"
            />
            <span className="grid gap-1">
              <span className="text-sm font-bold text-ink">Any post or reel on this account</span>
              <span className="text-sm font-medium text-muted">Use this when the same keyword can trigger across the whole Instagram account.</span>
            </span>
          </label>
          <label className="flex gap-3 rounded-lg border border-line bg-white p-3">
            <input
              type="radio"
              name="target_scope"
              value="specific_media"
              checked={form.target_scope === "specific_media"}
              onChange={() => setForm({ ...form, target_scope: "specific_media" })}
              className="mt-1 h-4 w-4 border-slate-300 text-accent focus:ring-accent/30"
            />
            <span className="grid gap-1">
              <span className="text-sm font-bold text-ink">Specific post or reel</span>
              <span className="text-sm font-medium text-muted">Use this when this campaign should only trigger from comments on one exact post/reel.</span>
            </span>
          </label>
        </div>
        {form.target_scope === "specific_media" ? (
          <div className="mt-4 grid gap-4 md:grid-cols-2">
            <Field
              label="Instagram post/reel URL"
              type="url"
              placeholder="https://www.instagram.com/reel/..."
              hint="Paste the Instagram URL for the post or reel this campaign should listen to."
              value={form.target_media_url}
              onChange={(e) => setForm({ ...form, target_media_url: e.target.value, target_media_shortcode: extractInstagramShortcode(e.target.value) })}
              required
            />
            <Field
              label="Post/Reel label"
              placeholder="May discount reel"
              hint="A private name to help your team recognize this post or reel."
              value={form.target_media_label}
              onChange={(e) => setForm({ ...form, target_media_label: e.target.value })}
            />
            <Select
              label="Media type"
              value={form.target_media_type}
              onChange={(e) => setForm({ ...form, target_media_type: e.target.value as FormState["target_media_type"] })}
            >
              <option value="reel">Reel</option>
              <option value="post">Post</option>
              <option value="story">Story</option>
              <option value="unknown">Unknown</option>
            </Select>
            <p className="self-end text-sm font-medium text-amber-700">
              The system will match this campaign once the media ID is known from webhook events or account setup.
            </p>
          </div>
        ) : null}
        {form.target_scope === "specific_media" && form.target_media_shortcode ? (
          <p className="mt-3 text-xs font-medium text-muted">Shortcode detected: {form.target_media_shortcode}</p>
        ) : null}
      </Panel>

      <Panel>
        <h2 className="mb-4 text-lg font-bold text-ink">Step 3: Keywords</h2>
        <div className="grid gap-4 md:grid-cols-[1fr_auto]">
          <Field label="Keyword" value={form.keywordInput} onChange={(e) => setForm({ ...form, keywordInput: e.target.value })} onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              addKeyword();
            }
          }} />
          <Button type="button" variant="secondary" className="self-end" onClick={addKeyword}>Add</Button>
        </div>
        <div className="mt-3 flex flex-wrap gap-2">
          {form.keywords.map((keyword) => (
            <button key={keyword} type="button" className="rounded-full border border-emerald-200 bg-mint px-3 py-1 text-sm font-semibold text-emerald-700 transition hover:border-emerald-300 hover:bg-emerald-100" onClick={() => setForm({ ...form, keywords: form.keywords.filter((item) => item !== keyword) })}>
              {keyword} x
            </button>
          ))}
        </div>
        <div className="mt-4 max-w-xs">
          <Select label="Match type" value={form.match_type} onChange={(e) => setForm({ ...form, match_type: e.target.value as FormState["match_type"] })}>
            <option value="contains">Contains</option>
            <option value="exact">Exact</option>
            <option value="starts_with">Starts with</option>
          </Select>
        </div>
      </Panel>

      <Panel>
        <h2 className="mb-4 text-lg font-bold text-ink">Step 4: Message</h2>
        <TextArea label="Message template" value={form.message_template} onChange={(e) => setForm({ ...form, message_template: e.target.value })} required />
        <div className="mt-3 flex flex-wrap gap-2">
          {variables.map((item) => (
            <Button key={item} type="button" variant="secondary" onClick={() => setForm({ ...form, message_template: `${form.message_template}${item}` })}>{item}</Button>
          ))}
        </div>
        <div className="mt-4 grid gap-4 md:grid-cols-2">
          <Field label="Link URL" type="url" value={form.link_url} onChange={(e) => setForm({ ...form, link_url: e.target.value })} />
          <p className="self-end text-sm font-medium text-muted">{form.message_template.length} / 1000 characters</p>
        </div>
      </Panel>

      <Panel>
        <h2 className="mb-4 text-lg font-bold text-ink">Step 5: Delivery Flow</h2>
        <div className="grid gap-4">
          <Select label="Delivery mode" value={form.delivery_mode} onChange={(e) => setForm({ ...form, delivery_mode: e.target.value as FormState["delivery_mode"] })}>
            <option value="instant">Instant delivery</option>
            <option value="follow_prompt">Follow prompt then details</option>
          </Select>
          {form.delivery_mode === "follow_prompt" ? (
            <div className="grid gap-4 rounded-xl border border-emerald-100 bg-mint/50 p-4 md:grid-cols-2">
              <Field label="Card Title" value={form.follow_prompt_title} onChange={(e) => setForm({ ...form, follow_prompt_title: e.target.value })} required />
              <Field label="Profile URL" type="url" value={form.follow_prompt_profile_url} onChange={(e) => setForm({ ...form, follow_prompt_profile_url: e.target.value })} required />
              <div className="md:col-span-2">
                <TextArea label="Card Description" value={form.follow_prompt_description} onChange={(e) => setForm({ ...form, follow_prompt_description: e.target.value })} required />
              </div>
              <div className="flex flex-wrap items-center gap-3 md:col-span-2">
                <span className="inline-flex h-10 items-center justify-center rounded-lg border border-emerald-200 bg-white px-4 text-sm font-semibold text-emerald-700">Follow</span>
                <span className="rounded-full border border-slate-200 bg-white px-3 py-1 text-xs font-semibold text-slate-700">10 seconds fixed</span>
              </div>
              <p className="text-sm font-medium text-muted md:col-span-2">
                The Follow button opens the Instagram profile. The final message is sent automatically after 10 seconds. The system does not verify whether the user followed.
              </p>
            </div>
          ) : null}
        </div>
      </Panel>

      <Panel>
        <h2 className="mb-4 text-lg font-bold text-ink">Step 6: Publishing controls</h2>
        <div className="grid gap-4 md:grid-cols-2">
          <Field
            label="Cooldown period"
            type="number"
            min={0}
            value={form.cooldown_hours}
            hint="Prevent sending this campaign again to the same Instagram user for this many hours."
            onChange={(e) => setForm({ ...form, cooldown_hours: Number(e.target.value) })}
          />
        </div>
      </Panel>

      <div className="sticky bottom-0 z-[1] flex flex-wrap items-center gap-3 border-t border-line bg-panel/95 py-4 backdrop-blur">
        {canManageCampaigns ? <Button type="submit" disabled={saving}>Save Draft</Button> : null}
        {canManageCampaigns ? <Button type="button" disabled={saving} onClick={() => save("active")}>Activate Campaign</Button> : null}
        <Button type="button" variant="secondary" onClick={() => setTestOpen(true)}>Test Message</Button>
        {savedCampaign ? <Badge value={savedCampaign.status} /> : null}
      </div>

      {testOpen ? (
        <div className="fixed inset-0 z-10 flex items-center justify-center bg-black/30 p-4">
          <Panel className="w-full max-w-lg shadow-2xl">
            <h2 className="mb-4 text-lg font-bold text-ink">Test Message</h2>
            <div className="grid gap-4">
              <Field label="Comment text" value={testInput.comment_text} onChange={(e) => setTestInput({ ...testInput, comment_text: e.target.value })} />
              <Field label="Username" value={testInput.username} onChange={(e) => setTestInput({ ...testInput, username: e.target.value })} />
              {simulation ? (
                <div className="rounded-lg border border-line bg-panel p-3 text-sm text-slate-700">
                  <p>Matched: {simulation.matched ? "True" : "False"}</p>
                  <p>Rendered message: {simulation.rendered_message || "No message rendered"}</p>
                </div>
              ) : null}
              <div className="flex gap-2">
                <Button type="button" onClick={simulate}>Run test</Button>
                <Button type="button" variant="secondary" onClick={() => setTestOpen(false)}>Close</Button>
              </div>
            </div>
          </Panel>
        </div>
      ) : null}
    </form>
  );
}
