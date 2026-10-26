import { PageHeading } from "../components/PageHeading";
import { useState } from "react";
import {
  Alert,
  Button,
  Paper,
  Stack,
  Tab,
  Tabs,
  Typography,
} from "@mui/material";
import { Link, useSearchParams } from "react-router";
import { useSession } from "../auth/session";
import {
  useFinanceMutation,
  useResource,
  money,
  localDate,
  type Schema,
} from "../api/finance";
import {
  Form,
  amountField,
  currencyField,
  optional,
  value,
  type Field,
} from "../components/Forms";
import { ConfirmAction } from "../components/ConfirmAction";
import {
  DataTable,
  Reasons,
  Result,
  words,
} from "../components/FinancialResults";

function GoalForm({
  goal,
  onSaved,
}: {
  goal?: Schema<"GoalResponse">;
  onSaved: (id: string) => void;
}) {
  const { user } = useSession();
  const mutate = useFinanceMutation();
  const fields: Field[] = [
    {
      name: "name",
      label: "Goal name",
      required: true,
      maxLength: 120,
      value: goal?.name,
    },
    {
      name: "goal_type",
      label: "Goal type",
      required: true,
      value: goal?.goal_type || "travel",
      options: [
        "travel",
        "marriage",
        "education",
        "emergency_fund",
        "major_purchase",
        "other",
      ],
    },
    {
      ...amountField,
      name: "target_amount",
      label: "Target amount",
      value: goal?.target_amount,
    },
    {
      ...amountField,
      name: "starting_amount",
      label: "Starting amount",
      value: goal?.starting_amount || "0",
      help: "Savings already dedicated to this goal. Do not also record them as a contribution.",
    },
    {
      ...currencyField,
      value: goal?.currency || user?.default_currency || "INR",
    },
    {
      name: "target_date",
      label: "Target date",
      type: "date",
      required: true,
      value: goal?.target_date,
      min: localDate(user?.timezone),
    },
    {
      name: "priority",
      label: "Priority",
      required: true,
      value: goal?.priority || "medium",
      options: ["low", "medium", "high", "critical"],
    },
    {
      name: "description",
      label: "Goal description",
      maxLength: 500,
      value: goal?.description || "",
    },
  ];
  return (
    <Form
      title={goal ? "Edit goal" : "Create goal"}
      submit={goal ? "Save goal" : "Create goal"}
      fields={fields}
      onSubmit={async (data) => {
        const payload = {
          name: value(data, "name"),
          goal_type: value(data, "goal_type") as Schema<"GoalType">,
          target_amount: value(data, "target_amount"),
          starting_amount: value(data, "starting_amount"),
          currency: value(data, "currency").toUpperCase(),
          target_date: value(data, "target_date"),
          priority: value(data, "priority") as Schema<"GoalPriority">,
          description: optional(data, "description"),
        } satisfies Schema<"GoalCreateRequest">;
        const result = await mutate<Schema<"GoalResponse">>(
          goal ? `/goals/${goal.id}` : "/goals",
          goal ? "PATCH" : "POST",
          payload,
        );
        onSaved(result.id);
      }}
    />
  );
}

