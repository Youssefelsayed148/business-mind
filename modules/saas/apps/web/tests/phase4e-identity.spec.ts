import { expect, test, type Page, type Route } from "@playwright/test";

import { registerAdmin } from "./e2e-helpers";

/**
 * Phase 4E identity screens. The e2e API runs with identity v2 off, so the v2 routes are
 * answered by Playwright; the sign-in and organization are real. "Flag off" cases rely on the
 * real API's 404s.
 */

const NOT_FOUND = { error: { code: "NOT_FOUND", message: "Not found." } };

type Recorded = { method: string; path: string; json: unknown };

async function mock(
  page: Page,
  handlers: Record<string, (route: Route, call: Recorded) => unknown>,
): Promise<Recorded[]> {
  const calls: Recorded[] = [];
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname.replace("/api/v1/", "");
    const key = `${request.method()} ${path}`;
    const handler = Object.entries(handlers).find(([pattern]) =>
      new RegExp(`^${pattern}$`).test(key),
    )?.[1];
    if (!handler) return route.fallback();
    let json: unknown = null;
    try {
      json = request.postDataJSON();
    } catch {
      json = null;
    }
    const call = { method: request.method(), path, json };
    calls.push(call);
    const reply = (await handler(route, call)) as
      { status?: number; json?: unknown } | undefined;
    return route.fulfill({
      status: reply?.status ?? 200,
      json: reply?.json ?? {},
    });
  });
  return calls;
}

const ME = {
  id: "u1",
  email: "ann@example.com",
  is_platform_staff: false,
  memberships: [],
};

test.afterEach(async ({ page }) => {
  await page.unrouteAll({ behavior: "wait" });
});

// --- sign in with a second step, and the reset link ------------------------------------------

test("sign-in asks for a code only when the API says so, and sends it", async ({
  page,
}) => {
  let attempt = 0;
  let signedIn = false;
  const calls = await mock(page, {
    "GET auth/config": () => ({
      json: { self_serve_signup: false, identity_v2: true },
    }),
    "POST auth/login": (_route, call) => {
      attempt += 1;
      const body = call.json as { mfa_code?: string };
      if (!body.mfa_code)
        return {
          status: 401,
          json: {
            error: { code: "MFA_REQUIRED", message: "A code is required." },
          },
        };
      if (body.mfa_code !== "123456")
        return {
          status: 401,
          json: {
            error: { code: "INVALID_MFA_CODE", message: "Not correct." },
          },
        };
      signedIn = true;
      return { json: ME };
    },
    "GET auth/me": () =>
      signedIn
        ? { json: ME }
        : {
            status: 401,
            json: { error: { code: "UNAUTHENTICATED", message: "No." } },
          },
  });
  await page.goto("/login");
  await expect(page.getByLabel("Verification code")).toHaveCount(0);
  await page.getByLabel("Email").fill("ann@example.com");
  await page.getByLabel("Password", { exact: true }).fill("Str0ngPass!");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByLabel("Verification code")).toBeVisible();

  await page.getByLabel("Verification code").fill("000000");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByText("That code is not correct")).toBeVisible();

  await page.getByLabel("Verification code").fill("123 456");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect.poll(() => attempt).toBe(3);
  const last = calls.filter((c) => c.path === "auth/login").at(-1);
  expect(last?.json).toEqual({
    email: "ann@example.com",
    password: "Str0ngPass!",
    mfa_code: "123456",
  });
});

test("the sign-in page links to reset only while identity v2 is on", async ({
  page,
}) => {
  await page.goto("/login");
  await expect(
    page.getByText("Forgot your password? Contact your administrator."),
  ).toBeVisible();
  await page.unrouteAll({ behavior: "wait" });
  await mock(page, {
    "GET auth/config": () => ({
      json: { self_serve_signup: false, identity_v2: true },
    }),
  });
  await page.goto("/login");
  await expect(
    page.getByRole("link", { name: "Forgot your password?" }),
  ).toHaveAttribute("href", "/forgot-password");
});

test("forgot password: the same answer is shown, and a missing feature is explained", async ({
  page,
}) => {
  const calls = await mock(page, {
    "POST auth/password-reset/request": () => ({
      status: 202,
      json: { message: "If an account exists, we sent a link." },
    }),
  });
  await page.goto("/forgot-password");
  await page.getByRole("button", { name: "Send reset link" }).click();
  await expect(page.locator(".field-error")).toHaveText(
    "Enter your email address.",
  );
  expect(calls).toHaveLength(0);
  await page.getByLabel("Email").fill("anyone@example.com");
  await page.getByRole("button", { name: "Send reset link" }).click();
  await expect(page.getByTestId("reset-requested")).toContainText(
    "If an account exists",
  );
  expect(calls[0].json).toEqual({ email: "anyone@example.com" });

  await page.unrouteAll({ behavior: "wait" });
  await page.goto("/forgot-password");
  await page.getByLabel("Email").fill("anyone@example.com");
  await page.getByRole("button", { name: "Send reset link" }).click();
  await expect(page.getByText("not available here")).toBeVisible();
});

