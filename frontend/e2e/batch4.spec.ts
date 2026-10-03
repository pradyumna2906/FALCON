import { test, expect } from "@playwright/test";
import { owner, plan } from "../test-support/batch3-fixtures";
import {
  conversation,
  message,
  simulation,
  notification,
} from "../test-support/batch4-fixtures";

test("scenario selection, verified chat retry, report download and notification lifecycle", async ({
  page,
}) => {
  let created = false,
    selected: string | null = null,
    sent = false,
    dismissed = false;
  const keys: string[] = [],
    unexpected: string[] = [];
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request(),
      url = new URL(request.url());
    const path = url.pathname.replace("/api/v1", ""),
      method = request.method();
    const reply = (body: unknown, status = 200) =>
      route.fulfill({
        status,
        contentType: "application/json",
        body: status === 204 ? undefined : JSON.stringify(body),
      });
    if (path === "/auth/refresh")
      return reply({
        access_token: "synthetic",
        token_type: "bearer",
        expires_at: "2099-01-01T00:00:00Z",
      });
    if (path === "/auth/me") return reply(owner);
    if (path === "/goal-plans") return reply({ items: [plan] });
    if (path === "/scenario-simulations") {
      if (method === "POST") {
        expect(request.postDataJSON().scenarios[0].income_change_percent).toBe(
          "-10.1234",
        );
        created = true;
        return reply(simulation, 201);
      }
      return reply({ items: created ? [simulation] : [] });
    }
    if (path === `/scenario-simulations/${simulation.id}`)
      return reply({ ...simulation, selected_scenario_id: selected });
    if (path.endsWith("/select")) {
      expect(request.postDataJSON().expected_selected_scenario_id).toBeNull();
      selected = simulation.definitions[0].id;
      return reply({ ...simulation, selected_scenario_id: selected });
    }
    if (path === "/assistant/conversations")
      return reply(
        method === "POST" ? conversation : { items: [conversation] },
        method === "POST" ? 201 : 200,
      );
    if (path === `/assistant/conversations/${conversation.id}`)
      return reply({
        ...conversation,
        turn_count: sent ? 1 : 0,
        messages: sent ? [message] : [],
      });
    if (path.endsWith("/messages")) {
      keys.push(request.headers()["idempotency-key"]);
      if (keys.length === 1) return reply({ answer: "UNVERIFIED" }, 503);
      sent = true;
      return reply(message, 201);
    }
    if (path === "/reports/monthly.pdf") {
      expect(url.searchParams.get("currency")).toBe("INR");
      return route.fulfill({
        status: 200,
        contentType: "application/pdf",
        body: "%PDF-synthetic",
      });
    }
    if (path === "/preferences")
      return reply({
        display_name: "Synthetic",
        timezone: "UTC",
        default_currency: "INR",
      });
    if (path === "/notifications/preferences")
      return reply({ in_app_enabled: true });
    if (path === "/notifications")
      return reply({ items: dismissed ? [] : [notification], has_more: false });
    if (path === `/notifications/${notification.id}` && method === "DELETE") {
      dismissed = true;
      return reply(null, 204);
    }
    unexpected.push(`${method} ${path}`);
    return reply({}, 500);
  });
  await page.goto("/app/scenarios");
  await page.getByLabel("Alternative name").fill("Lower income");
  await page.getByLabel("Income change (%)").fill("-10.1234");
  await page.getByRole("button", { name: "Add alternative" }).click();
  await page.getByLabel("Source plan").click();
  await page.getByRole("option").first().click();
  await page.getByRole("button", { name: "Generate scenarios" }).click();
  await expect(
    page.getByRole("table", { name: "Baseline outcomes" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Select Baseline" }).click();
  expect(selected).toBeNull();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Confirm" })
    .click();
  await expect(
    page.getByRole("heading", { name: "Baseline · Selected" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Assistant", exact: true }).click();
  await page.getByRole("button", { name: "New conversation" }).click();
  await page.getByLabel("Your question").fill("Explain my forecast");
  await page.getByRole("button", { name: "Send question" }).click();
  await expect(page.getByText(/No unverified answer is shown/)).toBeVisible();
  await expect(page.getByText("UNVERIFIED", { exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "Send question" }).click();
  await expect(page.getByText(message.answer.answer)).toBeVisible();
  expect(keys).toHaveLength(2);
  expect(keys[0]).toBe(keys[1]);
  await page
    .getByText("View evidence and reliability", { exact: true })
    .click();
  await expect(
    page.getByText("Savings forecast", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Minimize chat" }).click();
  await page.getByRole("link", { name: "Reports", exact: true }).click();
  await page.getByLabel("Report month").fill("2026-08");
  const downloading = page.waitForEvent("download");
  await page.getByRole("button", { name: "Download report" }).click();
  expect((await downloading).suggestedFilename()).toBe(
    "falcon-2026-08-INR.pdf",
  );
  await page.getByRole("link", { name: "Settings", exact: true }).click();
  await page.getByRole("tab", { name: "Notifications" }).click();
  await page.getByRole("button", { name: "Dismiss", exact: true }).click();
  expect(dismissed).toBe(false);
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Confirm" })
    .click();
  await expect(page.getByText("No records for this selection.")).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  expect(
    await page.evaluate(() => [localStorage.length, sessionStorage.length]),
  ).toEqual([0, 0]);
  expect(unexpected).toEqual([]);
});