function GoalDetail({ id }: { id: string }) {
  const goal = useResource<Schema<"GoalResponse">>(
    `/goals/${encodeURIComponent(id)}`,
  );
  const progress = useResource<Schema<"GoalProgressResponse">>(
    `/goals/${encodeURIComponent(id)}/progress`,
  );
  const contributions = useResource<Schema<"ContributionListResponse">>(
    `/goals/${encodeURIComponent(id)}/contributions`,
  );
  const { user } = useSession();
  const mutate = useFinanceMutation();
  const [editing, setEditing] = useState(false);
  return (
    <Result query={goal}>
      {(g) => (
        <Stack spacing={3}>
          <Typography variant="h2">{g.name}</Typography>
          <Typography>
            {words(g.goal_type)} · {g.priority} priority · {g.status} · Target{" "}
            {money(g.target_amount, g.currency)} by {g.target_date}
          </Typography>
          <Result query={progress}>
            {(p) => (
              <>
                <DataTable
                  title="Goal progress"
                  headings={[
                    "Saved",
                    "Remaining",
                    "Funding",
                    "Monthly contribution needed",
                    "State",
                  ]}
                  rows={[
                    [
                      money(p.current_amount, p.currency),
                      money(p.remaining_amount, p.currency),
                      `${p.funding_percentage}%`,
                      money(p.required_monthly_contribution, p.currency),
                      words(p.funding_state),
                    ],
                  ]}
                />
                <Typography variant="body2">
                  Calculated {p.calculated_on}. Progress and required
                  contributions are calculated by the server.
                </Typography>
              </>
            )}
          </Result>
          {g.status === "active" && (
            <>
              <Stack direction="row" sx={{ flexWrap: "wrap" }}>
                <Button onClick={() => setEditing(!editing)}>
                  {editing ? "Close editor" : "Edit goal"}
                </Button>
                <ConfirmAction
                  label="Complete goal"
                  detail="Mark this goal completed? This changes its lifecycle and removes it from active planning."
                  action={() => mutate(`/goals/${g.id}/complete`, "POST")}
                />
                <ConfirmAction
                  label="Cancel goal"
                  detail="Cancel this goal? Its history is retained and it will no longer be included in active planning."
                  action={() => mutate(`/goals/${g.id}/cancel`, "POST")}
                />
              </Stack>
              {editing && (
                <GoalForm
                  key={g.updated_at}
                  goal={g}
                  onSaved={() => setEditing(false)}
                />
              )}
              <Alert severity="info">
                Contributions record savings dedicated to this goal; they do not
                move money. Transaction links must satisfy the server's
                currency, date and allocation checks.
              </Alert>
              <Form
                title="Record contribution"
                submit="Add contribution"
                fields={[
                  {
                    ...amountField,
                    label: `Contribution amount (${g.currency})`,
                  },
                  {
                    name: "contribution_date",
                    label: "Contribution date",
                    required: true,
                    type: "date",
                    value: localDate(user?.timezone),
                    max: localDate(user?.timezone),
                  },
                  { name: "note", label: "Contribution note", maxLength: 500 },
                ]}
                onSubmit={async (data) => {
                  await mutate(`/goals/${g.id}/contributions`, "POST", {
                    source_type: "manual",
                    amount: value(data, "amount"),
                    contribution_date: value(data, "contribution_date"),
                    note: optional(data, "note"),
                  } satisfies Schema<"ContributionCreateRequest">);
                }}
              />
              <Form
                title="Link transaction contribution"
                submit="Link contribution"
                fields={[
                  {
                    name: "transaction_id",
                    label: "Transaction ID",
                    required: true,
                    pattern:
                      "[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}",
                    help: "Copy the ID from Money → Transactions. The backend verifies ownership and currency.",
                  },
                  {
                    ...amountField,
                    label: `Linked contribution amount (${g.currency})`,
                  },
                  {
                    name: "note",
                    label: "Linked contribution note",
                    maxLength: 500,
                  },
                ]}
                onSubmit={async (data) => {
                  await mutate(`/goals/${g.id}/contributions`, "POST", {
                    source_type: "transaction",
                    amount: value(data, "amount"),
                    transaction_id: value(data, "transaction_id"),
                    note: optional(data, "note"),
                  } satisfies Schema<"ContributionCreateRequest">);
                }}
              />
            </>
          )}
          <Result query={contributions}>
            {(data) => (
              <DataTable
                title="Contributions"
                headings={["Date", "Source", "Amount", "Note", "Action"]}
                rows={data.items.map((c) => [
                  c.contribution_date,
                  c.source_type,
                  money(c.amount, g.currency),
                  c.note || "—",
                  g.status === "active" ? (
                    <ConfirmAction
                      label="Remove contribution"
                      detail={`Remove the ${money(c.amount, g.currency)} contribution dated ${c.contribution_date}? This changes goal progress.`}
                      action={() =>
                        mutate(`/goals/${g.id}/contributions/${c.id}`, "DELETE")
                      }
                    />
                  ) : (
                    "Read only"
                  ),
                ])}
              />
            )}
          </Result>
        </Stack>
      )}
    </Result>
  );
}

