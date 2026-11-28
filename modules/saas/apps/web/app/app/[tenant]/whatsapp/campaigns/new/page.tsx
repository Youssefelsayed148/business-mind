"use client";

import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";

import { manyRequest } from "@/lib/many";
import { PageState } from "@/lib/page-state";
import { useManyData } from "@/lib/use-many";
import {
  Button,
  Card,
  Field,
  LinkButton,
  Loading,
  Notice,
  PageHeader,
  StatCard,
} from "@/lib/ui";
import {
  mappingComplete,
  reasonLabel,
  templateIndexes,
  type DryRun,
  type VariableSpec,
  type WhatsappCampaign,
  type WhatsappContact,
  type WhatsappTemplate,
} from "@/lib/whatsapp-types";

import { actionMessage, useWhatsapp } from "../../whatsapp-shell";

import "@/app/whatsapp-screen.css";

const STEPS = ["Template", "Audience", "Variables", "Dry-run", "Confirm"];
const CONTACT_LIMIT = 200;

type Prepared = {
  accountId: string;
  templates: WhatsappTemplate[];
  contactCount: number;
};

export default function NewWhatsappCampaignPage() {
  const { tenantId, account } = useWhatsapp();
  const { data, status } = useManyData<Prepared>(async () => {
    const scope = { kind: "org", tenantId } as const;
    const [templates, contacts] = await Promise.all([
      manyRequest<WhatsappTemplate[]>(
        scope,
        "GET",
        `whatsapp/templates?account_id=${account.id}&template_status=approved`,
      ),
      manyRequest<{ items: WhatsappContact[] }>(
        scope,
        "GET",
        `whatsapp/contacts?account_id=${account.id}&limit=${CONTACT_LIMIT}`,
      ),
    ]);
    return {
      accountId: account.id,
      templates: templates.filter((t) => t.category !== "authentication"),
      contactCount: contacts.items.length,
    };
  }, account.id);
  return (
    <>
      <PageHeader
        eyebrow={
          <LinkButton
            href={`/app/${tenantId}/whatsapp/campaigns`}
            variant="ghost"
            icon="arrow-left"
          >
            All campaigns
          </LinkButton>
        }
        title="Create WhatsApp campaign"
        purpose="The campaign is only started after a server-side eligibility dry-run and your confirmation."
      />
      <PageState status={status} homeHref={`/app/${tenantId}`}>
        {/* After a switch of number, wait for that number's templates. */}
        {data &&
          (data.accountId === account.id ? (
            <Wizard key={account.id} prepared={data} />
          ) : (
            <Loading />
          ))}
      </PageState>
    </>
  );
}

