import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import {
  owner,
  goal,
  progress,
  forecast,
  context,
  cash,
  spending,
} from "../test-support/batch3-fixtures";

for (const width of [390, 1440]) {
  test(`landing page is accessible and responsive at ${width}px`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.route("**/api/v1/auth/refresh", (route) =>
      route.fulfill({ status: 401, body: "{}" }),
    );
    await page.goto("/");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(
      /Understand today/,
    );
    await expect(
      page.getByRole("link", { name: "Create your account", exact: true }),
    ).toHaveAttribute("href", "/register");
    expect(
      (
        await new AxeBuilder({ page })
          .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
          .analyze()
      ).violations,
    ).toEqual([]);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await page.screenshot({
      path: `test-results/redesign-landing-${width}.png`,
      fullPage: true,
    });
    await page.addStyleTag({ content: "html { font-size: 200%; }" });
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
  });
}

test("deep links survive sign-in, passwords can be revealed and email links populate tokens", async ({
  page,
}) => {
  await page.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname.replace("/api/v1", "");
    const body =
      path === "/auth/refresh"
        ? {}
        : path === "/auth/me"
          ? owner
          : path === "/auth/login"
            ? {
                access_token: "synthetic",
                token_type: "bearer",
                expires_at: "2099-01-01T00:00:00Z",
              }
            : { items: [] };
    await route.fulfill({
      status: path === "/auth/refresh" ? 401 : 200,
      contentType: "application/json",
      body: JSON.stringify(body),
    });
  });
  await page.goto("/app/assistant");
  await expect(
    page.getByRole("heading", { name: "Sign in", exact: true }),
  ).toBeVisible();
  const password = page.getByLabel(/^Password/);
  await password.fill("Synthetic-Password-2026!");
  await page
    .getByRole("button", { name: "Show password", exact: true })
    .click();
  await expect(password).toHaveAttribute("type", "text");
  await page
    .getByRole("button", { name: "Hide password", exact: true })
    .click();
  await expect(password).toHaveAttribute("type", "password");
  await page.getByLabel("Email", { exact: false }).fill(owner.email);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page).toHaveURL(/\/app\/assistant$/);
  await expect(
    page.getByRole("heading", { name: "Assistant", exact: true }),
  ).toBeVisible();
  await page.goto(`/reset-password?token=${"a".repeat(43)}`);
  await expect(
    page.getByLabel("Token from your email", { exact: false }),
  ).toHaveValue("a".repeat(43));
});

test("dashboard renders API evidence, keeps account currencies and validates filters without writes", async ({
  page,
}) => {
  const writes: string[] = [],
    unexpected: string[] = [];
  const metrics = {
    ...cash.metrics,
    gross_income: { value: "50000.1234" },
    total_expense: { value: "123.4567" },
    net_cash_flow: { value: "49876.6667" },
    savings_amount: { value: "49876.6667" },
  };
  const data = {
    context,
    metrics,
    series: [{ period_start: "2026-09-01", ...metrics, transaction_count: 1 }],
    spending: {
      ...spending,
      categories: [
        {
          category_id: "food",
          name: "Food",
          amount: { value: "123.4567" },
          share: { value: "1.000000" },
          transaction_count: 1,
        },
      ],
    },
  };
  await page.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname.replace("/api/v1", ""),
      method = route.request().method();
    if (method !== "GET" && path !== "/auth/refresh")
      writes.push(`${method} ${path}`);
    let body: unknown;
    if (path === "/auth/refresh")
      body = {
        access_token: "synthetic",
        token_type: "bearer",
        expires_at: "2099-01-01T00:00:00Z",
      };
    else if (path === "/auth/me") body = owner;
    else if (path === "/analytics/dashboard") body = data;
    else if (path === "/analytics/health-score")
      body = {
        score: 78,
        status: "available",
        explanation: "Synthetic health evidence.",
        factors: [],
      };
    else if (path === "/analytics/insights")
      body = { explanation: "Synthetic insights.", insights: [] };
    else if (path === "/goals") body = { items: [goal] };
    else if (path === `/goals/${goal.id}/progress`) body = progress;
    else if (path === "/forecasts") body = { items: [forecast] };
    else if (path === `/forecasts/${forecast.id}`) body = forecast;
    else if (path === "/accounts")
      body = {
        items: [{ id: "usd-account", name: "Dollar account", currency: "USD" }],
      };
    else if (path === "/transactions")
      body = {
        items: [
          {
            id: "t",
            account_id: "usd-account",
            transaction_date: "2026-09-01",
            description: "Synthetic dollar expense",
            merchant_name: null,
            transaction_type: "expense",
            status: "posted",
            amount: "20.1234",
          },
        ],
        next_cursor: null,
      };
    else {
      unexpected.push(path);
      body = {};
    }
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(body),
    });
  });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/app/overview");
  await expect(
    page.getByRole("img", { name: "Financial health score 78 out of 100" }),
  ).toBeVisible();
  await expect(
    page
      .getByRole("region", { name: "Expenses summary" })
      .getByText("INR 123.4567", { exact: true }),
  ).toBeVisible();
  await expect(page.getByText("USD 20.1234", { exact: true })).toBeVisible();
  await expect(
    page.getByRole("img", { name: /expected forecast with 80%/ }),
  ).toBeVisible();
  await expect(
    page.getByRole("link", { name: "Review health factors" }),
  ).toHaveAttribute("href", "/app/analytics?tab=health");
  expect(
    (
      await new AxeBuilder({ page })
        .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
        .analyze()
    ).violations,
  ).toEqual([]);
  await page.screenshot({
    path: "test-results/redesign-dashboard-desktop.png",
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: "test-results/redesign-dashboard-mobile.png",
    fullPage: true,
  });
  await page.getByText(/Change period/).click();
  await page.getByLabel("From", { exact: false }).fill("2026-10-02");
  await page.getByLabel(/^To/).fill("2026-10-01");
  await page.getByRole("button", { name: "Apply filters" }).click();
  await expect(page.getByRole("alert")).toHaveText(
    "From date must not be after To date.",
  );
  expect(writes).toEqual([]);
  expect(unexpected).toEqual([]);
});
