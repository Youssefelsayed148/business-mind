"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Upload, X } from "lucide-react";
import { useWhatsapp } from "@/components/whatsapp/WhatsappShell";
import { useToast } from "@/components/ToastProvider";
import { Badge, statusLabel } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { DataState } from "@/components/ui/DataState";
import { EmptyState } from "@/components/ui/EmptyState";
import { PageHeader } from "@/components/ui/PageHeader";
import { Panel } from "@/components/ui/Panel";
import { TableSkeleton } from "@/components/ui/Skeleton";
import {
  TableWrap,
  tableClass,
  tdClass,
  thClass,
  theadRowClass,
  trClass,
} from "@/components/ui/Table";
import { api } from "@/lib/api";
import {
  formatDate,
  type WhatsappContact,
  type WhatsappContactDetail,
} from "@/lib/whatsapp";
import { useWorkspaceCan } from "@/lib/workspacePermissions";

const ATTESTATION =
  "I confirm these people gave permission to receive WhatsApp messages from this business";

function ContactDrawer({
  id,
  canManage,
  onClose,
  onChanged,
}: {
  id: string;
  canManage: boolean;
  onClose: () => void;
  onChanged: () => void;
}) {
  const [contact, setContact] = useState<WhatsappContactDetail | null>(null);
  const [proof, setProof] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const toast = useToast();
  const load = useCallback(
    () =>
      api
        .get<WhatsappContactDetail>(`/whatsapp/contacts/${id}`)
        .then(setContact)
        .catch((e) =>
          setError(e instanceof Error ? e.message : "Could not load contact"),
        ),
    [id],
  );
  useEffect(() => {
    void load();
  }, [load]);
  async function consent(action: "grant" | "revoke") {
    setBusy(true);
    setError(null);
    try {
      await api.post(`/whatsapp/contacts/${id}/${action}`, {
        proof: proof.trim(),
      });
      toast.success(
        action === "grant"
          ? "Manual permission recorded."
          : "Contact opted out.",
      );
      setProof("");
      await load();
      onChanged();
    } catch (e) {
      const message = e instanceof Error ? e.message : "Update failed";
      setError(message);
      toast.error(message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div
      className="fixed inset-0 z-50 flex justify-end bg-slate-950/30"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <aside className="h-full w-full max-w-xl overflow-y-auto bg-white shadow-2xl">
        <div className="sticky top-0 flex items-start justify-between border-b border-line bg-white p-5">
          <div>
            <h2 className="text-xl font-bold" dir="auto">
              {contact?.display_name || "Contact"}
            </h2>
            <p className="mt-1 font-mono text-sm text-muted">
              {contact?.wa_id}
            </p>
          </div>
          <button onClick={onClose} aria-label="Close contact">
            <X />
          </button>
        </div>
        <div className="grid gap-5 p-5">
          <DataState loading={!contact && !error} error={error} />
          {contact ? (
            <>
              <div className="grid grid-cols-2 gap-3 rounded-xl bg-slate-50 p-4">
                <div>
                  <p className="text-xs font-bold uppercase text-muted">
                    Consent status
                  </p>
                  <div className="mt-2">
                    <Badge value={contact.marketing_consent} />
                  </div>
                </div>
                <div>
                  <p className="text-xs font-bold uppercase text-muted">
                    Consent source
                  </p>
                  <p className="mt-2 text-sm font-semibold">
                    {statusLabel(contact.consent_source)}
                  </p>
                </div>
              </div>
              {canManage ? (
                <Panel className="grid gap-3">
                  <h3 className="font-bold">Change consent</h3>
                  <label className="grid gap-1.5 text-sm font-semibold">
                    Proof note
                    <textarea
                      value={proof}
                      onChange={(e) => setProof(e.target.value)}
                      className="min-h-24 rounded-lg border border-line p-3 font-normal"
                      placeholder="Where and when did this person grant permission?"
                    />
                  </label>
                  <p className="text-xs text-muted">
                    A proof note is mandatory for a manual grant and is retained
                    in consent history.
                  </p>
                  <div className="flex gap-2">
                    <Button
                      onClick={() => consent("grant")}
                      disabled={!proof.trim() || busy}
                    >
                      Grant manually
                    </Button>
                    <Button
                      variant="danger"
                      onClick={() => consent("revoke")}
                      disabled={!proof.trim() || busy}
                    >
                      Revoke
                    </Button>
                  </div>
                </Panel>
              ) : null}
              <div>
                <h3 className="font-bold">Consent history</h3>
                {contact.consent_history.length === 0 ? (
                  <p className="mt-3 text-sm text-muted">
                    No consent events recorded.
                  </p>
                ) : (
                  <ol className="mt-3 grid gap-3">
                    {contact.consent_history.map((event) => (
                      <li
                        key={event.id}
                        className="rounded-lg border border-line p-3"
                      >
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <span className="font-semibold">
                            {statusLabel(event.event_type)} ·{" "}
                            {statusLabel(event.source)}
                          </span>
                          <time className="text-xs text-muted">
                            {formatDate(event.created_at)}
                          </time>
                        </div>
                        <pre
                          dir="auto"
                          className="mt-2 whitespace-pre-wrap break-words rounded bg-slate-50 p-2 text-xs text-slate-600"
                        >
                          {JSON.stringify(event.evidence, null, 2)}
                        </pre>
                      </li>
                    ))}
                  </ol>
                )}
              </div>
            </>
          ) : null}
        </div>
      </aside>
    </div>
  );
}

function ImportDialog({
  accountId,
  onClose,
  onDone,
}: {
  accountId: string;
  onClose: () => void;
  onDone: () => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const toast = useToast();
  async function submit() {
    if (!file || !confirmed) return;
    setBusy(true);
    setError(null);
    const body = new FormData();
    body.set("account_id", accountId);
    body.set("attestation", ATTESTATION);
    body.set("file", file);
    try {
      const result = await api.post<{
        imported: number;
        created: number;
        deduplicated: number;
        invalid: number;
      }>("/whatsapp/contacts/import", body);
      const message = `Import complete: ${result.imported} imported, ${result.created} created, ${result.deduplicated} deduplicated, ${result.invalid} invalid.`;
      if (result.invalid > 0)
        toast.warning(
          `${message} Review and correct the invalid rows in the CSV.`,
        );
      else toast.success(message);
      onDone();
      onClose();
    } catch (e) {
      const message = e instanceof Error ? e.message : "Import failed";
      setError(message);
      toast.error(message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-slate-950/40 p-4">
      <div className="w-full max-w-lg rounded-xl bg-white shadow-xl">
        <div className="flex justify-between border-b border-line p-5">
          <div>
            <h2 className="text-lg font-bold">Import contacts</h2>
            <p className="mt-1 text-sm text-muted">
              Upload a CSV with phone numbers and optional display names.
            </p>
          </div>
          <button onClick={onClose}>
            <X />
          </button>
        </div>
        <div className="grid gap-4 p-5">
          <DataState error={error} />
          <input
            type="file"
            accept=".csv,text/csv"
            onChange={(e) => setFile(e.target.files?.[0] || null)}
            className="rounded-lg border border-line p-3 text-sm"
          />
          <label className="flex items-start gap-3 rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm font-semibold text-amber-950">
            <input
              type="checkbox"
              className="mt-1 h-4 w-4"
              checked={confirmed}
              onChange={(e) => setConfirmed(e.target.checked)}
            />
            <span>{ATTESTATION}</span>
          </label>
          <p className="text-xs text-muted">
            The exact statement above is sent to the server and stored with the
            import evidence.
          </p>
        </div>
        <div className="flex justify-end gap-2 border-t border-line p-5">
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={submit} disabled={!file || !confirmed || busy}>
            {busy ? "Importing…" : "Import"}
          </Button>
        </div>
      </div>
    </div>
  );
}

export default function ContactsPage() {
  const { account } = useWhatsapp();
  const canManage = useWorkspaceCan("manage_contacts");
  const [contacts, setContacts] = useState<WhatsappContact[]>([]);
  const [search, setSearch] = useState("");
  const [consent, setConsent] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [importing, setImporting] = useState(false);
  const query = useMemo(() => {
    const p = new URLSearchParams({ account_id: account!.id });
    if (search.trim()) p.set("search", search.trim());
    if (consent) p.set("consent", consent);
    return p.toString();
  }, [account, search, consent]);
  const load = () => {
    setLoading(true);
    setError(null);
    api
      .get<{ items: WhatsappContact[] }>(`/whatsapp/contacts?${query}`)
      .then((r) => setContacts(r.items))
      .catch((e) =>
        setError(e instanceof Error ? e.message : "Could not load contacts"),
      )
      .finally(() => setLoading(false));
  };
  useEffect(load, [query]);
  return (
    <div className="grid gap-6">
      <PageHeader
        title="WhatsApp contacts"
        description="Review contact identity, permission status, its source, and the complete consent audit trail."
      >
        {canManage ? (
          <Button className="gap-2" onClick={() => setImporting(true)}>
            <Upload className="h-4 w-4" />
            Import CSV
          </Button>
        ) : null}
      </PageHeader>
      <Panel>
        <div className="mb-5 grid gap-3 sm:grid-cols-[1fr_220px]">
          <label className="grid gap-1 text-sm font-semibold">
            Search
            <input
              className="h-10 rounded-lg border border-line px-3 font-normal"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Name or phone number"
            />
          </label>
          <label className="grid gap-1 text-sm font-semibold">
            Consent status
            <select
              className="h-10 rounded-lg border border-line px-3 font-normal"
              value={consent}
              onChange={(e) => setConsent(e.target.value)}
            >
              <option value="">All statuses</option>
              <option value="unknown">Unknown</option>
              <option value="opted_in">Opted in</option>
              <option value="opted_out">Opted out</option>
            </select>
          </label>
        </div>
        <DataState error={error} />
        {loading ? <TableSkeleton rows={5} columns={5} /> : null}
        {!loading && !error && contacts.length === 0 ? (
          <EmptyState
            title="No contacts found"
            message="Try another filter, import a consented list, or wait for inbound WhatsApp activity."
          />
        ) : null}
        {contacts.length ? (
          <TableWrap>
            <table className={tableClass}>
              <thead>
                <tr className={theadRowClass}>
                  <th className={thClass}>Contact</th>
                  <th className={thClass}>Phone</th>
                  <th className={thClass}>Consent status</th>
                  <th className={thClass}>Consent source</th>
                  <th className={thClass}>Updated</th>
                </tr>
              </thead>
              <tbody>
                {contacts.map((c) => (
                  <tr
                    key={c.id}
                    className={`${trClass} cursor-pointer`}
                    onClick={() => setSelected(c.id)}
                  >
                    <td className={tdClass}>
                      <span dir="auto" className="font-semibold">
                        {c.display_name || "No display name"}
                      </span>
                    </td>
                    <td className={`${tdClass} font-mono`}>{c.wa_id}</td>
                    <td className={tdClass}>
                      <Badge value={c.marketing_consent} />
                    </td>
                    <td className={tdClass}>{statusLabel(c.consent_source)}</td>
                    <td className={tdClass}>
                      {formatDate(c.consent_at || c.created_at)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableWrap>
        ) : null}
      </Panel>
      {selected ? (
        <ContactDrawer
          id={selected}
          canManage={canManage}
          onClose={() => setSelected(null)}
          onChanged={load}
        />
      ) : null}
      {importing ? (
        <ImportDialog
          accountId={account!.id}
          onClose={() => setImporting(false)}
          onDone={load}
        />
      ) : null}
    </div>
  );
}
