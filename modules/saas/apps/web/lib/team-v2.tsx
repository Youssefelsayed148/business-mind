"use client";

/**
 * Team screen for identity v2 (Phase 4E): five roles, invitations that never reveal whether an
 * address has an account, role changes, deactivation and MFA reset. The API applies the team
 * rules (an Admin cannot touch Owners or Admins, the last Owner stays); this screen only offers
 * what the signed-in role may try and shows the API's plain message when it refuses.
 */

import { useCallback, useState, type FormEvent } from "react";

import * as api from "./api";
import type { OrgRoleName, TeamMember } from "./api";
import { invitableRoles, inviteUrl, roleLabel } from "./identity";
import { orgRoleSatisfies, type OrgRole } from "./org-role";
import {
  Button,
  ConfirmAction,
  DataTable,
  Empty,
  Field,
  FormSection,
  Notice,
  PageHeader,
  StatusBadge,
} from "./ui";

import "@/app/team-screen.css";

const PURPOSE = "Invite teammates and manage their access to this workspace.";

export function TeamV2({
  tenantId,
  actor,
  initial,
  reload,
}: {
  tenantId: string;
  actor: OrgRole | null;
  initial: TeamMember[];
  reload: () => Promise<void>;
}) {
  const members = initial;
  const offered = invitableRoles(actor);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<OrgRoleName>(offered.at(-1) ?? "viewer");
  const [link, setLink] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [draft, setDraft] = useState<Record<string, OrgRoleName>>({});

  const run = useCallback(
    async (key: string, action: () => Promise<void>, done: string) => {
      setBusy(key);
      setError(null);
      setNotice(null);
      try {
        await action();
        setNotice(done);
        await reload();
      } catch (caught) {
        setError(
          caught instanceof Error ? caught.message : "That did not work.",
        );
      } finally {
        setBusy(null);
      }
    },
    [reload],
  );

  async function onInvite(event: FormEvent) {
    event.preventDefault();
    if (!email.trim()) {
      setError("Enter the email address to invite.");
      return;
    }
    setBusy("invite");
    setError(null);
    setNotice(null);
    setLink(null);
    try {
      const reply = await api.teamInvite(tenantId, email.trim(), role);
      setNotice(reply.message);
      setLink(inviteUrl(reply.link_path, window.location.origin));
      setEmail("");
    } catch (caught) {
      setError(
        caught instanceof Error
          ? caught.message
          : "Could not send the invitation.",
      );
    } finally {
      setBusy(null);
    }
  }

  const canManage = orgRoleSatisfies(actor, "admin");
  return (
    <main className="team-page">
      <PageHeader title="Team" purpose={PURPOSE} />
      {notice && <Notice message={notice} scope="item" />}
      {error && <Notice message={error} tone="error" scope="item" />}
      {canManage && offered.length > 0 && (
        <FormSection title="Invite someone" data-testid="invite-form">
          <form onSubmit={onInvite} noValidate>
            <Field label="Email">
              {(control) => (
                <input
                  {...control}
                  type="email"
                  autoComplete="off"
                  dir="ltr"
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                />
              )}
            </Field>
            <Field label="Role">
              {(control) => (
                <select
                  {...control}
                  value={role}
                  onChange={(event) =>
                    setRole(event.target.value as OrgRoleName)
                  }
                >
                  {offered.map((value) => (
                    <option key={value} value={value}>
                      {roleLabel(value)}
                    </option>
                  ))}
                </select>
              )}
            </Field>
            <Button type="submit" disabled={busy === "invite"}>
              Send invitation
            </Button>
          </form>
          {link && (
            <p data-testid="invite-link">
              Share this link with the invited person:{" "}
              <code dir="ltr">{link}</code>
            </p>
          )}
        </FormSection>
      )}
      {members.length === 0 ? (
        <Empty>No team members yet.</Empty>
      ) : (
        <DataTable
          caption="Team members"
          rows={members}
          rowKey={(row) => row.user_id}
          columns={[
            {
              key: "email",
              header: "Person",
              cell: (row) => <bdi dir="ltr">{row.email}</bdi>,
            },
            {
              key: "role",
              header: "Role",
              cell: (row) =>
                canManage && row.status === "active" ? (
                  <span className="team-role-edit">
                    <select
                      aria-label={`Role for ${row.email}`}
                      value={draft[row.user_id] ?? row.role}
                      onChange={(event) =>
                        setDraft({
                          ...draft,
                          [row.user_id]: event.target.value as OrgRoleName,
                        })
                      }
                    >
                      {(
                        [
                          "owner",
                          "admin",
                          "manager",
                          "agent",
                          "viewer",
                        ] as OrgRoleName[]
                      ).map((value) => (
                        <option key={value} value={value}>
                          {roleLabel(value)}
                        </option>
                      ))}
                    </select>
                    <Button
                      variant="quiet"
                      disabled={
                        busy === `role-${row.user_id}` ||
                        (draft[row.user_id] ?? row.role) === row.role
                      }
                      onClick={() =>
                        void run(
                          `role-${row.user_id}`,
                          async () => {
                            await api.teamChangeRole(
                              tenantId,
                              row.user_id,
                              draft[row.user_id] ?? row.role,
                            );
                            setDraft((current) => {
                              const next = { ...current };
                              delete next[row.user_id];
                              return next;
                            });
                          },
                          "Role updated.",
                        )
                      }
                    >
                      Save role
                    </Button>
                  </span>
                ) : (
                  roleLabel(row.role)
                ),
            },
            {
              key: "status",
              header: "Status",
              cell: (row) => (
                <StatusBadge
                  value={row.status}
                  tone={row.status === "active" ? "success" : "neutral"}
                >
                  {row.status === "active" ? "Active" : "Removed"}
                </StatusBadge>
              ),
            },
            {
              key: "scope",
              header: "Access",
              cell: (row) =>
                row.location_scope === "limited"
                  ? `${row.location_ids.length} location${row.location_ids.length === 1 ? "" : "s"}`
                  : "All locations",
            },
            {
              key: "actions",
              header: <span className="sr-only">Actions</span>,
              cell: (row) =>
                canManage && row.status === "active" ? (
                  <span className="team-actions">
                    <ConfirmAction
                      testId={`reset-mfa-${row.user_id}`}
                      title="Reset two-step verification?"
                      description={`${row.email} will have to set it up again. Their sessions end.`}
                      confirmLabel="Reset"
                      onConfirm={() =>
                        void run(
                          `mfa-${row.user_id}`,
                          () => api.teamResetMfa(tenantId, row.user_id),
                          "Two-step verification was reset.",
                        )
                      }
                    >
                      Reset 2-step
                    </ConfirmAction>
                    <ConfirmAction
                      testId={`remove-${row.user_id}`}
                      title="Remove this member?"
                      description={`${row.email} will lose access to this workspace.`}
                      confirmLabel="Remove"
                      onConfirm={() =>
                        void run(
                          `remove-${row.user_id}`,
                          () => api.teamDeactivate(tenantId, row.user_id),
                          "Member removed.",
                        )
                      }
                    >
                      Remove
                    </ConfirmAction>
                  </span>
                ) : null,
            },
          ]}
        />
      )}
    </main>
  );
}
