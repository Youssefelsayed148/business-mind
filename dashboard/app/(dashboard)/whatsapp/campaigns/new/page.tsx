"use client";
import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { useWhatsapp } from "@/components/whatsapp/WhatsappShell";
import { useToast } from "@/components/ToastProvider";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { DataState } from "@/components/ui/DataState";
import { PageHeader } from "@/components/ui/PageHeader";
import { Panel } from "@/components/ui/Panel";
import { api } from "@/lib/api";
import {
  reasonLabel,
  type DryRun,
  type WhatsappCampaign,
  type WhatsappContact,
  type WhatsappTemplate,
} from "@/lib/whatsapp";
const indexes = (t?: WhatsappTemplate) =>
  Array.from(
    new Set(
      Array.from(
        (t?.components.map((c) => c.text || "").join(" ") || "").matchAll(
          /{{\s*(\d+)\s*}}/g,
        ),
        (m) => Number(m[1]),
      ),
    ),
  ).sort((a, b) => a - b);
export default function NewCampaignPage() {
  const { account, outreachDisabled } = useWhatsapp();
  const router = useRouter();
  const toast = useToast();
  const [step, setStep] = useState(1);
  const [templates, setTemplates] = useState<WhatsappTemplate[]>([]);
  const [contactCount, setContactCount] = useState(0);
  const [templateId, setTemplateId] = useState("");
  const [name, setName] = useState("");
  const [mapping, setMapping] = useState<
    Record<number, { source: string; value?: string; fallback?: string }>
  >({});
  const [campaign, setCampaign] = useState<WhatsappCampaign | null>(null);
  const [dry, setDry] = useState<DryRun | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    Promise.all([
      api.get<WhatsappTemplate[]>(
        `/whatsapp/templates?account_id=${account!.id}&template_status=approved`,
      ),
      api.get<{ items: WhatsappContact[] }>(
        `/whatsapp/contacts?account_id=${account!.id}&limit=200`,
      ),
    ])
      .then(([t, c]) => {
        setTemplates(t.filter((x) => x.category !== "authentication"));
        setTemplateId(t.find((x) => x.category !== "authentication")?.id || "");
        setContactCount(c.items.length);
      })
      .catch((e) =>
        setError(e instanceof Error ? e.message : "Could not prepare campaign"),
      );
  }, [account]);
  const template = templates.find((t) => t.id === templateId);
  const vars = useMemo(() => indexes(template), [template]);
  async function runDry() {
    setBusy(true);
    setError(null);
    try {
      const variable_mapping = Object.fromEntries(
        vars.map((i) => [
          String(i),
          mapping[i] || { source: "literal", value: "" },
        ]),
      );
      let current = campaign;
      if (!current) {
        current = await api.post<WhatsappCampaign>("/whatsapp/campaigns", {
          account_id: account!.id,
          template_id: templateId,
          name,
          throttle_per_minute: 30,
          variable_mapping,
        });
        setCampaign(current);
      }
      const result = await api.post<DryRun>(
        `/whatsapp/campaigns/${current.id}/dry-run`,
        { variable_mapping },
      );
      setDry(result);
      setStep(4);
    } catch (e) {
      const m = e instanceof Error ? e.message : "Dry-run failed";
      setError(m);
      toast.error(m);
    } finally {
      setBusy(false);
    }
  }
  async function start() {
    if (!campaign) return;
    setBusy(true);
    try {
      await api.post(`/whatsapp/campaigns/${campaign.id}/start`);
      toast.success("Campaign queued to start.");
      router.push(`/whatsapp/campaigns/${campaign.id}`);
    } catch (e) {
      const m = e instanceof Error ? e.message : "Could not start campaign";
      setError(m);
      toast.error(m);
    } finally {
      setBusy(false);
    }
  }
  const labels = ["Template", "Audience", "Variables", "Dry-run", "Confirm"];
  return (
    <div className="grid gap-6">
      <PageHeader
        title="Create WhatsApp campaign"
        description="The campaign is only started after a server-side eligibility dry-run and your confirmation."
      />
      <div className="grid grid-cols-5 gap-2">
        {labels.map((label, i) => (
          <div
            key={label}
            className={`rounded-lg border p-2 text-center text-xs font-bold ${step === i + 1 ? "border-emerald-300 bg-emerald-50 text-emerald-800" : "border-line bg-white text-muted"}`}
          >
            {i + 1}. {label}
          </div>
        ))}
      </div>
      <DataState error={error} />
      <Panel>
        {step === 1 ? (
          <div className="grid gap-4">
            <h2 className="text-lg font-bold">Choose an approved template</h2>
            {templates.length === 0 ? (
              <p className="rounded-lg bg-amber-50 p-3 text-sm text-amber-900">
                No approved marketing or utility template is available. Submit
                and sync a template first.
              </p>
            ) : null}
            <label className="grid gap-1 text-sm font-semibold">
              Template
              <select
                className="h-10 rounded-lg border border-line px-3 font-normal"
                value={templateId}
                onChange={(e) => setTemplateId(e.target.value)}
              >
                {templates.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.name} · {t.category}
                  </option>
                ))}
              </select>
            </label>
            <label className="grid gap-1 text-sm font-semibold">
              Campaign name
              <input
                className="h-10 rounded-lg border border-line px-3 font-normal"
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            </label>
            <Button
              onClick={() => setStep(2)}
              disabled={!templateId || !name.trim()}
            >
              Continue
            </Button>
          </div>
        ) : null}
        {step === 2 ? (
          <div className="grid gap-4">
            <h2 className="text-lg font-bold">Audience</h2>
            <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-5">
              <p className="font-bold">
                All eligible contacts for this WhatsApp number
              </p>
              <p className="mt-2 text-sm text-emerald-900">
                {contactCount}
                {contactCount === 200 ? "+" : ""} contacts currently loaded. The
                server freezes the audience at start and excludes contacts
                without permission, opt-outs, and other terminally ineligible
                recipients.
              </p>
            </div>
            <p className="text-sm text-muted">
              This backend does not currently support saved segments or
              per-campaign audience filters.
            </p>
            <div className="flex gap-2">
              <Button variant="secondary" onClick={() => setStep(1)}>
                Back
              </Button>
              <Button onClick={() => setStep(3)}>Use this audience</Button>
            </div>
          </div>
        ) : null}
        {step === 3 ? (
          <div className="grid gap-4">
            <h2 className="text-lg font-bold">Map template variables</h2>
            {vars.length === 0 ? (
              <p className="text-sm text-muted">
                This template has no variables.
              </p>
            ) : null}
            {vars.map((i) => {
              const spec = mapping[i] || { source: "literal", value: "" };
              return (
                <div
                  key={i}
                  className="grid gap-2 rounded-lg border border-line p-4 sm:grid-cols-[130px_180px_1fr]"
                >
                  <strong>{`{{${i}}}`}</strong>
                  <select
                    className="h-10 rounded-lg border border-line px-3"
                    value={spec.source}
                    onChange={(e) =>
                      setMapping((m) => ({
                        ...m,
                        [i]: { source: e.target.value },
                      }))
                    }
                  >
                    <option value="literal">Fixed text</option>
                    <option value="contact.display_name">Contact name</option>
                  </select>
                  <input
                    className="h-10 rounded-lg border border-line px-3"
                    placeholder={
                      spec.source === "literal"
                        ? "Value"
                        : "Fallback when name is missing"
                    }
                    value={
                      spec.source === "literal"
                        ? spec.value || ""
                        : spec.fallback || ""
                    }
                    onChange={(e) =>
                      setMapping((m) => ({
                        ...m,
                        [i]:
                          spec.source === "literal"
                            ? { source: spec.source, value: e.target.value }
                            : { source: spec.source, fallback: e.target.value },
                      }))
                    }
                  />
                </div>
              );
            })}
            <div className="flex gap-2">
              <Button variant="secondary" onClick={() => setStep(2)}>
                Back
              </Button>
              <Button
                onClick={runDry}
                disabled={
                  busy ||
                  vars.some((i) => {
                    const s = mapping[i];
                    return (
                      !s ||
                      (s.source === "literal"
                        ? !s.value?.trim()
                        : !s.fallback?.trim())
                    );
                  })
                }
              >
                {busy ? "Checking…" : "Run dry-run"}
              </Button>
            </div>
          </div>
        ) : null}
        {step === 4 && dry ? (
          <div className="grid gap-5">
            <h2 className="text-lg font-bold">Dry-run summary</h2>
            <div className="grid gap-3 sm:grid-cols-3">
              <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-4">
                <p className="text-sm font-semibold">Eligible now</p>
                <p className="mt-2 text-3xl font-bold">{dry.eligible}</p>
              </div>
              <div className="rounded-lg border border-red-200 bg-red-50 p-4">
                <p className="text-sm font-semibold">Permanently skipped</p>
                <p className="mt-2 text-3xl font-bold">
                  {dry.terminal_skips.count}
                </p>
              </div>
              <div className="rounded-lg border border-amber-200 bg-amber-50 p-4">
                <p className="text-sm font-semibold">Blocked for now</p>
                <p className="mt-2 text-3xl font-bold">
                  {dry.deferrable_blocks.count}
                </p>
              </div>
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <ReasonList
                title="Why contacts are skipped"
                reasons={dry.terminal_skips.reasons}
              />
              <ReasonList
                title="Why contacts are deferred"
                reasons={dry.deferrable_blocks.reasons}
              />
            </div>
            <p className="rounded-lg bg-slate-50 p-4 text-sm">
              <strong>Estimated time under the daily cap:</strong>{" "}
              {dry.estimated_days_to_finish} day(s). Cap: {dry.daily_cap}; used
              in the rolling 24 hours: {dry.used_in_rolling_24h}.
            </p>
            <div className="flex gap-2">
              <Button variant="secondary" onClick={() => setStep(3)}>
                Back
              </Button>
              <Button onClick={() => setStep(5)}>Review and confirm</Button>
            </div>
          </div>
        ) : null}
        {step === 5 && dry ? (
          <div className="grid gap-4">
            <h2 className="text-lg font-bold">Confirm and start</h2>
            <p className="text-sm">
              You are about to start <strong dir="auto">{name}</strong> with
              template <strong dir="auto">{template?.name}</strong>. Up to{" "}
              {dry.eligible} recipients are eligible immediately;{" "}
              {dry.deferrable_blocks.count} may be sent later when temporary
              blocks clear.
            </p>
            {outreachDisabled ? (
              <p className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
                Starting is disabled because WhatsApp outreach is globally
                disabled.
              </p>
            ) : null}
            <label className="flex items-start gap-3 rounded-lg border border-line p-4 text-sm">
              <input id="confirm" type="checkbox" className="mt-1" />
              <span>
                I reviewed the audience and dry-run results and want to start
                this campaign.
              </span>
            </label>
            <div className="flex gap-2">
              <Button variant="secondary" onClick={() => setStep(4)}>
                Back
              </Button>
              <Button
                disabled={outreachDisabled || busy}
                onClick={() => {
                  const box = document.getElementById(
                    "confirm",
                  ) as HTMLInputElement;
                  if (!box.checked) {
                    toast.warning(
                      "Confirm that you reviewed the dry-run first.",
                    );
                    return;
                  }
                  start();
                }}
              >
                {busy ? "Starting…" : "Confirm and start"}
              </Button>
            </div>
          </div>
        ) : null}
      </Panel>
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
      <h3 className="font-bold">{title}</h3>
      {entries.length ? (
        <ul className="mt-2 grid gap-2">
          {entries.map(([reason, count]) => (
            <li
              key={reason}
              className="flex justify-between rounded-lg border border-line p-3 text-sm"
            >
              <span>{reasonLabel(reason)}</span>
              <Badge value={String(count)} />
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-2 text-sm text-muted">None</p>
      )}
    </div>
  );
}