test("reset password: needs a token, checks the two passwords, sends token and password", async ({
  page,
}) => {
  await page.goto("/reset-password");
  await expect(page.getByText("missing its reset token")).toBeVisible();

  const calls = await mock(page, {
    "POST auth/password-reset/confirm": () => ({ json: { ok: true } }),
  });
  await page.goto("/reset-password?token=abcdefghijklmnopqrstuvwxyz");
  await page.getByLabel("New password", { exact: true }).fill("NewStr0ngPass!");
  await page.getByLabel("Confirm new password").fill("Different1!");
  await page.getByRole("button", { name: "Change password" }).click();
  await expect(page.getByText("do not match")).toBeVisible();
  expect(calls).toHaveLength(0);
  await page.getByLabel("Confirm new password").fill("NewStr0ngPass!");
  await page.getByRole("button", { name: "Change password" }).click();
  await expect(page.getByTestId("reset-done")).toBeVisible();
  expect(calls[0].json).toEqual({
    token: "abcdefghijklmnopqrstuvwxyz",
    new_password: "NewStr0ngPass!",
  });
});

test("a link that is expired shows the API's plain message", async ({
  page,
}) => {
  await mock(page, {
    "POST auth/password-reset/confirm": () => ({
      status: 400,
      json: {
        error: { code: "INVALID_TOKEN", message: "This link has expired." },
      },
    }),
  });
  await page.goto("/reset-password?token=abcdefghijklmnopqrstuvwxyz");
  await page.getByLabel("New password", { exact: true }).fill("NewStr0ngPass!");
  await page.getByLabel("Confirm new password").fill("NewStr0ngPass!");
  await page.getByRole("button", { name: "Change password" }).click();
  await expect(page.getByText("This link has expired.")).toBeVisible();
});

// --- accepting an invitation without an account ------------------------------------------------

test("an invited person without an account creates one with a password", async ({
  page,
}) => {
  const calls = await mock(page, {
    "GET auth/config": () => ({
      json: { self_serve_signup: false, identity_v2: true },
    }),
    "POST invitations/accept-new": () => ({ json: ME }),
  });
  await page.goto("/accept-invite?token=abcdefghijklmnopqrstuvwxyz");
  const form = page.getByTestId("create-account");
  await expect(form).toBeVisible();
  await form.getByLabel("Password", { exact: true }).fill("NewStr0ngPass!");
  await form.getByLabel("Confirm password").fill("nope");
  await form.getByRole("button", { name: "Create account and join" }).click();
  await expect(page.getByText("do not match")).toBeVisible();
  expect(calls.filter((c) => c.path === "invitations/accept-new")).toHaveLength(
    0,
  );
  await form.getByLabel("Confirm password").fill("NewStr0ngPass!");
  await form.getByRole("button", { name: "Create account and join" }).click();
  await expect
    .poll(() => calls.filter((c) => c.path === "invitations/accept-new").length)
    .toBe(1);
  expect(calls.find((c) => c.path === "invitations/accept-new")?.json).toEqual({
    token: "abcdefghijklmnopqrstuvwxyz",
    password: "NewStr0ngPass!",
  });
});

test("with identity v2 off the invitation page offers no account form", async ({
  page,
}) => {
  await page.goto("/accept-invite?token=abcdefghijklmnopqrstuvwxyz");
  await expect(page.getByRole("link", { name: "Sign in" })).toBeVisible();
  await expect(page.getByTestId("create-account")).toHaveCount(0);
});

// --- Account: two-step verification and devices -----------------------------------------------

test("the account page shows no security panels while identity v2 is off", async ({
  page,
}) => {
  await registerAdmin(page, "P4E-off");
  await page.goto("/account");
  await expect(page.getByTestId("account-email")).toBeVisible();
  await expect(page.getByTestId("mfa-panel")).toHaveCount(0);
  await expect(page.getByTestId("sessions-panel")).toHaveCount(0);
});