function Snapshot({ currency }: { currency: string }) {
  const query = useResource<Schema<"GoalPlanningSnapshotResponse">>(
    `/goal-planning/snapshot?currency=${encodeURIComponent(currency)}`,
  );
  return (
    <Result query={query}>
      {(s) => (
        <Stack spacing={2}>
          <Typography variant="h2">Planning evidence</Typography>
          <Typography>
            {s.currency} · Cutoff {s.cutoff_at} · {s.timezone}
          </Typography>
          {s.warnings.length > 0 && (
            <Alert severity="warning">
              <Reasons items={s.warnings} />
            </Alert>
          )}
          <Typography>
            {s.goals.length} eligible goals · Profile{" "}
            {s.profile?.completion_status || "missing"} ·{" "}
            {s.budgets.active_budget_count} active budgets
          </Typography>
          <DataTable
            title="Planning financial evidence"
            headings={[
              "Liquid balance (not automatically allocated)",
              "Outstanding debt",
              "Monthly debt payment",
              "Budget limits",
            ]}
            rows={[
              [
                money(s.finances.liquid_balance, s.currency),
                money(s.finances.outstanding_debt, s.currency),
                money(s.finances.monthly_debt_payment, s.currency),
                money(s.budgets.total_overall_limit, s.currency),
              ],
            ]}
          />
          {s.savings_capacity ? (
            <>
              <Typography>
                Forecast reliability: {words(s.savings_capacity.reliability)} ·
                Protection band: {s.savings_capacity.protection_band}
              </Typography>
              <DataTable
                title="Forecast savings capacity"
                headings={["Protected", "Expected", "Upside"]}
                rows={[
                  [
                    money(s.savings_capacity.protected_total, s.currency),
                    money(s.savings_capacity.expected_total, s.currency),
                    money(s.savings_capacity.upside_total, s.currency),
                  ],
                ]}
              />
              <Button
                component={Link}
                to={`/app/forecasts?run=${s.savings_capacity.forecast_run_id}`}
              >
                View source savings forecast
              </Button>
            </>
          ) : (
            <Alert severity="warning">
              No usable savings forecast. Generate a savings forecast for this
              currency before relying on a plan.
            </Alert>
          )}
          <Button component={Link} to="/app/forecasts">
            Generate savings forecast
          </Button>
        </Stack>
      )}
    </Result>
  );
}

