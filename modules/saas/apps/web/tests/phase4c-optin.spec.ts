import { expect, test } from "@playwright/test";

const TOKEN = "eyJhbGciOiJIUzI1NiJ9.eyJhIjoxfQ.c2lnbmF0dXJl";
const CALL = `**/api/v1/many/public/whatsapp/opt-in/${TOKEN}`;

test.afterEach(async ({ page }) => {
  await page.unrouteAll({ behavior: "wait" });
});

test("a visitor opts in without a login and gets the WhatsApp link", async ({
  page,
}) => {
  let body: unknown = null;
  let sentCookies = "unset";
  await page.route(CALL, async (route) => {
    body = route.request().postDataJSON();
    sentCookies = (await route.request().allHeaders())["cookie"] ?? "";
    return route.fulfill({
      status: 202,
      json: {
        accepted: true,
        message: "Open WhatsApp.",
        click_to_chat_url: "https://wa.me/201001234567?text=JOIN",
      },
    });
  });
  await page.goto(`/opt-in/${TOKEN}`);
  await expect(
    page.getByRole("heading", { name: "Confirm WhatsApp messages" }),
  ).toBeVisible();
  await page.getByLabel("WhatsApp number").fill("+20 100 123-4567");
  await page.getByRole("button", { name: "Continue" }).click();
  const link = page.getByRole("link", { name: "Open WhatsApp and send" });
  await expect(link).toHaveAttribute(
    "href",
    "https://wa.me/201001234567?text=JOIN",
  );
  expect(body).toEqual({ phone: "+201001234567" });
  expect(sentCookies).toBe("");
});

test("a number without + is refused in the page, before any call", async ({
  page,
}) => {
  let calls = 0;
  await page.route(CALL, (route) => {
    calls += 1;
    return route.fulfill({ status: 202, json: {} });
  });
  await page.goto(`/opt-in/${TOKEN}`);
  await page.getByLabel("WhatsApp number").fill("01001234567");
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByText("starting with +")).toBeVisible();
  expect(calls).toBe(0);
});

for (const [status, text] of [
  [404, "not valid any more"],
  [429, "Too many requests"],
  [502, "not available"],
] as const) {
  test(`a ${status} answer is shown in plain words`, async ({ page }) => {
    await page.route(CALL, (route) =>
      route.fulfill({
        status,
        json: {
          error: {
            code: status === 502 ? "MANY_UNAVAILABLE" : "X",
            message: "The channel service is not available right now.",
          },
        },
      }),
    );
    await page.goto(`/opt-in/${TOKEN}`);
    await page.getByLabel("WhatsApp number").fill("+201001234567");
    await page.getByRole("button", { name: "Continue" }).click();
    await expect(page.getByRole("alert")).toContainText(text);
    await expect(page.getByRole("alert")).not.toContainText(String(status));
  });
}

test("a link that is not wa.me is never opened", async ({ page }) => {
  await page.route(CALL, (route) =>
    route.fulfill({
      status: 202,
      json: { accepted: true, click_to_chat_url: "https://evil.example/x" },
    }),
  );
  await page.goto(`/opt-in/${TOKEN}`);
  await page.getByLabel("WhatsApp number").fill("+201001234567");
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByTestId("optin-done")).toBeVisible();
  await expect(
    page.getByRole("link", { name: "Open WhatsApp and send" }),
  ).toHaveCount(0);
  await expect(
    page.getByText("could not be opened automatically"),
  ).toBeVisible();
});