test("two-step verification: set up, confirm, see recovery codes once", async ({
  page,
}) => {
  await registerAdmin(page, "P4E-mfa");
  let enrolled = false;
  const calls = await mock(page, {
    "GET auth/sessions": () => ({ status: 404, json: NOT_FOUND }),
    "GET auth/mfa": () => ({
      json: {
        enrolled,
        pending: false,
        recovery_codes_remaining: enrolled ? 10 : 0,
        required: true,
        available: true,
      },
    }),
    "POST auth/mfa/enroll": () => ({
      json: {
        secret: "JBSWY3DPEHPK3PXP",
        otpauth_uri: "otpauth://totp/Chatbot:ann?secret=JBSWY3DPEHPK3PXP",
      },
    }),
    "POST auth/mfa/confirm": () => {
      enrolled = true;
      return { json: { recovery_codes: ["aaaa-1111", "bbbb-2222"] } };
    },
  });
  await page.goto("/account");
  const panel = page.getByTestId("mfa-panel");
  await expect(panel).toContainText("needs two-step verification");
  await panel.getByTestId("mfa-start").click();
  await expect(panel).toContainText("JBSWY3DPEHPK3PXP");
  await panel.getByLabel("Code from your app").fill("12");
  await panel.getByRole("button", { name: "Turn on" }).click();
  await expect(panel.getByRole("alert")).toContainText(
    "Enter the 6-digit code",
  );
  expect(calls.filter((c) => c.path === "auth/mfa/confirm")).toHaveLength(0);
  await panel.getByLabel("Code from your app").fill("123 456");
  await panel.getByRole("button", { name: "Turn on" }).click();
  await expect(panel.getByTestId("mfa-recovery")).toContainText("aaaa-1111");
  expect(calls.find((c) => c.path === "auth/mfa/confirm")?.json).toEqual({
    code: "123456",
  });
  await panel.getByRole("button", { name: "I saved them" }).click();
  await expect(panel.getByTestId("mfa-recovery")).toHaveCount(0);
  await expect(panel.getByTestId("mfa-enrolled")).toContainText(
    "10 recovery codes",
  );
});

test("an unavailable second step is explained, not offered", async ({
  page,
}) => {
  await registerAdmin(page, "P4E-mfa-off");
  await mock(page, {
    "GET auth/sessions": () => ({ status: 404, json: NOT_FOUND }),
    "GET auth/mfa": () => ({
      json: {
        enrolled: false,
        pending: false,
        recovery_codes_remaining: 0,
        required: false,
        available: false,
      },
    }),
  });
  await page.goto("/account");
  await expect(page.getByTestId("mfa-panel")).toContainText(
    "not set up on this deployment",
  );
  await expect(page.getByTestId("mfa-start")).toHaveCount(0);
});

test("devices: the current one is marked and the others can be signed out", async ({
  page,
}) => {
  await registerAdmin(page, "P4E-sessions");
  let others = 2;
  const calls = await mock(page, {
    "GET auth/mfa": () => ({ status: 404, json: NOT_FOUND }),
    "GET auth/sessions": () => ({
      json: [
        {
          id: "s1",
          created_at: "2026-01-01T10:00:00Z",
          last_seen_at: "2026-01-02T10:00:00Z",
          user_agent: "Mozilla/5.0 (Windows NT 10.0) Chrome/120 Safari/537",
          current: true,
        },
        ...Array.from({ length: others }, (_, i) => ({
          id: `o${i}`,
          created_at: "2026-01-01T09:00:00Z",
          last_seen_at: null,
          user_agent: "Mozilla/5.0 (iPhone; CPU iPhone OS 17) Safari/604",
          current: false,
        })),
      ],
    }),
    "POST auth/sessions/revoke-all": () => {
      const revoked = others;
      others = 0;
      return { json: { revoked } };
    },
  });
  await page.goto("/account");
  const panel = page.getByTestId("sessions-panel");
  await expect(panel).toContainText("Chrome on Windows");
  await expect(panel).toContainText("This device");
  await expect(panel).toContainText("Safari on iOS");
  await panel.getByTestId("sessions-revoke").click();
  await page
    .getByRole("dialog", { name: "Sign out other devices?" })
    .getByRole("button", { name: "Sign out others" })
    .click();
  await expect(panel).toContainText("2 other sessions were signed out.");
  expect(
    calls.find((c) => c.path === "auth/sessions/revoke-all")?.json,
  ).toEqual({
    keep_current: true,
  });
  await expect(panel.getByTestId("sessions-revoke")).toBeDisabled();
});

// --- Team (identity v2) ---------------------------------------------------------------------

function member(id: string, email: string, role: string, status = "active") {
  return {
    user_id: id,
    email,
    role,
    status,
    location_scope: "all",
    location_ids: [],
    joined_at: "2026-01-01T00:00:00Z",
  };
}