export function PlanDetail({
  id,
  onSelect,
}: {
  id: string;
  onSelect: (id: string) => void;
}) {
  const query = useResource<Schema<"GoalPlanRunResponse">>(
    `/goal-plans/${encodeURIComponent(id)}`,
  );
  const mutate = useFinanceMutation();
  return (
    <Result query={query}>
      {(p) => (
        <Stack spacing={2}>
          <Typography variant="h2">Plan result</Typography>
          <Typography>
            {p.status} · {words(p.strategy)} · Feasibility:{" "}
            {words(p.overall_feasibility)} · Forecast reliability:{" "}
            {words(p.forecast_reliability)}
          </Typography>
          <Typography variant="body2" sx={{ overflowWrap: "anywhere" }}>
            Plan {p.id} · Created {p.created_at} · Evidence cutoff{" "}
            {p.planning_cutoff_at} · {p.timezone}
          </Typography>
          <Alert severity={p.strategy === "blocked" ? "warning" : "info"}>
            Plans are advisory. Approval records your decision and does not move
            money. Changes to goals or evidence require regeneration; existing
            plan evidence stays immutable.
          </Alert>
          <Reasons
            items={[
              ...p.reason_codes,
              ...p.snapshot_warnings,
              ...p.guardrail_reason_codes,
            ]}
          />
          <Typography>Assumptions</Typography>
          <Reasons items={p.assumptions} />
          <DataTable
            title="Plan capacity"
            headings={[
              "Available savings",
              "Allocated",
              "Unallocated",
              "Emergency reserve",
            ]}
            rows={[
              [
                money(p.available_savings, p.currency),
                money(p.allocated_savings, p.currency),
                money(p.unallocated_savings, p.currency),
                money(p.emergency_reserve_amount, p.currency),
              ],
            ]}
          />
          <Stack direction="row" sx={{ flexWrap: "wrap" }}>
            {p.status === "generated" && (
              <>
                {p.strategy !== "blocked" && (
                  <ConfirmAction
                    label="Approve plan"
                    detail={`Approve this ${p.currency} plan allocating ${money(p.allocated_savings, p.currency)}? This records a decision only; it does not move money.`}
                    action={() => mutate(`/goal-plans/${p.id}/approve`, "POST")}
                  />
                )}
                <ConfirmAction
                  label="Reject plan"
                  detail="Reject this generated plan? Its evidence and decision history will remain available."
                  action={() => mutate(`/goal-plans/${p.id}/reject`, "POST")}
                />
              </>
            )}
            {["generated", "approved"].includes(p.status) && (
              <ConfirmAction
                label="Regenerate plan"
                detail="Create a new version from current evidence and supersede this plan? Review the new version before approving it."
                action={async () => {
                  const next = await mutate<Schema<"GoalPlanRunResponse">>(
                    `/goal-plans/${p.id}/regenerate`,
                    "POST",
                  );
                  onSelect(next.id);
                }}
              />
            )}
            {p.predecessor_plan_id && (
              <Button onClick={() => onSelect(p.predecessor_plan_id!)}>
                Previous version
              </Button>
            )}
            {p.successor_plan_id && (
              <Button onClick={() => onSelect(p.successor_plan_id!)}>
                Next version
              </Button>
            )}
          </Stack>
          {p.forecast_run_id && (
            <Button
              component={Link}
              to={`/app/forecasts?run=${p.forecast_run_id}`}
            >
              View plan forecast
            </Button>
          )}
          <Typography variant="h2">Goal outcomes</Typography>
          <Typography variant="body2">
            Completion probabilities are server estimates (0–1), not guarantees;
            unavailable is different from zero.
          </Typography>
          {p.outcomes.length === 0 && (
            <Alert severity="info">
              No eligible goal outcomes in this plan.
            </Alert>
          )}
          {p.outcomes.map((o) => (
            <Paper key={o.goal_id} variant="outlined" sx={{ p: 2 }}>
              <Typography variant="h3">
                {o.rank}. {o.goal_name}
              </Typography>
              <Typography>
                {o.priority} priority · {words(o.feasibility_state)} · Deadline
                risk: {o.deadline_risk} · Evidence:{" "}
                {words(o.evidence_reliability)}
              </Typography>
              <DataTable
                title={`${o.goal_name} outcome`}
                headings={[
                  "Allocated",
                  "Expected shortfall",
                  "Protected shortfall",
                  "Completion probability",
                  "Projected completion",
                  "Deadline met",
                ]}
                rows={[
                  [
                    money(o.allocated_amount, p.currency),
                    money(o.expected_shortfall, p.currency),
                    money(o.protected_shortfall, p.currency),
                    o.completion_probability ?? "Unavailable",
                    o.projected_completion_period || "Unavailable",
                    o.deadline_met ? "Yes" : "No",
                  ],
                ]}
              />
              <Typography>
                Target date: {o.target_date} · Expected completion:{" "}
                {o.expected_completion_period || "Unavailable"}
              </Typography>
              <Reasons
                items={[
                  ...o.feasibility_reason_codes,
                  ...o.ranking_reason_codes,
                ]}
              />
            </Paper>
          ))}
          <DataTable
            title={`Allocation schedule (${p.currency})`}
            headings={[
              "Period",
              "Goal",
              "Allocation",
              "Cumulative",
              "Remaining",
            ]}
            rows={p.periods.flatMap((period) =>
              period.allocations.map((a) => [
                period.period_start,
                p.outcomes.find((o) => o.goal_id === a.goal_id)?.goal_name ||
                  a.goal_id,
                a.amount,
                a.cumulative_amount,
                a.projected_remaining_amount,
              ]),
            )}
          />
          <DataTable
            title={`Period capacity (${p.currency})`}
            headings={["Period", "Available", "Allocated", "Unallocated"]}
            rows={p.periods.map((period) => [
              period.period_start,
              period.available_capacity,
              period.allocated_amount,
              period.unallocated_amount,
            ])}
          />
          <DataTable
            title="Plan decision history"
            headings={["When", "From", "To", "Source", "Reason"]}
            rows={p.events.map((e) => [
              e.occurred_at,
              e.previous_status || "—",
              e.status,
              e.source,
              words(e.reason_code || "—"),
            ])}
          />
        </Stack>
      )}
    </Result>
  );
}

