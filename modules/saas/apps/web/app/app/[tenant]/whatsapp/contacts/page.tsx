"use client";

import { useEffect, useMemo, useState } from "react";

import { manyRequest } from "@/lib/many";
import { PageState } from "@/lib/page-state";
import { useManyData } from "@/lib/use-many";
import {
  Button,
  ConfirmAction,
  DataTable,
  Dialog,
  Field,
  Loading,
  Notice,
  PageHeader,
  StatusBadge,
} from "@/lib/ui";
import {
  formatDate,
  statusLabel,
  statusTone,
  type WhatsappContact,
  type WhatsappContactDetail,
} from "@/lib/whatsapp-types";

import { actionMessage, useWhatsapp } from "../whatsapp-shell";

import "@/app/whatsapp-screen.css";

const ATTESTATION =
  "I confirm these people gave permission to receive WhatsApp messages from this business";

type ImportResult = {
  imported: number;
  created: number;
  deduplicated: number;
  invalid: number;
};

export default function WhatsappContactsPage() {
  const { tenantId, account, notify } = useWhatsapp();
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [consent, setConsent] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const [importing, setImporting] = useState(false);

  // Wait for a pause in typing before asking Many again.
  useEffect(() => {
    const timer = setTimeout(() => setSearch(searchInput.trim()), 300);
    return () => clearTimeout(timer);
  }, [searchInput]);

  const query = useMemo(() => {
    const params = new URLSearchParams({ account_id: account.id });
    if (search) params.set("search", search);
    if (consent) params.set("consent", consent);
    return params.toString();
  }, [account.id, search, consent]);

  const { data, status, reload } = useManyData<{ items: WhatsappContact[] }>(
    () =>
      manyRequest(
        { kind: "org", tenantId },
        "GET",
        `whatsapp/contacts?${query}`,
      ),
    query,
    {
      isEmpty: (result) => result.items.length === 0,
      emptyMessage:
        "No contacts found. Try another filter, import a consented list, or wait for inbound WhatsApp activity.",
    },
  );

  return (
    <>
      <PageHeader
        title="WhatsApp contacts"
        purpose="Review contact identity, permission status, its source, and the complete consent audit trail."
        actions={
          <Button
            data-testid="wa-import-open"
            onClick={() => setImporting(true)}
          >
            Import CSV
          </Button>
        }
      />
      <div className="wa-filters">
        <Field label="Search">
          {(control) => (
            <input
              {...control}
              type="search"
              dir="auto"
              value={searchInput}
              placeholder="Name or phone number"
              onChange={(event) => setSearchInput(event.target.value)}
            />
          )}
        </Field>
        <Field label="Consent status">
          {(control) => (
            <select
              {...control}
              data-testid="wa-consent-filter"
              value={consent}
              onChange={(event) => setConsent(event.target.value)}
            >
              <option value="">All statuses</option>
              <option value="unknown">Unknown</option>
              <option value="opted_in">Opted in</option>
              <option value="opted_out">Opted out</option>
            </select>
          )}
        </Field>
      </div>
      <PageState status={status} homeHref={`/app/${tenantId}`}>
        {data && (
          <DataTable
            data-testid="wa-contacts-table"
            caption="WhatsApp contacts"
            rows={data.items}
            rowKey={(row) => row.id}
            columns={[
              {
                key: "contact",
                header: "Contact",
                cell: (row) => (
                  <button
                    type="button"
                    className="wa-row-link"
                    dir="auto"
                    data-testid={`wa-contact-${row.id}`}
                    onClick={() => setSelected(row.id)}
                  >
                    {row.display_name || "No display name"}
                  </button>
                ),
              },
              {
                key: "phone",
                header: "Phone",
                cell: (row) => <bdi dir="ltr">{row.wa_id}</bdi>,
              },
              {
                key: "consent",
                header: "Consent status",
                cell: (row) => (
                  <StatusBadge
                    value={row.marketing_consent}
                    tone={statusTone(row.marketing_consent)}
                  >
                    {statusLabel(row.marketing_consent)}
                  </StatusBadge>
                ),
              },
              {
                key: "source",
                header: "Consent source",
                cell: (row) => statusLabel(row.consent_source),
              },
              {
                key: "updated",
                header: "Updated",
                cell: (row) => formatDate(row.consent_at || row.created_at),
              },
            ]}
          />
        )}
      </PageState>
      <Dialog
        open={selected !== null}
        onClose={() => setSelected(null)}
        title="Contact"
        className="wa-dialog"
        data-testid="wa-contact-dialog"
      >
        {selected && (
          <ContactDetail
            key={selected}
            id={selected}
            onChanged={reload}
            notify={notify}
          />
        )}
      </Dialog>
      <Dialog
        open={importing}
        onClose={() => setImporting(false)}
        title="Import contacts"
        className="wa-dialog"
        data-testid="wa-import-dialog"
      >
        <ImportForm
          onClose={() => setImporting(false)}
          onDone={(result) => {
            const message = `Import complete: ${result.imported} imported, ${result.created} created, ${result.deduplicated} deduplicated, ${result.invalid} invalid.`;
            notify(
              result.invalid > 0
                ? `${message} Review and correct the invalid rows in the CSV.`
                : message,
            );
            reload();
          }}
        />
      </Dialog>
    </>
  );
}

