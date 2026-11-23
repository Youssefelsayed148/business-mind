"use client";

import { useEffect, useMemo, useState } from "react";
import { Plus, RefreshCw, Send, X } from "lucide-react";
import { useWhatsapp } from "@/components/whatsapp/WhatsappShell";
import { useToast } from "@/components/ToastProvider";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { DataState } from "@/components/ui/DataState";
import { EmptyState } from "@/components/ui/EmptyState";
import { PageHeader } from "@/components/ui/PageHeader";
import { Panel } from "@/components/ui/Panel";
import { api } from "@/lib/api";
import {
  formatDate,
  type WhatsappContact,
  type WhatsappTemplate,
} from "@/lib/whatsapp";
import { useWorkspaceCan } from "@/lib/workspacePermissions";

const placeholderIndexes = (text: string) =>
  Array.from(
    new Set(
      Array.from(text.matchAll(/{{\s*(\d+)\s*}}/g), (match) =>
        Number(match[1]),
      ),
    ),
  ).sort((a, b) => a - b);
const renderPreview = (text: string, examples: Record<number, string>) =>
  text.replace(/{{\s*(\d+)\s*}}/g, (_, n) => examples[Number(n)] || `{{${n}}}`);

function Editor({
  template,
  accountId,
  onClose,
  onSaved,
}: {
  template?: WhatsappTemplate;
  accountId: string;
  onClose: () => void;
  onSaved: () => void;
}) {
  const bodyComponent = template?.components.find(
    (c) => c.type.toLowerCase() === "body",
  );
  const initialText = bodyComponent?.text || "";
  const [name, setName] = useState(template?.name || "");
  const [language, setLanguage] = useState(template?.language || "en_US");
  const [category, setCategory] = useState(template?.category || "marketing");
  const [body, setBody] = useState(initialText);
  const [examples, setExamples] = useState<Record<number, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const toast = useToast();
  const indexes = useMemo(() => placeholderIndexes(body), [body]);
  async function save() {
    setBusy(true);
    setError(null);
    const components = [
      {
        type: "BODY",
        text: body,
        example: indexes.length
          ? { body_text: indexes.map((i) => examples[i] || "") }
          : undefined,
      },
    ];
    try {
      if (template)
        await api.patch(`/whatsapp/templates/${template.id}`, {
          name,
          language,
          category,
          components,
        });
      else
        await api.post("/whatsapp/templates", {
          account_id: accountId,
          name,
          language,
          category,
          components,
        });
      toast.success("Template draft saved.");
      onSaved();
      onClose();
    } catch (e) {
      const m = e instanceof Error ? e.message : "Could not save template";
      setError(m);
      toast.error(m);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-slate-950/40 p-4">
      <div className="max-h-[94vh] w-full max-w-4xl overflow-y-auto rounded-xl bg-white shadow-xl">
        <div className="flex justify-between border-b border-line p-5">
          <div>
            <h2 className="text-xl font-bold">
              {template ? "Edit template" : "Create template"}
            </h2>
            <p className="mt-1 text-sm text-muted">
              Use numbered placeholders such as {"{{1}}"}, then supply an
              example for every number.
            </p>
          </div>
          <button onClick={onClose}>
            <X />
          </button>
        </div>
        <div className="grid gap-5 p-5 lg:grid-cols-2">
          <div className="grid content-start gap-4">
            <DataState error={error} />
            <label className="grid gap-1 text-sm font-semibold">
              Template name
              <input
                className="h-10 rounded-lg border border-line px-3 font-normal"
                value={name}
                onChange={(e) =>
                  setName(
                    e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, "_"),
                  )
                }
                placeholder="seasonal_offer"
              />
            </label>
            <div className="grid grid-cols-2 gap-3">
              <label className="grid gap-1 text-sm font-semibold">
                Language
                <input
                  className="h-10 rounded-lg border border-line px-3 font-normal"
                  value={language}
                  onChange={(e) => setLanguage(e.target.value)}
                />
              </label>
              <label className="grid gap-1 text-sm font-semibold">
                Category
                <select
                  className="h-10 rounded-lg border border-line px-3 font-normal"
                  value={category}
                  onChange={(e) => setCategory(e.target.value)}
                >
                  <option value="marketing">Marketing</option>
                  <option value="utility">Utility</option>
                  <option value="authentication">Authentication</option>
                </select>
              </label>
            </div>
            <label className="grid gap-1 text-sm font-semibold">
              Message body
              <textarea
                dir="auto"
                className="min-h-36 rounded-lg border border-line p-3 font-normal"
                value={body}
                onChange={(e) => setBody(e.target.value)}
                placeholder="Hello {{1}}, your offer is ready."
              />
            </label>
            {indexes.map((i) => (
              <label key={i} className="grid gap-1 text-sm font-semibold">
                Example for {`{{${i}}}`}
                <input
                  dir="auto"
                  className="h-10 rounded-lg border border-line px-3 font-normal"
                  value={examples[i] || ""}
                  onChange={(e) =>
                    setExamples((old) => ({ ...old, [i]: e.target.value }))
                  }
                />
              </label>
            ))}
          </div>
          <div>
            <p className="mb-2 text-sm font-bold">Live preview</p>
            <div className="min-h-72 rounded-[2rem] bg-[#e9edef] p-5 shadow-inner">
              <div
                dir="auto"
                className="ml-auto max-w-[86%] whitespace-pre-wrap rounded-lg bg-[#d9fdd3] p-3 text-sm shadow"
              >
                {renderPreview(body, examples) ||
                  "Your message preview appears here."}
                <div className="mt-2 text-right text-[10px] text-slate-500">
                  12:00
                </div>
              </div>
            </div>
          </div>
        </div>
        <div className="flex justify-end gap-2 border-t border-line p-5">
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button
            onClick={save}
            disabled={
              busy ||
              !name ||
              !body ||
              indexes.some((i) => !examples[i]?.trim())
            }
          >
            {busy ? "Saving…" : "Save draft"}
          </Button>
        </div>
      </div>
    </div>
  );
}

