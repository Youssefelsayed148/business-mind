"use client";

import { useMemo, useState } from "react";

import { manyRequest } from "@/lib/many";
import { PageState } from "@/lib/page-state";
import { useManyData } from "@/lib/use-many";
import {
  Button,
  Card,
  ConfirmAction,
  Dialog,
  Field,
  Notice,
  PageHeader,
  StatusBadge,
} from "@/lib/ui";
import {
  exampleValues,
  formatDate,
  normalizeTemplateName,
  placeholderIndexes,
  renderPreview,
  statusLabel,
  statusTone,
  templateIndexes,
  type WhatsappContact,
  type WhatsappTemplate,
} from "@/lib/whatsapp-types";

import { actionMessage, useWhatsapp } from "../whatsapp-shell";

import "@/app/whatsapp-screen.css";

export default function WhatsappTemplatesPage() {
  const { tenantId, account, notify } = useWhatsapp();
  const [editing, setEditing] = useState<WhatsappTemplate | "new" | null>(null);
  const [testing, setTesting] = useState<WhatsappTemplate | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const { data, status, reload } = useManyData<WhatsappTemplate[]>(
    () =>
      manyRequest(
        { kind: "org", tenantId },
        "GET",
        `whatsapp/templates?account_id=${account.id}`,
      ),
    account.id,
    {
      isEmpty: (rows) => rows.length === 0,
      emptyMessage:
        "No templates yet. Create a draft or sync templates already present in Meta.",
    },
  );

  async function run(
    path: string,
    method: "POST" | "DELETE",
    done: string,
  ): Promise<void> {
    setBusy(true);
    setActionError(null);
    try {
      await manyRequest({ kind: "org", tenantId }, method, path);
      notify(done);
      reload();
    } catch (caught) {
      setActionError(actionMessage(caught, "The action could not be done."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader
        title="WhatsApp templates"
        purpose="Draft message templates, preview variables, submit them to Meta, and record the App Review test-send flow."
        actions={
          <>
            <Button
              variant="quiet"
              data-testid="wa-sync"
              disabled={busy}
              onClick={() =>
                run(
                  `whatsapp/accounts/${account.id}/templates/sync`,
                  "POST",
                  "Template statuses synced.",
                )
              }
            >
              Sync Meta
            </Button>
            <Button
              data-testid="wa-template-new"
              onClick={() => setEditing("new")}
            >
              New template
            </Button>
          </>
        }
      />
      {actionError && (
        <Notice message={actionError} tone="error" scope="item" />
      )}
      <PageState status={status} homeHref={`/app/${tenantId}`}>
        {data && (
          <div className="wa-grid" data-testid="wa-templates">
            {data.map((template) => (
              <Card
                key={template.id}
                data-testid={`wa-template-${template.name}`}
                title={<span dir="auto">{template.name}</span>}
                actions={
                  <StatusBadge
                    value={template.status}
                    tone={statusTone(template.status)}
                  >
                    {statusLabel(template.status)}
                  </StatusBadge>
                }
              >
                <p className="muted wa-small">
                  <bdi dir="ltr">{template.language}</bdi> ·{" "}
                  {statusLabel(template.category)}
                </p>
                {template.rejection_reason && (
                  <p className="wa-reject">
                    <strong>Rejection reason:</strong>{" "}
                    <span dir="auto">{template.rejection_reason}</span>
                  </p>
                )}
                <div dir="auto" className="wa-body">
                  {template.components
                    .map((c) => c.text)
                    .filter(Boolean)
                    .join("\n") || "No text component"}
                </div>
                <p className="muted wa-small">
                  Last synced: {formatDate(template.last_synced_at)}
                </p>
                <div className="action-row">
                  {["draft", "rejected"].includes(template.status) && (
                    <>
                      <Button
                        variant="quiet"
                        data-testid="wa-template-edit"
                        onClick={() => setEditing(template)}
                      >
                        Edit
                      </Button>
                      <Button
                        data-testid="wa-template-submit"
                        disabled={busy}
                        onClick={() =>
                          run(
                            `whatsapp/templates/${template.id}/submit`,
                            "POST",
                            "Template submitted to Meta.",
                          )
                        }
                      >
                        Submit to Meta
                      </Button>
                      <ConfirmAction
                        testId="wa-template-delete"
                        title="Delete this template?"
                        description={`"${template.name}" is removed. This cannot be undone.`}
                        confirmLabel="Delete"
                        disabled={busy}
                        onConfirm={() =>
                          run(
                            `whatsapp/templates/${template.id}`,
                            "DELETE",
                            "Template deleted.",
                          )
                        }
                      >
                        Delete
                      </ConfirmAction>
                    </>
                  )}
                  {template.status === "approved" && (
                    <Button
                      variant="quiet"
                      data-testid="wa-template-test"
                      onClick={() => setTesting(template)}
                    >
                      Send test to my own number
                    </Button>
                  )}
                </div>
              </Card>
            ))}
          </div>
        )}
      </PageState>
      <Dialog
        open={editing !== null}
        onClose={() => setEditing(null)}
        title={
          editing && editing !== "new" ? "Edit template" : "Create template"
        }
        className="wa-dialog wa-dialog-wide"
        data-testid="wa-template-dialog"
      >
        {editing && (
          <TemplateEditor
            template={editing === "new" ? undefined : editing}
            onClose={() => setEditing(null)}
            onSaved={() => {
              notify("Template draft saved.");
              reload();
            }}
          />
        )}
      </Dialog>
      <Dialog
        open={testing !== null}
        onClose={() => setTesting(null)}
        title="Send test to my own number"
        className="wa-dialog"
        data-testid="wa-test-dialog"
      >
        {testing && (
          <TestSend
            template={testing}
            onClose={() => setTesting(null)}
            notify={notify}
          />
        )}
      </Dialog>
    </>
  );
}

function TemplateEditor({
  template,
  onClose,
  onSaved,
}: {
  template?: WhatsappTemplate;
  onClose: () => void;
  onSaved: () => void;
}) {
  const { tenantId, account } = useWhatsapp();
  const bodyComponent = template?.components.find(
    (c) => c.type.toLowerCase() === "body",
  );
  const [name, setName] = useState(template?.name || "");
  const [language, setLanguage] = useState(template?.language || "en_US");
  const [category, setCategory] = useState(template?.category || "marketing");
  const [body, setBody] = useState(bodyComponent?.text || "");
  const [examples, setExamples] = useState<Record<number, string>>(() =>
    exampleValues(bodyComponent, placeholderIndexes(bodyComponent?.text || "")),
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
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
      if (template) {
        await manyRequest(
          { kind: "org", tenantId },
          "PATCH",
          `whatsapp/templates/${template.id}`,
          { name, language, category, components },
        );
      } else {
        await manyRequest(
          { kind: "org", tenantId },
          "POST",
          "whatsapp/templates",
          {
            account_id: account.id,
            name,
            language,
            category,
            components,
          },
        );
      }
      onSaved();
      onClose();
    } catch (caught) {
      setError(actionMessage(caught, "Could not save the template."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="wa-editor">
      <div className="wa-form">
        <p className="muted">
          Use numbered placeholders such as {"{{1}}"}, then supply an example
          for every number.
        </p>
        {error && <Notice message={error} tone="error" scope="item" />}
        <Field label="Template name" required>
          {(control) => (
            <input
              {...control}
              dir="ltr"
              data-testid="wa-template-name"
              value={name}
              placeholder="seasonal_offer"
              onChange={(event) =>
                setName(normalizeTemplateName(event.target.value))
              }
            />
          )}
        </Field>
        <div className="wa-two">
          <Field label="Language">
            {(control) => (
              <input
                {...control}
                dir="ltr"
                value={language}
                onChange={(event) => setLanguage(event.target.value)}
              />
            )}
          </Field>
          <Field label="Category">
            {(control) => (
              <select
                {...control}
                value={category}
                onChange={(event) => setCategory(event.target.value)}
              >
                <option value="marketing">Marketing</option>
                <option value="utility">Utility</option>
                <option value="authentication">Authentication</option>
              </select>
            )}
          </Field>
        </div>
        <Field label="Message body" required>
          {(control) => (
            <textarea
              {...control}
              dir="auto"
              rows={6}
              data-testid="wa-template-body"
              value={body}
              placeholder="Hello {{1}}, your offer is ready."
              onChange={(event) => setBody(event.target.value)}
            />
          )}
        </Field>
        {indexes.map((i) => (
          <Field key={i} label={`Example for {{${i}}}`}>
            {(control) => (
              <input
                {...control}
                dir="auto"
                data-testid={`wa-example-${i}`}
                value={examples[i] || ""}
                onChange={(event) =>
                  setExamples((old) => ({ ...old, [i]: event.target.value }))
                }
              />
            )}
          </Field>
        ))}
      </div>
      <div>
        <p className="wa-preview-title">Live preview</p>
        <div className="wa-phone">
          <div dir="auto" className="wa-bubble" data-testid="wa-preview">
            {renderPreview(body, examples) ||
              "Your message preview appears here."}
          </div>
        </div>
      </div>
      <div className="action-row wa-editor-actions">
        <Button variant="quiet" onClick={onClose}>
          Cancel
        </Button>
        <Button
          data-testid="wa-template-save"
          onClick={save}
          disabled={
            busy || !name || !body || indexes.some((i) => !examples[i]?.trim())
          }
        >
          {busy ? "Saving…" : "Save draft"}
        </Button>
      </div>
    </div>
  );
}

function TestSend({
  template,
  onClose,
  notify,
}: {
  template: WhatsappTemplate;
  onClose: () => void;
  notify: (message: string, tone?: "info" | "error") => void;
}) {
  const { tenantId, account, outreachDisabled } = useWhatsapp();
  const { data, status, reload } = useManyData<{ items: WhatsappContact[] }>(
    () =>
      manyRequest(
        { kind: "org", tenantId },
        "GET",
        `whatsapp/contacts?account_id=${account.id}&consent=opted_in`,
      ),
    account.id,
  );
  const indexes = useMemo(() => templateIndexes(template), [template]);
  const [picked, setPicked] = useState("");
  const [values, setValues] = useState<Record<number, string>>({});
  const [proof, setProof] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const contacts = data?.items ?? [];
  const contactId = picked || contacts[0]?.id || "";

  async function grant() {
    setBusy(true);
    setError(null);
    try {
      await manyRequest(
        { kind: "org", tenantId },
        "POST",
        `whatsapp/contacts/${contactId}/grant`,
        { proof: proof.trim() },
      );
      notify(
        "Manual permission recorded; this number can now receive the test.",
      );
      reload();
    } catch (caught) {
      setError(actionMessage(caught, "Could not record the permission."));
    } finally {
      setBusy(false);
    }
  }

  async function send() {
    setBusy(true);
    setError(null);
    try {
      const result = await manyRequest<{ accepted: boolean }>(
        { kind: "org", tenantId },
        "POST",
        `whatsapp/templates/${template.id}/test-send`,
        {
          contact_id: contactId,
          variables: Object.fromEntries(
            indexes.map((i) => [String(i), values[i]]),
          ),
        },
      );
      if (result.accepted) {
        notify("Test message accepted.");
        onClose();
      } else {
        setError("The test send was refused.");
      }
    } catch (caught) {
      setError(actionMessage(caught, "The test send failed."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <PageState status={status} homeHref={`/app/${tenantId}`}>
      <div className="wa-form">
        <p className="muted">
          For Meta App Review, first select your number and record a manual
          grant with proof. The server only sends tests to manually opted-in
          contacts.
        </p>
        {error && <Notice message={error} tone="error" scope="item" />}
        {outreachDisabled && (
          <Notice
            message="Test sending is unavailable while outreach is globally disabled."
            tone="error"
            scope="item"
          />
        )}
        <Field label="My opted-in number">
          {(control) => (
            <select
              {...control}
              data-testid="wa-test-contact"
              value={contactId}
              onChange={(event) => setPicked(event.target.value)}
            >
              {contacts.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.display_name || c.wa_id} · {c.wa_id}
                </option>
              ))}
            </select>
          )}
        </Field>
        {contacts.length === 0 && (
          <p className="muted">
            No opted-in contacts found. Import or receive the contact first,
            then grant permission on Contacts.
          </p>
        )}
        <Field label="Manual grant proof note">
          {(control) => (
            <textarea
              {...control}
              dir="auto"
              rows={2}
              value={proof}
              placeholder="I control this number and consent to this App Review test."
              onChange={(event) => setProof(event.target.value)}
            />
          )}
        </Field>
        <div className="action-row">
          <Button
            variant="quiet"
            data-testid="wa-test-grant"
            onClick={grant}
            disabled={!contactId || !proof.trim() || busy}
          >
            Record manual grant first
          </Button>
        </div>
        {indexes.map((i) => (
          <Field key={i} label={`Value for {{${i}}}`}>
            {(control) => (
              <input
                {...control}
                dir="auto"
                data-testid={`wa-test-value-${i}`}
                value={values[i] || ""}
                onChange={(event) =>
                  setValues((old) => ({ ...old, [i]: event.target.value }))
                }
              />
            )}
          </Field>
        ))}
        <div className="action-row">
          <Button variant="quiet" onClick={onClose}>
            Cancel
          </Button>
          <Button
            data-testid="wa-test-send"
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
    </PageState>
  );
}