async function openTeam(page: Page, role: "owner" | "admin") {
  const { tenantId } = await registerAdmin(page, `P4E-team-${role}`);
  let rows = [
    member("m1", "owner@example.com", "owner"),
    member("m2", "agent@example.com", "agent"),
  ];
  const calls = await mock(page, {
    [`GET tenants/${tenantId}/summary`]: () => ({
      json: {
        organization_id: tenantId,
        organization_name: "Org",
        role,
        role_cap: null,
        via_agency: false,
      },
    }),
    [`GET tenants/${tenantId}/team/members`]: () => ({ json: rows }),
    [`POST tenants/${tenantId}/team/invitations`]: () => ({
      status: 202,
      json: {
        message: "If the address can join, an invitation was sent.",
        link_path: "/accept-invite?token=abcdefghijklmnopqrstuvwxyz",
      },
    }),
    [`PATCH tenants/${tenantId}/team/members/m2`]: (_r, call) => {
      rows = rows.map((r) =>
        r.user_id === "m2"
          ? { ...r, role: (call.json as { role: string }).role }
          : r,
      );
      return { json: rows[1] };
    },
    [`DELETE tenants/${tenantId}/team/members/m2`]: () => {
      rows = rows.map((r) =>
        r.user_id === "m2" ? { ...r, status: "deactivated" } : r,
      );
      return { status: 204 };
    },
    [`POST tenants/${tenantId}/team/members/m2/mfa-reset`]: () => ({
      status: 204,
    }),
  });
  await page.goto(`/app/${tenantId}/settings/members`);
  return { tenantId, calls };
}

test("team (owner): roles to invite, invitation link, role change", async ({
  page,
}) => {
  const { tenantId, calls } = await openTeam(page, "owner");
  const form = page.getByTestId("invite-form");
  await expect(form.getByLabel("Role").locator("option")).toHaveText([
    "Admin",
    "Manager",
    "Agent",
    "Viewer",
  ]);
  await form.getByLabel("Email").fill("new@example.com");
  await form.getByLabel("Role").selectOption("manager");
  await form.getByRole("button", { name: "Send invitation" }).click();
  await expect(page.getByText("an invitation was sent")).toBeVisible();
  await expect(page.getByTestId("invite-link")).toContainText(
    "/accept-invite?token=abcdefghijklmnopqrstuvwxyz",
  );
  expect(
    calls.find((c) => c.path === `tenants/${tenantId}/team/invitations`)?.json,
  ).toEqual({ email: "new@example.com", role: "manager" });

  await page.getByLabel("Role for agent@example.com").selectOption("manager");
  await page
    .getByRole("row", { name: /agent@example.com/ })
    .getByRole("button", { name: "Save role" })
    .click();
  await expect(page.getByText("Role updated.")).toBeVisible();
  expect(calls.find((c) => c.method === "PATCH")?.json).toEqual({
    role: "manager",
  });
});

test("team (admin): cannot offer Admin or Owner; removal and MFA reset ask first", async ({
  page,
}) => {
  const { tenantId, calls } = await openTeam(page, "admin");
  const form = page.getByTestId("invite-form");
  await expect(form.getByLabel("Role").locator("option")).toHaveText([
    "Manager",
    "Agent",
    "Viewer",
  ]);

  await page.getByTestId("reset-mfa-m2").click();
  expect(calls.filter((c) => c.path.endsWith("mfa-reset"))).toHaveLength(0);
  await page
    .getByRole("dialog", { name: "Reset two-step verification?" })
    .getByRole("button", { name: "Reset" })
    .click();
  await expect(
    page.getByText("Two-step verification was reset."),
  ).toBeVisible();

  await page.getByTestId("remove-m2").click();
  expect(calls.filter((c) => c.method === "DELETE")).toHaveLength(0);
  await page
    .getByRole("dialog", { name: "Remove this member?" })
    .getByRole("button", { name: "Remove" })
    .click();
  await expect(page.getByText("Member removed.")).toBeVisible();
  expect(
    calls.some((c) => c.path === `tenants/${tenantId}/team/members/m2`),
  ).toBe(true);
  await expect(
    page.getByRole("row", { name: /agent@example.com/ }),
  ).toContainText("Removed");
});

test("team: the API's refusal is shown in plain words and nothing changes", async ({
  page,
}) => {
  const { tenantId } = await openTeam(page, "admin");
  await page.route(`**/api/v1/tenants/${tenantId}/team/members/m2`, (route) =>
    route.request().method() === "PATCH"
      ? route.fulfill({
          status: 403,
          json: {
            error: {
              code: "FORBIDDEN",
              message: "Only an Owner can change an Admin.",
            },
          },
        })
      : route.fallback(),
  );
  await page.getByLabel("Role for agent@example.com").selectOption("admin");
  await page
    .getByRole("row", { name: /agent@example.com/ })
    .getByRole("button", { name: "Save role" })
    .click();
  await expect(
    page.getByText("Only an Owner can change an Admin."),
  ).toBeVisible();
});

test("team: with identity v2 off the earlier screen is shown", async ({
  page,
}) => {
  const { tenantId } = await registerAdmin(page, "P4E-team-off");
  await page.goto(`/app/${tenantId}/settings/members`);
  await expect(
    page.getByRole("heading", { name: "Team", exact: true }),
  ).toBeVisible();
  await expect(page.getByTestId("invite-form")).toHaveCount(0);
});
