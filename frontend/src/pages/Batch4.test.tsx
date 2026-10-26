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
import { ApiClient } from "../api/client";
import Assistant from "./Assistant";
import Scenarios, { scenarioInput } from "./Scenarios";
import Settings from "./Settings";
import Reports from "./Reports";
import { owner, plan } from "../../test-support/batch3-fixtures";
import {
  conversation,
  message,
  simulation,
  notification,
} from "../../test-support/batch4-fixtures";

vi.mock("../auth/session", () => ({
  useSession: () => ({
    status: "authenticated",
    user: owner,
    reloadUser: vi.fn(),
  }),
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
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  caches.forEach((c) => c.clear());
  caches.length = 0;
});

it("keeps hypothetical decimal inputs exact and does not include owner or trial controls", () => {
  const form = new FormData();
  Object.entries({
    name: "Reduced income",
    income_change_percent: "-10.1234",
    expense_change_percent: "0",
    start: "2026-10",
    end: "2026-11",
    one_time: "123.4567",
    retained: "0",
    goal_id: "goal",
    contribution: "99.9999",
  }).forEach(([key, val]) => form.set(key, val));
  const result = scenarioInput(form);
  expect(result.income_change_percent).toBe("-10.1234");
  expect(result.one_time_expenses).toEqual([
    { period_start: "2026-10-01", amount: "123.4567" },
  ]);
  expect(result.income_interruptions?.[0].retained_income_percent).toBe("0");
  expect(result.goal_adjustments?.[0].monthly_contribution_delta).toBe(
    "99.9999",
  );
  expect(result).not.toHaveProperty("user_id");
  expect(result).not.toHaveProperty("trial_count");
});

it("shows unknown probabilities separately from zero and confirms compare-and-set selection", async () => {
  const writes: unknown[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init: RequestInit) => {
      if (init.method === "POST") {
        writes.push(JSON.parse(String(init.body)));
        return response({
          ...simulation,
          selected_scenario_id: simulation.definitions[0].id,
        });
      }
      return response(
        url.includes("/goal-plans")
          ? { items: [plan] }
          : url.includes("?limit")
            ? { items: [simulation] }
            : simulation,
      );
    }),
  );
  show(<Scenarios />, `/?run=${simulation.id}`);
  const table = await screen.findByRole("table", { name: "Baseline outcomes" });
  expect(within(table).getByText("0.000000")).toBeInTheDocument();
  expect(within(table).getAllByText("Unavailable").length).toBeGreaterThan(0);
  await userEvent.click(
    screen.getByRole("button", { name: "Select Baseline" }),
  );
  expect(writes).toEqual([]);
  await userEvent.click(
    within(screen.getByRole("dialog")).getByRole("button", { name: "Confirm" }),
  );
  await waitFor(() =>
    expect(writes).toEqual([
      {
        scenario_definition_id: simulation.definitions[0].id,
        expected_selected_scenario_id: null,
      },
    ]),
  );
});

it("uses the same idempotency key after ambiguous failure and only renders a completed answer", async () => {
  const keys: string[] = [];
  let saved = false;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init: RequestInit) => {
      if (init.method === "POST") {
        keys.push(new Headers(init.headers).get("Idempotency-Key")!);
        if (keys.length === 1)
          return response({ answer: "UNVERIFIED SECRET" }, 503);
        saved = true;
        return response(message, 201);
      }
      return response(
        url.includes("/conversations?")
          ? { items: [conversation] }
          : {
              ...conversation,
              messages: saved ? [message] : [],
              turn_count: saved ? 1 : 0,
            },
      );
    }),
  );
  show(<Assistant />, `/?conversation=${conversation.id}`);
  await userEvent.type(
    await screen.findByLabelText(/Your question/),
    "Explain my forecast",
  );
  await userEvent.click(screen.getByRole("button", { name: "Send question" }));
  await screen.findByText(/No unverified answer is shown/);
  expect(screen.queryByText("UNVERIFIED SECRET")).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Send question" }));
  await screen.findByText(message.answer.answer);
  expect(keys).toHaveLength(2);
  expect(keys[0]).toBe(keys[1]);
  expect(screen.getByText("Savings forecast")).toBeInTheDocument();
  expect(
    screen.getByRole("table", { name: "Verified evidence citations" }),
  ).toBeInTheDocument();
});