function TestSendDialog({
  template,
  onClose,
}: {
  template: WhatsappTemplate;
  onClose: () => void;
}) {
  const { account, outreachDisabled } = useWhatsapp();
  const [contacts, setContacts] = useState<WhatsappContact[]>([]);
  const [contactId, setContactId] = useState("");
  const indexes = useMemo(
    () =>
      placeholderIndexes(
        template.components.map((c) => c.text || "").join(" "),
      ),
    [template],
  );
  const [values, setValues] = useState<Record<number, string>>({});
  const [proof, setProof] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const toast = useToast();
  useEffect(() => {
    api
      .get<{ items: WhatsappContact[] }>(
        `/whatsapp/contacts?account_id=${account!.id}&consent=opted_in`,
      )
      .then((r) => {
        setContacts(r.items);
        setContactId(r.items[0]?.id || "");
      })
      .catch((e) =>
        setError(e instanceof Error ? e.message : "Could not load contacts"),
      );
  }, [account]);
  async function grant() {
    if (!contactId) return;
    setBusy(true);
    try {
      await api.post(`/whatsapp/contacts/${contactId}/grant`, {
        proof: proof.trim(),
      });
      toast.success(
        "Manual permission recorded; this number can now receive the test.",
      );
    } catch (e) {
      const m = e instanceof Error ? e.message : "Grant failed";
      setError(m);
      toast.error(m);
    } finally {
      setBusy(false);
    }
  }
  async function send() {
    setBusy(true);
    setError(null);
    try {
      const r = await api.post<{ accepted: boolean }>(
        `/whatsapp/templates/${template.id}/test-send`,
        {
          contact_id: contactId,
          variables: Object.fromEntries(
            indexes.map((i) => [String(i), values[i]]),
          ),
        },
      );
      r.accepted
        ? toast.success("Test message accepted.")
        : toast.warning("The test send was refused.");
      if (r.accepted) onClose();
    } catch (e) {
      const m = e instanceof Error ? e.message : "Test send failed";
      setError(m);
      toast.error(m);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-slate-950/40 p-4">
      <div className="w-full max-w-xl rounded-xl bg-white shadow-xl">
        <div className="flex justify-between border-b border-line p-5">
          <div>
            <h2 className="text-lg font-bold">Send test to my own number</h2>
            <p className="mt-1 text-sm text-muted">
              For Meta App Review, first select your number and record a manual
              grant with proof. The server only sends tests to manually opted-in
              contacts.
            </p>
          </div>
          <button onClick={onClose}>
            <X />
          </button>
        </div>
        <div className="grid gap-4 p-5">
          <DataState error={error} />
          {outreachDisabled ? (
            <p className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
              Test sending is unavailable while outreach is globally disabled.
            </p>
          ) : null}
          <label className="grid gap-1 text-sm font-semibold">
            My opted-in number
            <select
              className="h-10 rounded-lg border border-line px-3 font-normal"
              value={contactId}
              onChange={(e) => setContactId(e.target.value)}
            >
              {contacts.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.display_name || c.wa_id} · {c.wa_id}
                </option>
              ))}
            </select>
          </label>
          {contacts.length === 0 ? (
            <p className="rounded-lg bg-amber-50 p-3 text-sm text-amber-900">
              No opted-in contacts found. Import or receive the contact first,
              then grant permission on Contacts.
            </p>
          ) : null}
          <label className="grid gap-1 text-sm font-semibold">
            Manual grant proof note
            <textarea
              className="min-h-20 rounded-lg border border-line p-3 font-normal"
              value={proof}
              onChange={(e) => setProof(e.target.value)}
              placeholder="I control this number and consent to this App Review test."
            />
          </label>
          <Button
            variant="secondary"
            onClick={grant}
            disabled={!contactId || !proof.trim() || busy}
          >
            Record manual grant first
          </Button>
          {indexes.map((i) => (
            <label key={i} className="grid gap-1 text-sm font-semibold">
              Value for {`{{${i}}}`}
              <input
                className="h-10 rounded-lg border border-line px-3 font-normal"
                value={values[i] || ""}
                onChange={(e) =>
                  setValues((v) => ({ ...v, [i]: e.target.value }))
                }
              />
            </label>
          ))}
        </div>
        <div className="flex justify-end gap-2 border-t border-line p-5">
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button
            onClick={send}
            disabled={
              outreachDisabled ||
              !contactId ||
              busy ||
              indexes.some((i) => !values[i]?.trim())
            }
          >
            Send test
          </Button>
        </div>
      </div>
    </div>
  );
}

