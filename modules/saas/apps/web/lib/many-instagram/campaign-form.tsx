"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";

import { ManyError } from "@/lib/many";
import {
  Button,
  Dialog,
  Field,
  FormSection,
  Notice,
  StatusBadge,
  Switch,
} from "@/lib/ui";

import { staffGet, staffSend } from "./calls";
import {
  addKeyword,
  buildCreateBody,
  buildPatchBody,
  extractInstagramShortcode,
  formFromCampaign,
  keywordAddPath,
  planKeywordSync,
  TEMPLATE_VARIABLES,
  type CampaignFormState,
} from "./helpers";
import { PostPicker } from "./post-picker";
import type {
  Campaign,
  InstagramAccount,
  InstagramMedia,
  SimulationResult,
} from "./types";

const LIST = "/platform/instagram/campaigns";

/** Create or edit one campaign. Many calls: see the comments next to each. */
export function CampaignForm({ campaign }: { campaign?: Campaign }) {
  const router = useRouter();
  const [form, setForm] = useState<CampaignFormState>(() =>
    formFromCampaign(campaign),
  );
  const [accounts, setAccounts] = useState<InstagramAccount[]>([]);
  const [accountsError, setAccountsError] = useState<string | null>(null);
  const [saved, setSaved] = useState<Campaign | undefined>(campaign);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [testOpen, setTestOpen] = useState(false);
  const [testInput, setTestInput] = useState({
    comment_text: "",
    username: "",
  });
  const [simulation, setSimulation] = useState<SimulationResult | null>(null);
  const [testError, setTestError] = useState<string | null>(null);
  const [testing, setTesting] = useState(false);

  useEffect(() => {
    const timer = setTimeout(() => {
      staffGet<InstagramAccount[]>("/instagram/accounts").then(
        (rows) => {
          setAccounts(rows);
          setForm((current) =>
            !current.instagram_account_id && rows[0]
              ? { ...current, instagram_account_id: rows[0].id }
              : current,
          );
        },
        (caught: unknown) => {
          setAccounts([]);
          setAccountsError(
            caught instanceof ManyError
              ? caught.message
              : "Could not load the Instagram accounts.",
          );
        },
      );
    }, 0);
    return () => clearTimeout(timer);
  }, []);

  function patch(change: Partial<CampaignFormState>) {
    setForm((current) => ({ ...current, ...change }));
  }

  function pushKeyword() {
    setForm((current) => ({
      ...current,
      keywords: addKeyword(current.keywords, current.keywordInput),
      keywordInput: "",
    }));
  }

  /** Save as a draft (create or edit), then optionally activate. */
  async function save(activate: boolean) {
    setSaving(true);
    setError(null);
    try {
      let result: Campaign;
      if (saved) {
        // PATCH /campaigns/{id}, then the keyword diff, then a fresh GET.
        result = await staffSend<Campaign>(
          "PATCH",
          `/campaigns/${saved.id}`,
          buildPatchBody(form),
        );
        const plan = planKeywordSync(result.keywords, form.keywords);
        await Promise.all(
          plan.add.map((keyword) =>
            staffSend("POST", keywordAddPath(result.id, keyword)),
          ),
        );
        await Promise.all(
          plan.remove.map((id) =>
            staffSend("DELETE", `/campaigns/${result.id}/keywords/${id}`),
          ),
        );
        result = await staffGet<Campaign>(`/campaigns/${result.id}`);
      } else {
        // POST /campaigns (always a draft).
        result = await staffSend<Campaign>(
          "POST",
          "/campaigns",
          buildCreateBody(form),
        );
      }
      if (activate) {
        // POST /campaigns/{id}/activate
        result = await staffSend<Campaign>(
          "POST",
          `/campaigns/${result.id}/activate`,
        );
      }
      setSaved(result);
      router.push(activate ? LIST : `${LIST}/${result.id}`);
    } catch (caught) {
      setError(
        caught instanceof ManyError
          ? caught.message
          : "Could not save the campaign.",
      );
    } finally {
      setSaving(false);
    }
  }

  async function simulate() {
    if (!saved) return;
    setTesting(true);
    setTestError(null);
    try {
      // POST /campaigns/{id}/simulate
      setSimulation(
        await staffSend<SimulationResult>(
          "POST",
          `/campaigns/${saved.id}/simulate`,
          testInput,
        ),
      );
    } catch (caught) {
      setSimulation(null);
      setTestError(
        caught instanceof ManyError
          ? caught.message
          : "Could not run the test.",
      );
    } finally {
      setTesting(false);
    }
  }

  function pickMedia(media: InstagramMedia) {
    setForm((current) => ({
      ...current,
      target_media_id: media.media_id,
      target_media_url: media.permalink || "",
      target_media_shortcode: extractInstagramShortcode(media.permalink || ""),
      target_media_type: media.media_type === "VIDEO" ? "reel" : "post",
      target_media_label: current.target_media_label || media.label,
    }));
  }

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    void save(false);
  }

  return (
    <form
      onSubmit={onSubmit}
      className="ig-form"
      data-testid="ig-campaign-form"
    >
      {error && (
        <div data-testid="ig-form-error">
          <Notice tone="error" message={error} scope="item" />
        </div>
      )}
      {accountsError && (
        <Notice tone="error" message={accountsError} scope="item" />
      )}

      <FormSection title="Step 1: Campaign basics">
        <div className="ig-grid-2">
          <Field label="Name" required>
            {(control) => (
              <input
                {...control}
                dir="auto"
                required
                data-testid="ig-name"
                value={form.name}
                onChange={(event) => patch({ name: event.target.value })}
              />
            )}
          </Field>
          <Field label="Instagram account" required>
            {(control) => (
              <select
                {...control}
                required
                data-testid="ig-account"
                value={form.instagram_account_id}
                onChange={(event) =>
                  patch({ instagram_account_id: event.target.value })
                }
              >
                <option value="">Select account</option>
                {accounts.map((account) => (
                  <option key={account.id} value={account.id}>
                    {account.username || account.ig_user_id}
                  </option>
                ))}
              </select>
            )}
          </Field>
        </div>
        <Field label="Description">
          {(control) => (
            <textarea
              {...control}
              dir="auto"
              rows={3}
              value={form.description}
              onChange={(event) => patch({ description: event.target.value })}
            />
          )}
        </Field>
      </FormSection>

      <FormSection title="Step 2: Target post or reel">
        <fieldset className="ig-radios">
          <legend className="sr-only">Target</legend>
          <label className="ig-radio">
            <input
              type="radio"
              name="target_scope"
              value="any_media"
              data-testid="ig-scope-any"
              checked={form.target_scope === "any_media"}
              onChange={() => patch({ target_scope: "any_media" })}
            />
            <span>
              <strong>Any post or reel on this account</strong>
              <small className="muted">
                The same keyword can trigger across the whole Instagram account.
              </small>
            </span>
          </label>
          <label className="ig-radio">
            <input
              type="radio"
              name="target_scope"
              value="specific_media"
              data-testid="ig-scope-specific"
              checked={form.target_scope === "specific_media"}
              onChange={() => patch({ target_scope: "specific_media" })}
            />
            <span>
              <strong>Specific post or reel</strong>
              <small className="muted">
                The campaign only triggers from comments on one exact post or
                reel.
              </small>
            </span>
          </label>
        </fieldset>
        {form.target_scope === "specific_media" && (
          <div className="ig-target">
            <p className="muted">
              Pick from posts on the connected account. Selecting here links the
              campaign to Instagram&apos;s own post ID, which is what makes
              keyword matching work.
            </p>
            <PostPicker
              accountId={form.instagram_account_id}
              selectedMediaId={form.target_media_id || null}
              onSelect={pickMedia}
            />
            {form.target_media_id ? (
              <div className="ig-grid-2">
                <Field
                  label="Post or reel label"
                  hint="A private name to help your team recognize this post or reel."
                >
                  {(control) => (
                    <input
                      {...control}
                      dir="auto"
                      placeholder="May discount reel"
                      value={form.target_media_label}
                      onChange={(event) =>
                        patch({ target_media_label: event.target.value })
                      }
                    />
                  )}
                </Field>
                <p data-testid="ig-media-chosen">
                  Post selected (ID{" "}
                  <span dir="ltr">{form.target_media_id}</span>)
                  {form.target_media_url && (
                    <>
                      {" "}
                      <a
                        href={form.target_media_url}
                        target="_blank"
                        rel="noreferrer noopener"
                        dir="ltr"
                      >
                        View on Instagram
                      </a>
                    </>
                  )}
                </p>
              </div>
            ) : (
              <p className="muted">
                No post selected yet. Choose one above before saving or
                activating.
              </p>
            )}
          </div>
        )}
      </FormSection>

      <FormSection title="Step 3: Keywords">
        <div className="ig-keyword-row">
          <Field label="Keyword">
            {(control) => (
              <input
                {...control}
                dir="auto"
                data-testid="ig-keyword-input"
                value={form.keywordInput}
                onChange={(event) =>
                  patch({ keywordInput: event.target.value })
                }
                onKeyDown={(event) => {
                  if (event.key === "Enter") {
                    event.preventDefault();
                    pushKeyword();
                  }
                }}
              />
            )}
          </Field>
          <Button
            variant="quiet"
            data-testid="ig-keyword-add"
            onClick={pushKeyword}
          >
            Add
          </Button>
        </div>
        <ul className="ig-chips" aria-label="Keywords">
          {form.keywords.map((keyword) => (
            <li key={keyword}>
              <button
                type="button"
                className="ig-chip"
                dir="auto"
                aria-label={`Remove keyword ${keyword}`}
                onClick={() =>
                  patch({
                    keywords: form.keywords.filter((k) => k !== keyword),
                  })
                }
              >
                {keyword} &times;
              </button>
            </li>
          ))}
        </ul>
        <Field label="Match type">
          {(control) => (
            <select
              {...control}
              value={form.match_type}
              onChange={(event) =>
                patch({
                  match_type: event.target
                    .value as CampaignFormState["match_type"],
                })
              }
            >
              <option value="contains">Contains</option>
              <option value="exact">Exact</option>
              <option value="starts_with">Starts with</option>
            </select>
          )}
        </Field>
      </FormSection>

      <FormSection title="Step 4: Message">
        <Field
          label="Message template"
          required
          hint={`${form.message_template.length} / 1000 characters`}
        >
          {(control) => (
            <textarea
              {...control}
              dir="auto"
              rows={4}
              required
              data-testid="ig-template"
              value={form.message_template}
              onChange={(event) =>
                patch({ message_template: event.target.value })
              }
            />
          )}
        </Field>
        <div className="action-row">
          {TEMPLATE_VARIABLES.map((item) => (
            <Button
              key={item}
              variant="quiet"
              onClick={() =>
                patch({ message_template: `${form.message_template}${item}` })
              }
            >
              {item}
            </Button>
          ))}
        </div>
        <Field label="Link URL">
          {(control) => (
            <input
              {...control}
              type="url"
              dir="ltr"
              value={form.link_url}
              onChange={(event) => patch({ link_url: event.target.value })}
            />
          )}
        </Field>
      </FormSection>

      <FormSection title="Step 5: Delivery flow">
        <Field label="Delivery mode">
          {(control) => (
            <select
              {...control}
              data-testid="ig-delivery"
              value={form.delivery_mode}
              onChange={(event) =>
                patch({
                  delivery_mode: event.target
                    .value as CampaignFormState["delivery_mode"],
                })
              }
            >
              <option value="instant">Instant delivery</option>
              <option value="follow_prompt">Follow prompt then details</option>
            </select>
          )}
        </Field>
        {form.delivery_mode === "follow_prompt" && (
          <div className="ig-subpanel" data-testid="ig-follow-prompt">
            <div className="ig-grid-2">
              <Field label="Card title" required>
                {(control) => (
                  <input
                    {...control}
                    dir="auto"
                    required
                    value={form.follow_prompt_title}
                    onChange={(event) =>
                      patch({ follow_prompt_title: event.target.value })
                    }
                  />
                )}
              </Field>
              <Field label="Profile URL" required>
                {(control) => (
                  <input
                    {...control}
                    type="url"
                    dir="ltr"
                    required
                    value={form.follow_prompt_profile_url}
                    onChange={(event) =>
                      patch({ follow_prompt_profile_url: event.target.value })
                    }
                  />
                )}
              </Field>
            </div>
            <Field label="Card description" required>
              {(control) => (
                <textarea
                  {...control}
                  dir="auto"
                  rows={3}
                  required
                  value={form.follow_prompt_description}
                  onChange={(event) =>
                    patch({ follow_prompt_description: event.target.value })
                  }
                />
              )}
            </Field>
            <p className="muted">
              The Follow button opens the Instagram profile. The final message
              is sent automatically after 10 seconds. The system does not verify
              whether the user followed.
            </p>
          </div>
        )}
      </FormSection>

      <FormSection title="Public comment reply">
        <Switch
          label="Reply publicly to the comment"
          hint="After the DM is delivered, post a public reply on the comment so the person knows to check their inbox. Only sent when the DM succeeds."
          checked={form.comment_reply_enabled}
          onChange={(next) => patch({ comment_reply_enabled: next })}
        />
        {form.comment_reply_enabled && (
          <Field
            label="Public reply text"
            hint="Keep it short. This is visible to everyone on the post."
          >
            {(control) => (
              <input
                {...control}
                dir="auto"
                maxLength={280}
                placeholder="Check your DMs!"
                value={form.comment_reply_text}
                onChange={(event) =>
                  patch({ comment_reply_text: event.target.value })
                }
              />
            )}
          </Field>
        )}
      </FormSection>

      <FormSection title="AI conversation continuation">
        <Switch
          label="Let AI continue this campaign's conversations"
          hint="If a lead replies inside the DM after receiving this campaign's message, the AI assistant takes over, using the business profile on the connected account. AI must also be enabled on the account."
          checked={form.ai_enabled}
          onChange={(next) => patch({ ai_enabled: next })}
        />
        {form.ai_enabled && (
          <Field
            label="Hand off to a human after"
            hint="Number of AI turns before the conversation is handed off for a manual reply."
          >
            {(control) => (
              <input
                {...control}
                type="number"
                min={1}
                max={50}
                value={form.ai_handoff_after_turns}
                onChange={(event) =>
                  patch({ ai_handoff_after_turns: Number(event.target.value) })
                }
              />
            )}
          </Field>
        )}
      </FormSection>

      <FormSection title="Step 6: Publishing controls">
        <Field
          label="Cooldown period (hours)"
          hint="Prevents sending this campaign again to the same Instagram user for this many hours."
        >
          {(control) => (
            <input
              {...control}
              type="number"
              min={0}
              value={form.cooldown_hours}
              onChange={(event) =>
                patch({ cooldown_hours: Number(event.target.value) })
              }
            />
          )}
        </Field>
      </FormSection>

      <div className="ig-form-actions">
        <Button type="submit" disabled={saving} data-testid="ig-save-draft">
          {saved ? "Save changes" : "Save draft"}
        </Button>
        <Button
          disabled={saving}
          data-testid="ig-activate"
          onClick={() => void save(true)}
        >
          Activate campaign
        </Button>
        <Button
          variant="quiet"
          data-testid="ig-test-open"
          onClick={() => setTestOpen(true)}
        >
          Test message
        </Button>
        {saved && <StatusBadge value={saved.status} />}
      </div>

      <Dialog
        open={testOpen}
        onClose={() => setTestOpen(false)}
        title="Test message"
        data-testid="ig-test-dialog"
      >
        <p className="muted">
          {saved
            ? "Tests the saved version of this campaign. Save your edits first."
            : "Save the draft first, then test the message."}
        </p>
        <Field label="Comment text">
          {(control) => (
            <input
              {...control}
              dir="auto"
              data-testid="ig-test-comment"
              value={testInput.comment_text}
              onChange={(event) =>
                setTestInput({ ...testInput, comment_text: event.target.value })
              }
            />
          )}
        </Field>
        <Field label="Username">
          {(control) => (
            <input
              {...control}
              dir="auto"
              value={testInput.username}
              onChange={(event) =>
                setTestInput({ ...testInput, username: event.target.value })
              }
            />
          )}
        </Field>
        {simulation && (
          <div data-testid="ig-test-result">
            <p>Matched: {simulation.matched ? "Yes" : "No"}</p>
            <p dir="auto">
              Rendered message:{" "}
              {simulation.rendered_message || "No message rendered"}
            </p>
          </div>
        )}
        {testError && <Notice tone="error" message={testError} scope="item" />}
        <div className="action-row">
          <Button
            disabled={!saved || testing}
            data-testid="ig-test-run"
            onClick={() => void simulate()}
          >
            {testing ? "Testing..." : "Run test"}
          </Button>
          <Button variant="quiet" onClick={() => setTestOpen(false)}>
            Close
          </Button>
        </div>
      </Dialog>
    </form>
  );
}
