import type { ReactNode } from "react";
import { afterEach, expect, it, vi } from "vitest";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router";
import { createQueryClient } from "../api/query";
import Analytics from "./Analytics";
import Forecasts, { ForecastDetail } from "./Forecasts";
import Goals, { PlanDetail } from "./Goals";
import {
  owner,
  goal,
  forecast,
  plan,
  progress,
  cash,
  spending,
} from "../../test-support/batch3-fixtures";

vi.mock("../auth/session", () => ({
  useSession: () => ({ status: "authenticated", user: owner }),
}));
const response = (body: unknown, status = 200) =>
  new Response(status === 204 ? null : JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
const caches: ReturnType<typeof createQueryClient>[] = [];
function show(element: ReactNode, route = "/") {
  const cache = createQueryClient();
  caches.push(cache);
  return render(
    <QueryClientProvider client={cache}>
      <MemoryRouter initialEntries={[route]}>{element}</MemoryRouter>
    </QueryClientProvider>,
  );
}
afterEach(() => {
  vi.unstubAllGlobals();
  caches.forEach((c) => c.clear());
  caches.length = 0;
});

it("loads only the selected analytics section and drills down to the matching account and period", async () => {
  const fetcher = vi.fn(async (url: string) =>
    response(
      url.includes("cash-flow")
        ? cash
        : url.includes("/transactions?")
          ? { items: [], next_cursor: null }
          : spending,
    ),
  );
  vi.stubGlobal("fetch", fetcher);
  show(<Analytics />);
  await screen.findByRole("table", { name: "Cash-flow comparison" });
  expect(fetcher).toHaveBeenCalledTimes(1);
  expect(screen.getByText("INR 123.4567")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("tab", { name: "Spending" }));
  await userEvent.click(
    await screen.findByRole("button", { name: "Explore Synthetic bank" }),
  );
  await screen.findByRole("table", { name: "Account expense details" });
  const request = fetcher.mock.calls.find(([url]) =>
    url.includes("/transactions?"),
  )![0];
  expect(request).toContain("account_id=eeeeeeee-eeee-4eee-eeee-eeeeeeeeeeee");
  expect(request).toContain("date_from=2026-09-01");
  expect(request).toContain("date_to=2026-09-30");
  expect(request).toContain("status=posted");
  expect(request).toContain("transaction_type=expense");
});

it.each([
  "Cash flow",
  "Spending",
  "Recurring & subscriptions",
  "Leaks & anomalies",
  "Budgets & risk",
  "Health factors",
  "Insights",
])("shows a safe retry state for %s failures", async (section) => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => response({}, 503)),
  );
  show(<Analytics />);
  await userEvent.click(screen.getByRole("tab", { name: section }));
  await screen.findByRole("button", { name: "Retry loading" });
  expect(screen.queryByText("INR 0.0000")).not.toBeInTheDocument();
});

it("keeps exact forecast values and warns about provisional evidence", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => response(forecast)),
  );
  show(<ForecastDetail id={forecast.id} />);
  await screen.findByRole("table", { name: "Exact forecast values" });
  expect(screen.getByRole("img", { name: /80% and 95%/ })).toBeInTheDocument();
  expect(screen.getAllByText("500.1234")).toHaveLength(2);
  expect(screen.getByText(/Reliability: provisional/)).toBeInTheDocument();
});

it("does not replay a failed forecast generation or invent a result", async () => {
  const fetcher = vi.fn(async (_url: string, init?: RequestInit) =>
    response(
      init?.method === "POST" ? {} : { items: [] },
      init?.method === "POST" ? 422 : 200,
    ),
  );
  vi.stubGlobal("fetch", fetcher);
  show(<Forecasts />);
  fireEvent.change(screen.getByLabelText(/History start/), {
    target: { value: "2026-01-01" },
  });
  fireEvent.change(screen.getByLabelText(/History end/), {
    target: { value: "2026-08-31" },
  });
  await userEvent.click(
    screen.getByRole("button", { name: "Generate forecast" }),
  );
  await screen.findByText(/Check the entered values/);
  expect(
    fetcher.mock.calls.filter(([, init]) => init?.method === "POST"),
  ).toHaveLength(1);
  expect(
    screen.queryByRole("table", { name: "Exact forecast values" }),
  ).not.toBeInTheDocument();
});