export default function TemplatesPage() {
  const { account } = useWhatsapp();
  const canManage = useWorkspaceCan("manage_templates");
  const [items, setItems] = useState<WhatsappTemplate[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<WhatsappTemplate | "new" | null>(null);
  const [testing, setTesting] = useState<WhatsappTemplate | null>(null);
  const toast = useToast();
  const load = () => {
    setLoading(true);
    setError(null);
    api
      .get<WhatsappTemplate[]>(`/whatsapp/templates?account_id=${account!.id}`)
      .then(setItems)
      .catch((e) =>
        setError(e instanceof Error ? e.message : "Could not load templates"),
      )
      .finally(() => setLoading(false));
  };
  useEffect(load, [account]);
  async function action(template: WhatsappTemplate, kind: "submit" | "sync") {
    try {
      if (kind === "submit")
        await api.post(`/whatsapp/templates/${template.id}/submit`);
      else await api.post(`/whatsapp/accounts/${account!.id}/templates/sync`);
      toast.success(
        kind === "submit"
          ? "Template submitted to Meta."
          : "Template statuses synced.",
      );
      load();
    } catch (e) {
      const m = e instanceof Error ? e.message : "Action failed";
      setError(m);
      toast.error(m);
    }
  }
  return (
    <div className="grid gap-6">
      <PageHeader
        title="WhatsApp templates"
        description="Draft message templates, preview variables, submit them to Meta, and record the App Review test-send flow."
      >
        {canManage ? (
          <>
            <Button
              variant="secondary"
              className="gap-2"
              onClick={() =>
                items[0]
                  ? action(items[0], "sync")
                  : api
                      .post(`/whatsapp/accounts/${account!.id}/templates/sync`)
                      .then(load)
              }
            >
              <RefreshCw className="h-4 w-4" />
              Sync Meta
            </Button>
            <Button className="gap-2" onClick={() => setEditing("new")}>
              <Plus className="h-4 w-4" />
              New template
            </Button>
          </>
        ) : null}
      </PageHeader>
      <DataState error={error} />
      {loading ? <DataState loading /> : null}
      {!loading && !error && items.length === 0 ? (
        <EmptyState
          title="No templates"
          message="Create a draft or sync templates already present in Meta."
        />
      ) : null}
      <div className="grid gap-4 lg:grid-cols-2">
        {items.map((t) => (
          <Panel key={t.id}>
            <div className="flex items-start justify-between gap-3">
              <div>
                <h2 className="font-bold" dir="auto">
                  {t.name}
                </h2>
                <p className="mt-1 text-xs text-muted">
                  {t.language} · {t.category}
                </p>
              </div>
              <Badge value={t.status} />
            </div>
            {t.rejection_reason ? (
              <p className="mt-3 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
                <strong>Rejection reason:</strong>{" "}
                <span dir="auto">{t.rejection_reason}</span>
              </p>
            ) : null}
            <div
              dir="auto"
              className="mt-4 whitespace-pre-wrap rounded-lg bg-slate-50 p-3 text-sm"
            >
              {t.components
                .map((c) => c.text)
                .filter(Boolean)
                .join("\n") || "No text component"}
            </div>
            <p className="mt-3 text-xs text-muted">
              Last synced: {formatDate(t.last_synced_at)}
            </p>
            {canManage ? (
              <div className="mt-4 flex flex-wrap gap-2">
                {["draft", "rejected"].includes(t.status) ? (
                  <>
                    <Button variant="secondary" onClick={() => setEditing(t)}>
                      Edit
                    </Button>
                    <Button onClick={() => action(t, "submit")}>
                      Submit to Meta
                    </Button>
                  </>
                ) : null}
                {t.status === "approved" ? (
                  <Button
                    variant="stats"
                    className="gap-2"
                    onClick={() => setTesting(t)}
                  >
                    <Send className="h-4 w-4" />
                    Send test to my own number
                  </Button>
                ) : null}
              </div>
            ) : null}
          </Panel>
        ))}
      </div>
      {editing ? (
        <Editor
          template={editing === "new" ? undefined : editing}
          accountId={account!.id}
          onClose={() => setEditing(null)}
          onSaved={load}
        />
      ) : null}
      {testing ? (
        <TestSendDialog template={testing} onClose={() => setTesting(null)} />
      ) : null}
    </div>
  );
}