function Plans() {
  const { user } = useSession();
  const [currency, setCurrency] = useState(user?.default_currency || "INR");
  const [params, setParams] = useSearchParams();
  const id = params.get("plan");
  const history = useResource<Schema<"GoalPlanListResponse">>(
    "/goal-plans?limit=20",
  );
  const mutate = useFinanceMutation();
  const select = (plan: string) => setParams({ tab: "plans", plan });
  return (
    <Stack spacing={3}>
      <Form
        title="Planning currency"
        submit="Load planning evidence"
        fields={[{ ...currencyField, value: currency }]}
        onSubmit={async (data) =>
          setCurrency(value(data, "currency").toUpperCase())
        }
      />
      <Snapshot currency={currency} />
      <ConfirmAction
        label="Generate plan"
        detail={`Generate an advisory plan using current ${currency} evidence? Goals in other currencies are excluded, with no currency conversion.`}
        action={async () => {
          const p = await mutate<Schema<"GoalPlanRunResponse">>(
            "/goal-plans",
            "POST",
            { currency } satisfies Schema<"GoalPlanGenerationRequest">,
          );
          select(p.id);
        }}
      />
      <Result query={history}>
        {(data) => (
          <>
            <Typography variant="h2">Recent plans</Typography>
            <Typography variant="body2">
              Up to 20 most recent plans across currencies.
            </Typography>
            <DataTable
              title="Plan history"
              headings={["Created", "Currency", "Status", "Strategy", "Open"]}
              rows={data.items.map((p) => [
                p.created_at,
                p.currency,
                p.status,
                words(p.strategy),
                <Button onClick={() => select(p.id)}>
                  View plan {p.id.slice(0, 8)}
                </Button>,
              ])}
            />
          </>
        )}
      </Result>
      {id && (
        <Paper sx={{ p: 3 }}>
          <PlanDetail key={id} id={id} onSelect={select} />
        </Paper>
      )}
    </Stack>
  );
}

export default function Goals() {
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") === "plans" ? "plans" : "goals";
  const id = params.get("goal");
  const [status, setStatus] = useState("active");
  const goals = useResource<Schema<"GoalListResponse">>(
    `/goals?limit=100${status ? `&status=${status}` : ""}`,
    tab === "goals",
  );
  return (
    <Stack spacing={3}>
      <PageHeading
        title="Goals &amp; Plans"
        description="Make room for what matters, one contribution and one decision at a time."
        icon="goals"
      />
      <Tabs
        value={tab}
        onChange={(_, next: string) => setParams({ tab: next })}
        aria-label="Goal sections"
      >
        <Tab
          value="goals"
          label="Goals"
          id="goals-tab"
          aria-controls="goals-panel"
        />
        <Tab
          value="plans"
          label="Plans"
          id="plans-tab"
          aria-controls="goals-panel"
        />
      </Tabs>
      <Stack
        role="tabpanel"
        id="goals-panel"
        aria-labelledby={`${tab}-tab`}
        spacing={3}
      >
        {tab === "plans" ? (
          <Plans />
        ) : (
          <>
            <Paper sx={{ p: 3 }}>
              <GoalForm onSaved={(goal) => setParams({ goal })} />
            </Paper>
            <Form
              title="Goal status"
              submit="Filter goals"
              fields={[
                {
                  name: "status",
                  label: "Status",
                  value: status,
                  options: [
                    { value: "", label: "All statuses" },
                    "active",
                    "completed",
                    "cancelled",
                  ],
                },
              ]}
              onSubmit={async (data) => setStatus(value(data, "status"))}
            />
            <Result query={goals}>
              {(data) => (
                <>
                  <Typography variant="body2">
                    Up to 100 goals. Completed and cancelled goals retain their
                    history.
                  </Typography>
                  <DataTable
                    title="Your goals"
                    headings={[
                      "Name",
                      "Target",
                      "Deadline",
                      "Priority",
                      "Status",
                      "Open",
                    ]}
                    rows={data.items.map((g) => [
                      g.name,
                      money(g.target_amount, g.currency),
                      g.target_date,
                      g.priority,
                      g.status,
                      <Button onClick={() => setParams({ goal: g.id })}>
                        View {g.name}
                      </Button>,
                    ])}
                  />
                </>
              )}
            </Result>
            {id && (
              <Paper sx={{ p: 3 }}>
                <GoalDetail key={id} id={id} />
              </Paper>
            )}
          </>
        )}
      </Stack>
    </Stack>
  );
}
