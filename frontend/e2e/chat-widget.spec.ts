import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { owner } from "../test-support/batch3-fixtures";
import { conversation, message } from "../test-support/batch4-fixtures";

test("chat persists across workspace navigation, minimizes, retries safely and deletes with confirmation", async ({
  page,
}) => {
  let created = 0,
    sent = false,
    deleted = false;
  const keys: string[] = [],
    unexpected: string[] = [];
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request(),
      path = new URL(request.url()).pathname.replace("/api/v1", ""),
      method = request.method();
    let body: unknown = {},
      status = 200;
    if (path === "/auth/refresh")
      body = {
        access_token: "synthetic",
        token_type: "bearer",
        expires_at: "2099-01-01T00:00:00Z",
      };
    else if (path === "/auth/me") body = owner;
    else if (path === "/assistant/conversations") {
      if (method === "POST") {
        created++;
        body = conversation;
        status = 201;
      } else body = { items: created && !deleted ? [conversation] : [] };
    } else if (path === `/assistant/conversations/${conversation.id}`) {
      if (method === "DELETE") {
        deleted = true;
        status = 204;
      } else
        body = {
          ...conversation,
          turn_count: sent ? 1 : 0,
          messages: sent ? [message] : [],
        };
    } else if (path.endsWith("/messages")) {
      keys.push(request.headers()["idempotency-key"]);
      if (keys.length === 1) {
        status = 503;
        body = { answer: "UNVERIFIED" };
      } else {
        sent = true;
        body = message;
        status = 201;
      }
    } else if (path === "/preferences")
      body = {
        display_name: "Synthetic",
        timezone: "UTC",
        default_currency: "INR",
      };
    else if (path === "/notifications/preferences")
      body = { in_app_enabled: true };
    else if (path === "/notifications") body = { items: [], has_more: false };
    else {
      unexpected.push(`${method} ${path}`);
      status = 500;
    }
    await route.fulfill({
      status,
      contentType: "application/json",
      body: status === 204 ? undefined : JSON.stringify(body),
    });
  });
  await page.goto("/app/reports");
  await page.getByRole("button", { name: "Ask FALCON" }).click();
  const chat = page.getByRole("dialog", { name: "Assistant", exact: true });
  await expect(chat).toBeVisible();
  await expect(page).toHaveURL(/\/app\/reports$/);
  await chat.getByRole("button", { name: "New conversation" }).click();
  await chat.getByLabel("Your question").fill("Explain my forecast");
  await chat.getByRole("button", { name: "Send question" }).click();
  await expect(chat.getByText(/No unverified answer is shown/)).toBeVisible();
  await expect(chat.getByText("UNVERIFIED", { exact: true })).toHaveCount(0);
  await chat.getByRole("button", { name: "Send question" }).click();
  await expect(chat.getByText(message.answer.answer)).toBeVisible();
  expect(keys).toHaveLength(2);
  expect(keys[0]).toBe(keys[1]);
  await chat.getByText("View evidence and reliability").click();
  await expect(
    chat.getByText("Savings forecast", { exact: true }),
  ).toBeVisible();
  await chat.getByText("View evidence and reliability").click();
  await chat.getByLabel("Your question").fill("How can I improve my savings?");
  await page.getByRole("link", { name: "Settings", exact: true }).click();
  await expect(page).toHaveURL(/\/app\/settings$/);
  await expect(chat.getByLabel("Your question")).toHaveValue(
    "How can I improve my savings?",
  );
  await chat.getByRole("button", { name: "Minimize chat" }).click();
  await expect(chat).toBeHidden();
  await page.getByRole("button", { name: "Ask FALCON" }).click();
  await expect(chat.getByText(message.answer.answer)).toBeVisible();
  expect(created).toBe(1);
  expect(
    (
      await new AxeBuilder({ page })
        .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
        .analyze()
    ).violations,
  ).toEqual([]);
  await page.screenshot({ path: "test-results/chat-desktop.png" });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(
    chat.getByRole("button", { name: "Send question" }),
  ).toBeInViewport();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({ path: "test-results/chat-mobile.png" });
  await chat.getByRole("button", { name: "Delete conversation" }).click();
  const confirm = page.getByRole("dialog", { name: "Delete conversation?" });
  await confirm.getByRole("button", { name: "Cancel" }).click();
  expect(deleted).toBe(false);
  await chat.getByRole("button", { name: "Delete conversation" }).click();
  await confirm.getByRole("button", { name: "Confirm", exact: true }).click();
  await expect(chat.getByLabel("Your question")).toHaveCount(0);
  expect(deleted).toBe(true);
  await chat.press("Escape");
  await expect(chat).toBeHidden();
  await expect(page.getByRole("button", { name: "Ask FALCON" })).toBeFocused();
  expect(unexpected).toEqual([]);
});
