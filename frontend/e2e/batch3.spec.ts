import { test, expect } from "@playwright/test";
import {
  owner,
  goal,
  forecast,
  plan,
  progress,
  snapshot,
  cash,
  spending,
} from "../test-support/batch3-fixtures";
import type { Schema } from "../src/api/finance";

test("analytics to forecasts, goal contributions and explicit plan decisions", async ({
  page,
}) => {
  let generatedForecast = false,
    createdGoal = false,
    contributed = false,
    generatedPlan = false;
  let currentPlan: Schema<"GoalPlanRunResponse"> = structuredClone(plan);
  let previousPlan: Schema<"GoalPlanRunResponse"> | null = null;
  const unexpected: string[] = [];
  const writes: string[] = [];
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request(),
      url = new URL(request.url());
    const path = url.pathname.replace("/api/v1", ""),
      method = request.method();
    const reply = (body: unknown, status = 200) =>
      route.fulfill({
        status,
        contentType: "application/json",
        body: JSON.stringify(body),
      });
    if (method !== "GET") writes.push(`${method} ${path}`);
    if (path === "/auth/refresh")
      return reply({
        access_token: "synthetic-only",
        token_type: "bearer",
        expires_at: "2099-01-01T00:00:00Z",
      });
    if (path === "/auth/me") return reply(owner);
    if (path === "/analytics/cash-flow") return reply(cash);
    if (path === "/analytics/spending") return reply(spending);
    if (path === "/transactions") {
      expect(url.searchParams.get("account_id")).toBe(
        spending.accounts[0].account_id,
      );
      expect(url.searchParams.get("status")).toBe("posted");
      return reply({ items: [], next_cursor: null });
    }
    if (path === "/forecasts") {
      if (method === "POST") {
        expect(request.postDataJSON()).toEqual({
          target: "savings_amount",
          granularity: "month",
          currency: "INR",
          history_start: "2026-01-01",
          history_end: "2026-08-31",
          horizon: 2,
        });
        generatedForecast = true;
        return reply(forecast, 201);
      }
      return reply({ items: generatedForecast ? [forecast] : [] });
    }
    if (path === `/forecasts/${forecast.id}`) return reply(forecast);
    if (path === "/goals") {
      if (method === "POST") {
        expect(request.postDataJSON().target_amount).toBe("1000.1234");
        expect(request.postDataJSON()).not.toHaveProperty("user_id");
        createdGoal = true;
        return reply(goal, 201);
      }
      return reply({ items: createdGoal ? [goal] : [] });
    }
    if (path === `/goals/${goal.id}`) return reply(goal);
    if (path === `/goals/${goal.id}/progress`)
      return reply({
        ...progress,
        current_amount: contributed ? "25.1234" : "0.0000",
      });
    if (path === `/goals/${goal.id}/contributions`) {
      const contribution = {
        id: "ffffffff-ffff-4fff-ffff-ffffffffffff",
        amount: "25.1234",
        contribution_date: "2026-09-01",
        source_type: "manual",
        note: null,
      };
      if (method === "POST") {
        expect(request.postDataJSON().amount).toBe("25.1234");
        contributed = true;
        return reply(contribution, 201);
      }
      return reply({ items: contributed ? [contribution] : [] });
    }
    if (path === "/goal-planning/snapshot") return reply(snapshot);
    if (path === "/goal-plans") {
      if (method === "POST") {
        expect(request.postDataJSON()).toEqual({ currency: "INR" });
        generatedPlan = true;
        return reply(currentPlan, 201);
      }
      return reply({ items: generatedPlan ? [currentPlan] : [] });
    }
    if (path === `/goal-plans/${currentPlan.id}/approve`) {
      currentPlan = { ...currentPlan, status: "approved" };
      return reply(currentPlan);
    }
    if (path === `/goal-plans/${currentPlan.id}/regenerate`) {
      previousPlan = { ...currentPlan, status: "superseded", successor_plan_id: "abababab-abab-4bab-abab-abababababab" };
      currentPlan = {
        ...currentPlan,
        id: "abababab-abab-4bab-abab-abababababab",
        status: "generated",
        predecessor_plan_id: currentPlan.id,
      };
      return reply(currentPlan, 201);
    }
    if (path === `/goal-plans/${currentPlan.id}/reject`) {
      currentPlan = { ...currentPlan, status: "rejected" };
      return reply(currentPlan);
    }
    if (path === `/goal-plans/${currentPlan.id}`) return reply(currentPlan);
    if (previousPlan && path === `/goal-plans/${previousPlan.id}`) return reply(previousPlan);
    unexpected.push(`${method} ${path}`);
    return reply({}, 500);
  });
  await page.goto("/app/analytics");
  await expect(
    page.getByRole("table", { name: "Cash-flow comparison" }),
  ).toBeVisible();
  await page.getByRole("tab", { name: "Spending", exact: true }).click();
  await page.getByRole("button", { name: "Explore Synthetic bank" }).click();
  await expect(
    page.getByRole("table", { name: "Account expense details" }),
  ).toBeVisible();
  await page.getByRole("link", { name: "Forecasts", exact: true }).click();
  await page.getByLabel("History start").fill("2026-01-01");
  await page.getByLabel("History end").fill("2026-08-31");
  await page.getByLabel("Forecast periods").fill("2");
  await page
    .getByRole("button", { name: "Generate forecast", exact: true })
    .click();
  await expect(
    page.getByRole("table", { name: "Exact forecast values" }),
  ).toBeVisible();
  await expect(page.getByText(/Reliability: provisional/)).toBeVisible();
  await page.getByRole("link", { name: "Goals & Plans", exact: true }).click();
  await page.getByLabel("Goal name", { exact: false }).fill("Trip fund");
  await page.getByLabel("Target amount", { exact: false }).fill("1000.1234");
  await page.getByLabel("Target date", { exact: false }).fill("2027-06-01");
  await page.getByRole("button", { name: "Create goal", exact: true }).click();
  await expect(
    page.getByRole("table", { name: "Goal progress" }),
  ).toBeVisible();
  await page
    .getByRole("form", { name: "Record contribution" })
    .getByLabel("Contribution amount (INR)", { exact: false })
    .fill("25.1234");
  await page
    .getByRole("button", { name: "Add contribution", exact: true })
    .click();
  await expect(
    page.getByRole("table", { name: "Goal progress" }),
  ).toContainText("INR 25.1234");
  await page.getByRole("tab", { name: "Plans", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Planning evidence" }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Generate plan", exact: true })
    .click();
  expect(generatedPlan).toBe(false);
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Confirm", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Plan result" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Approve plan", exact: true }).click();
  expect(currentPlan.status).toBe("generated");
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Confirm", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Approve plan", exact: true }),
  ).toHaveCount(0);
  await page
    .getByRole("button", { name: "Regenerate plan", exact: true })
    .click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Confirm", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Reject plan", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Reject plan", exact: true }).click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Confirm", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Regenerate plan", exact: true }),
  ).toHaveCount(0);
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(
    page.getByRole("button", { name: "Open navigation" }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  expect(
    await page.evaluate(() => localStorage.length + sessionStorage.length),
  ).toBe(0);
  expect(writes.filter((w) => w.endsWith("/approve"))).toHaveLength(1);
  expect(unexpected).toEqual([]);
});