it("creates goals with exact decimals and no client-controlled owner", async () => {
  const fetcher = vi.fn(async (url: string, init?: RequestInit) =>
    response(
      init?.method === "POST"
        ? goal
        : url.endsWith("/progress")
          ? progress
          : url.endsWith("/contributions")
            ? { items: [] }
            : url.includes("/goals?")
              ? { items: [] }
              : goal,
    ),
  );
  vi.stubGlobal("fetch", fetcher);
  show(<Goals />);
  const form = screen.getByRole("form", { name: "Create goal" });
  await userEvent.type(within(form).getByLabelText(/Goal name/), "Trip fund");
  await userEvent.type(
    within(form).getByLabelText(/Target amount/),
    "1000.1234",
  );
  fireEvent.change(within(form).getByLabelText(/Target date/), {
    target: { value: "2027-06-01" },
  });
  await userEvent.click(
    within(form).getByRole("button", { name: "Create goal" }),
  );
  await screen.findByRole("table", { name: "Goal progress" });
  const payload = JSON.parse(
    fetcher.mock.calls.find(([, init]) => init?.method === "POST")![1]!
      .body as string,
  );
  expect(payload.target_amount).toBe("1000.1234");
  expect(payload.currency).toBe("INR");
  expect(payload).not.toHaveProperty("user_id");
});

it("requires confirmation to approve a plan and invalidates its stored status", async () => {
  let approved = false;
  const fetcher = vi.fn(async (_url: string, init?: RequestInit) => {
    if (init?.method === "POST") approved = true;
    return response({ ...plan, status: approved ? "approved" : "generated" });
  });
  vi.stubGlobal("fetch", fetcher);
  show(<PlanDetail id={plan.id} onSelect={vi.fn()} />);
  await userEvent.click(
    await screen.findByRole("button", { name: "Approve plan" }),
  );
  expect(approved).toBe(false);
  expect(screen.getByRole("dialog")).toHaveTextContent("does not move money");
  await userEvent.click(
    within(screen.getByRole("dialog")).getByRole("button", { name: "Confirm" }),
  );
  await waitFor(() =>
    expect(
      screen.queryByRole("button", { name: "Approve plan" }),
    ).not.toBeInTheDocument(),
  );
  expect(approved).toBe(true);
  expect(
    fetcher.mock.calls.filter(([, init]) => init?.method === "POST"),
  ).toHaveLength(1);
});

it.each(["rejected", "superseded"])(
  "keeps %s plans read-only",
  async (status) => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => response({ ...plan, status })),
    );
    show(<PlanDetail id={plan.id} onSelect={vi.fn()} />);
    await screen.findByRole("heading", { name: "Plan result" });
    expect(
      screen.queryByRole("button", { name: "Approve plan" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Regenerate plan" }),
    ).not.toBeInTheDocument();
  },
);

it("does not offer approval for a blocked plan or present unknown probability as zero", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => response({ ...plan, strategy: "blocked" })),
  );
  show(<PlanDetail id={plan.id} onSelect={vi.fn()} />);
  const table = await screen.findByRole("table", { name: "Trip fund outcome" });
  expect(within(table).getAllByText("Unavailable").length).toBeGreaterThan(0);
  expect(
    screen.queryByRole("button", { name: "Approve plan" }),
  ).not.toBeInTheDocument();
});

it("requires confirmation before removing a goal contribution", async () => {
  let removed = false;
  const contribution = {
    id: "ffffffff-ffff-4fff-ffff-ffffffffffff",
    amount: "25.1234",
    source_type: "manual",
    contribution_date: "2026-09-01",
    note: null,
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === "DELETE") {
        removed = true;
        return response(null, 204);
      }
      return response(
        url.includes("/goals?")
          ? { items: [goal] }
          : url.endsWith("/progress")
            ? progress
            : url.endsWith("/contributions")
              ? { items: removed ? [] : [contribution] }
              : goal,
      );
    }),
  );
  show(<Goals />, `/?goal=${goal.id}`);
  await userEvent.click(
    await screen.findByRole("button", { name: "Remove contribution" }),
  );
  expect(removed).toBe(false);
  await userEvent.click(
    within(screen.getByRole("dialog")).getByRole("button", { name: "Confirm" }),
  );
  await waitFor(() => expect(removed).toBe(true));
});