function Wizard({ prepared }: { prepared: Prepared }) {
  const { tenantId, account, outreachDisabled, notify } = useWhatsapp();
  const router = useRouter();
  const { templates, contactCount } = prepared;
  const [step, setStep] = useState(1);
  const [templateId, setTemplateId] = useState(templates[0]?.id ?? "");
  const [name, setName] = useState("");
  const [mapping, setMapping] = useState<Record<number, VariableSpec>>({});
  const [campaign, setCampaign] = useState<WhatsappCampaign | null>(null);
  const [dry, setDry] = useState<DryRun | null>(null);
  const [reviewed, setReviewed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const template = templates.find((t) => t.id === templateId);
  const vars = useMemo(() => templateIndexes(template), [template]);

  async function runDry() {
    setBusy(true);
    setError(null);
    try {
      const scope = { kind: "org", tenantId } as const;
      const variable_mapping = Object.fromEntries(
        vars.map((i) => [
          String(i),
          mapping[i] || { source: "literal", value: "" },
        ]),
      );
      let current = campaign;
      if (!current) {
        current = await manyRequest<WhatsappCampaign>(
          scope,
          "POST",
          "whatsapp/campaigns",
          {
            account_id: account.id,
            template_id: templateId,
            name,
            throttle_per_minute: 30,
            variable_mapping,
          },
        );
        setCampaign(current);
      }
      setDry(
        await manyRequest<DryRun>(
          scope,
          "POST",
          `whatsapp/campaigns/${current.id}/dry-run`,
          { variable_mapping },
        ),
      );
      setReviewed(false);
      setStep(4);
    } catch (caught) {
      setError(actionMessage(caught, "The dry-run failed."));
    } finally {
      setBusy(false);
    }
  }

  async function start() {
    if (!campaign) return;
    setBusy(true);
    setError(null);
    try {
      await manyRequest(
        { kind: "org", tenantId },
        "POST",
        `whatsapp/campaigns/${campaign.id}/start`,
      );
      notify("Campaign queued to start.");
      router.push(`/app/${tenantId}/whatsapp/campaigns/${campaign.id}`);
    } catch (caught) {
      setError(actionMessage(caught, "Could not start the campaign."));
      setBusy(false);
    }
  }

  return (
    <div className="wa-stack" data-testid="wa-wizard">
      <ol className="wa-steps" aria-label="Campaign steps">
        {STEPS.map((label, i) => (
          <li
            key={label}
            data-active={step === i + 1 ? "true" : "false"}
            aria-current={step === i + 1 ? "step" : undefined}
          >
            {i + 1}. {label}
          </li>
        ))}
      </ol>
      {error && <Notice message={error} tone="error" scope="item" />}
      <Card>
        {step === 1 && (
          <div className="wa-form">
            <h2>Choose an approved template</h2>
            {templates.length === 0 && (
              <p className="muted" data-testid="wa-no-templates">
                No approved marketing or utility template is available. Submit
                and sync a template first.
              </p>
            )}
            <Field label="Template">
              {(control) => (
                <select
                  {...control}
                  dir="auto"
                  data-testid="wa-new-template"
                  value={templateId}
                  onChange={(event) => setTemplateId(event.target.value)}
                >
                  {templates.map((t) => (
                    <option key={t.id} value={t.id}>
                      {t.name} · {t.category}
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
                  data-testid="wa-new-name"
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                />
              )}
            </Field>
            <div className="action-row">
              <Button
                data-testid="wa-next"
                onClick={() => setStep(2)}
                disabled={!templateId || !name.trim()}
              >
                Continue
              </Button>
            </div>
          </div>
        )}
        {step === 2 && (
          <div className="wa-form">
            <h2>Audience</h2>
            <div className="wa-callout">
              <strong>All eligible contacts for this WhatsApp number</strong>
              <p>
                {contactCount}
                {contactCount === CONTACT_LIMIT ? "+" : ""} contacts currently
                loaded. The server freezes the audience at start and excludes
                contacts without permission, opt-outs, and other terminally
                ineligible recipients.
              </p>
            </div>
            <p className="muted">
              This backend does not currently support saved segments or
              per-campaign audience filters.
            </p>
            <div className="action-row">
              <Button variant="quiet" onClick={() => setStep(1)}>
                Back
              </Button>
              <Button data-testid="wa-next" onClick={() => setStep(3)}>
                Use this audience
              </Button>
            </div>
          </div>
        )}
        {step === 3 && (
          <div className="wa-form">
            <h2>Map template variables</h2>
            {vars.length === 0 && (
              <p className="muted">This template has no variables.</p>
            )}
            {vars.map((i) => {
              const spec = mapping[i] || { source: "literal", value: "" };
              return (
                <div className="wa-map" key={i}>
                  <strong dir="ltr">{`{{${i}}}`}</strong>
                  <Field label="Source" className="wa-map-source">
                    {(control) => (
                      <select
                        {...control}
                        data-testid={`wa-map-source-${i}`}
                        value={spec.source}
                        onChange={(event) =>
                          setMapping((old) => ({
                            ...old,
                            [i]: { source: event.target.value },
                          }))
                        }
                      >
                        <option value="literal">Fixed text</option>
                        <option value="contact.display_name">
                          Contact name
                        </option>
                      </select>
                    )}
                  </Field>
                  <Field
                    label={
                      spec.source === "literal"
                        ? "Value"
                        : "Fallback when name is missing"
                    }
                  >
                    {(control) => (
                      <input
                        {...control}
                        dir="auto"
                        data-testid={`wa-map-value-${i}`}
                        value={
                          spec.source === "literal"
                            ? spec.value || ""
                            : spec.fallback || ""
                        }
                        onChange={(event) =>
                          setMapping((old) => ({
                            ...old,
                            [i]:
                              spec.source === "literal"
                                ? {
                                    source: spec.source,
                                    value: event.target.value,
                                  }
                                : {
                                    source: spec.source,
                                    fallback: event.target.value,
                                  },
                          }))
                        }
                      />
                    )}
                  </Field>
                </div>
              );
            })}
            <div className="action-row">
              <Button variant="quiet" onClick={() => setStep(2)}>
                Back
              </Button>
              <Button
                data-testid="wa-dry-run"
                onClick={runDry}
                disabled={busy || !mappingComplete(vars, mapping)}
              >
                {busy ? "Checking…" : "Run dry-run"}
              </Button>
            </div>
          </div>
        )}
        {step === 4 && dry && (
          <div className="wa-form" data-testid="wa-dry-result">
            <h2>Dry-run summary</h2>
            <div className="wa-metrics wa-metrics-3">
              <StatCard label="Eligible now" value={dry.eligible} />
              <StatCard
                label="Permanently skipped"
                value={dry.terminal_skips.count}
              />
              <StatCard
                label="Blocked for now"
                value={dry.deferrable_blocks.count}
              />
            </div>
            <div className="wa-two">
              <ReasonList
                title="Why contacts are skipped"
                reasons={dry.terminal_skips.reasons}
              />
              <ReasonList
                title="Why contacts are deferred"
                reasons={dry.deferrable_blocks.reasons}
              />
            </div>
            <p>
              <strong>Estimated time under the daily cap:</strong>{" "}
              {dry.estimated_days_to_finish} day(s). Cap: {dry.daily_cap}; used
              in the rolling 24 hours: {dry.used_in_rolling_24h}.
            </p>
            <div className="action-row">
              <Button variant="quiet" onClick={() => setStep(3)}>
                Back
              </Button>
              <Button data-testid="wa-next" onClick={() => setStep(5)}>
                Review and confirm
              </Button>
            </div>
          </div>
        )}
        {step === 5 && dry && (
          <div className="wa-form">
            <h2>Confirm and start</h2>
            <p>
              You are about to start <strong dir="auto">{name}</strong> with
              template <strong dir="auto">{template?.name}</strong>. Up to{" "}
              {dry.eligible} recipients are eligible immediately;{" "}
              {dry.deferrable_blocks.count} may be sent later when temporary
              blocks clear.
            </p>
            {outreachDisabled && (
              <Notice
                message="Starting is disabled because WhatsApp outreach is globally disabled."
                tone="error"
                scope="item"
              />
            )}
            <label className="wa-attest">
              <input
                type="checkbox"
                data-testid="wa-reviewed"
                checked={reviewed}
                onChange={(event) => setReviewed(event.target.checked)}
              />
              <span>
                I reviewed the audience and dry-run results and want to start
                this campaign.
              </span>
            </label>
            <div className="action-row">
              <Button variant="quiet" onClick={() => setStep(4)}>
                Back
              </Button>
              <Button
                data-testid="wa-start"
                disabled={outreachDisabled || busy || !reviewed}
                onClick={start}
              >
                {busy ? "Starting…" : "Confirm and start"}
              </Button>
            </div>
          </div>
        )}
      </Card>
    </div>
  );
}

function ReasonList({
  title,
  reasons,
}: {
  title: string;
  reasons: Record<string, number>;
}) {
  const entries = Object.entries(reasons);
  return (
    <div>
      <h3>{title}</h3>
      {entries.length ? (
        <ul className="wa-counts">
          {entries.map(([reason, count]) => (
            <li key={reason}>
              <span>{reasonLabel(reason)}</span>
              <strong>{count}</strong>
            </li>
          ))}
        </ul>
      ) : (
        <p className="muted">None</p>
      )}
    </div>
  );
}