function ContactDetail({
  id,
  onChanged,
  notify,
}: {
  id: string;
  onChanged: () => void;
  notify: (message: string) => void;
}) {
  const { tenantId } = useWhatsapp();
  const { data, status, reload } = useManyData<WhatsappContactDetail>(
    () =>
      manyRequest({ kind: "org", tenantId }, "GET", `whatsapp/contacts/${id}`),
    id,
  );
  const [proof, setProof] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function change(action: "grant" | "revoke") {
    setBusy(true);
    setError(null);
    try {
      await manyRequest(
        { kind: "org", tenantId },
        "POST",
        `whatsapp/contacts/${id}/${action}`,
        { proof: proof.trim() },
      );
      notify(
        action === "grant"
          ? "Manual permission recorded."
          : "Contact opted out.",
      );
      setProof("");
      reload();
      onChanged();
    } catch (caught) {
      setError(actionMessage(caught, "Could not update the consent."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <PageState status={status} homeHref={`/app/${tenantId}`}>
      {data && (
        <div className="wa-form" data-testid="wa-contact-detail">
          <div>
            <h3 dir="auto">{data.display_name || "Contact"}</h3>
            <p dir="ltr" className="wa-mono">
              {data.wa_id}
            </p>
          </div>
          <dl className="wa-facts">
            <div>
              <dt>Consent status</dt>
              <dd>
                <StatusBadge
                  value={data.marketing_consent}
                  tone={statusTone(data.marketing_consent)}
                >
                  {statusLabel(data.marketing_consent)}
                </StatusBadge>
              </dd>
            </div>
            <div>
              <dt>Consent source</dt>
              <dd>{statusLabel(data.consent_source)}</dd>
            </div>
          </dl>
          {error && <Notice message={error} tone="error" scope="item" />}
          <section className="wa-section">
            <h3>Change consent</h3>
            <Field
              label="Proof note"
              hint="A proof note is mandatory for a manual grant and is retained in consent history."
            >
              {(control) => (
                <textarea
                  {...control}
                  dir="auto"
                  rows={3}
                  value={proof}
                  placeholder="Where and when did this person grant permission?"
                  onChange={(event) => setProof(event.target.value)}
                />
              )}
            </Field>
            <div className="action-row">
              <Button
                data-testid="wa-grant"
                onClick={() => change("grant")}
                disabled={!proof.trim() || busy}
              >
                Grant manually
              </Button>
              <ConfirmAction
                testId="wa-revoke"
                title="Revoke permission?"
                description="The contact is marked as opted out and will not receive campaigns."
                confirmLabel="Revoke"
                disabled={!proof.trim() || busy}
                onConfirm={() => change("revoke")}
              >
                Revoke
              </ConfirmAction>
            </div>
          </section>
          <section className="wa-section">
            <h3>Consent history</h3>
            {data.consent_history.length === 0 ? (
              <p className="muted">No consent events recorded.</p>
            ) : (
              <ol className="wa-history" data-testid="wa-history">
                {data.consent_history.map((event) => (
                  <li key={event.id}>
                    <div className="wa-history-head">
                      <strong>
                        {statusLabel(event.event_type)} ·{" "}
                        {statusLabel(event.source)}
                      </strong>
                      <time>{formatDate(event.created_at)}</time>
                    </div>
                    <pre dir="auto">
                      {JSON.stringify(event.evidence, null, 2)}
                    </pre>
                  </li>
                ))}
              </ol>
            )}
          </section>
        </div>
      )}
    </PageState>
  );
}

function ImportForm({
  onClose,
  onDone,
}: {
  onClose: () => void;
  onDone: (result: ImportResult) => void;
}) {
  const { tenantId, account } = useWhatsapp();
  const [file, setFile] = useState<File | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    if (!file || !confirmed) return;
    setBusy(true);
    setError(null);
    const body = new FormData();
    body.set("account_id", account.id);
    body.set("attestation", ATTESTATION);
    body.set("file", file);
    try {
      const result = await manyRequest<ImportResult>(
        { kind: "org", tenantId },
        "POST",
        "whatsapp/contacts/import",
        body,
      );
      onDone(result);
      onClose();
    } catch (caught) {
      setError(actionMessage(caught, "The import failed."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="wa-form">
      <p className="muted">
        Upload a CSV with phone numbers and optional display names.
      </p>
      {error && <Notice message={error} tone="error" scope="item" />}
      <Field label="CSV file">
        {(control) => (
          <input
            {...control}
            type="file"
            accept=".csv,text/csv"
            data-testid="wa-import-file"
            onChange={(event) => setFile(event.target.files?.[0] ?? null)}
          />
        )}
      </Field>
      <label className="wa-attest">
        <input
          type="checkbox"
          data-testid="wa-import-confirm"
          checked={confirmed}
          onChange={(event) => setConfirmed(event.target.checked)}
        />
        <span>{ATTESTATION}</span>
      </label>
      <p className="field-hint">
        The exact statement above is sent to the server and stored with the
        import evidence.
      </p>
      {busy && <Loading label="Importing…" />}
      <div className="action-row">
        <Button variant="quiet" onClick={onClose}>
          Cancel
        </Button>
        <Button
          data-testid="wa-import-submit"
          onClick={submit}
          disabled={!file || !confirmed || busy}
        >
          {busy ? "Importing…" : "Import"}
        </Button>
      </div>
    </div>
  );
}