it("requires confirmation before deleting a conversation", async () => {
  const writes: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init: RequestInit) => {
      if (init.method === "DELETE") {
        writes.push(url);
        return response(null, 204);
      }
      return response(
        url.includes("/conversations?")
          ? { items: [conversation] }
          : conversation,
      );
    }),
  );
  show(<Assistant />, `/?conversation=${conversation.id}`);
  await userEvent.click(
    await screen.findByRole("button", { name: "Delete conversation" }),
  );
  expect(writes).toEqual([]);
  await userEvent.click(
    within(screen.getByRole("dialog")).getByRole("button", { name: "Confirm" }),
  );
  await waitFor(() => expect(writes).toHaveLength(1));
});

it("downloads a report using the selected month and currency", async () => {
  const fetcher = vi.fn(
    async (url: string) =>
      new Response(`%PDF-synthetic ${url}`, {
        headers: { "Content-Type": "application/pdf" },
      }),
  );
  vi.stubGlobal("fetch", fetcher);
  const create = vi.fn(() => "blob:synthetic");
  URL.createObjectURL = create;
  URL.revokeObjectURL = vi.fn();
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
  show(<Reports />);
  fireEvent.change(screen.getByLabelText(/Report month/), {
    target: { value: "2026-08" },
  });
  await userEvent.click(
    screen.getByRole("button", { name: "Download report" }),
  );
  await waitFor(() => expect(create).toHaveBeenCalled());
  expect(fetcher.mock.calls[0][0]).toContain(
    "/reports/monthly.pdf?month=2026-08&currency=INR",
  );
});

it("discards a binary download that completes after sign-out", async () => {
  let finish!: (value: Blob) => void;
  const body = new Promise<Blob>((resolve) => {
    finish = resolve;
  });
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({ ok: true, status: 200, blob: () => body })),
  );
  const client = new ApiClient();
  const request = client.request("/privacy/export", {}, false, true);
  await Promise.resolve();
  client.clearSession();
  finish(new Blob(["private"]));
  await expect(request).rejects.toMatchObject({ status: 401 });
});

it("preserves the password exactly in a personal export and never sends a user ID", async () => {
  const calls: RequestInit[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init: RequestInit) => {
      expect(url).toContain('/api/v1/');
      calls.push(init);
      return response({});
    }),
  );
  URL.createObjectURL = vi.fn(() => "blob:synthetic");
  URL.revokeObjectURL = vi.fn();
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
  show(<Settings />);
  await userEvent.click(screen.getByRole("tab", { name: "Export & erasure" }));
  await userEvent.type(
    screen.getByLabelText(/Confirm password to export/),
    " untrimmed ",
  );
  await userEvent.click(
    screen.getByRole("button", { name: "Download personal data" }),
  );
  await waitFor(() =>
    expect(calls.some((call) => call.method === "POST")).toBe(true),
  );
  expect(
    JSON.parse(String(calls.find((call) => call.method === "POST")!.body)),
  ).toEqual({ password: " untrimmed " });
  expect(localStorage.length).toBe(0);
  expect(sessionStorage.length).toBe(0);
});

it("reads persisted notifications and confirms dismissal", async () => {
  const writes: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init: RequestInit) => {
      if (init.method === "DELETE") {
        writes.push(url);
        return response(null, 204);
      }
      return response(
        url.includes("/notifications?")
          ? { items: [notification], has_more: false }
          : { in_app_enabled: true },
      );
    }),
  );
  show(<Settings />);
  await userEvent.click(screen.getByRole("tab", { name: "Notifications" }));
  await userEvent.click(await screen.findByRole("button", { name: "Dismiss" }));
  expect(writes).toEqual([]);
  await userEvent.click(
    within(screen.getByRole("dialog")).getByRole("button", { name: "Confirm" }),
  );
  await waitFor(() => expect(writes[0]).toContain(notification.id));
});
