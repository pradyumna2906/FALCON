import { useState } from "react";
import { Alert, Button, Paper, Stack, Typography } from "@mui/material";
import { Link, useSearchParams } from "react-router";
import {
  money,
  useFinanceMutation,
  useResource,
  type Schema,
} from "../api/finance";
import { Form, value, type Field } from "../components/Forms";
import { ConfirmAction } from "../components/ConfirmAction";
import { DataTable, Reasons, Result } from "../components/FinancialResults";

type Definition = Schema<"ScenarioDefinitionRequest-Input">;
const fields: Field[] = [
  { name: "name", label: "Alternative name", required: true, maxLength: 80 },
  {
    name: "income_change_percent",
    label: "Income change (%)",
    value: "0",
    required: true,
  },
  {
    name: "expense_change_percent",
    label: "Expense change (%)",
    value: "0",
    required: true,
  },
  { name: "start", label: "Adjustment start month", type: "month" },
  { name: "end", label: "Adjustment end month", type: "month" },
  {
    name: "one_time",
    label: "One-time expense",
    help: "Applied in the adjustment start month.",
  },
  { name: "recurring", label: "Monthly recurring expense change" },
  { name: "debt", label: "Monthly debt payment change" },
  { name: "retained", label: "Income retained during interruption (%)" },
  { name: "goal_id", label: "Goal ID (optional)" },
  { name: "target_amount", label: "Hypothetical goal target amount" },
  { name: "target_date", label: "Hypothetical goal deadline", type: "date" },
  {
    name: "priority",
    label: "Hypothetical priority",
    options: ["", "critical", "high", "medium", "low"],
  },
  { name: "contribution", label: "Monthly goal contribution change" },
  { name: "pause_start", label: "Pause contributions from", type: "month" },
  { name: "pause_end", label: "Pause contributions through", type: "month" },
  { name: "reserve", label: "Emergency reserve target (months)" },
];
const month = (data: FormData, name: string) =>
  value(data, name) ? `${value(data, name)}-01` : "";
export function scenarioInput(data: FormData): Definition {
  const start_period = month(data, "start");
  const end_period = month(data, "end");
  return {
    name: value(data, "name"),
    income_change_percent: value(data, "income_change_percent"),
    expense_change_percent: value(data, "expense_change_percent"),
    one_time_expenses: value(data, "one_time")
      ? [{ period_start: start_period, amount: value(data, "one_time") }]
      : [],
    recurring_expense_adjustments: value(data, "recurring")
      ? [{ start_period, end_period, monthly_delta: value(data, "recurring") }]
      : [],
    debt_payment_adjustments: value(data, "debt")
      ? [{ start_period, end_period, monthly_delta: value(data, "debt") }]
      : [],
    income_interruptions: value(data, "retained")
      ? [
          {
            start_period,
            end_period,
            retained_income_percent: value(data, "retained"),
          },
        ]
      : [],
    goal_adjustments: value(data, "goal_id")
      ? [
          {
            goal_id: value(data, "goal_id"),
            target_amount: value(data, "target_amount") || null,
            target_date: value(data, "target_date") || null,
            priority: (value(data, "priority") ||
              null) as Schema<"GoalPriority"> | null,
            monthly_contribution_delta: value(data, "contribution") || null,
            pause_start: month(data, "pause_start") || null,
            pause_end: month(data, "pause_end") || null,
          },
        ]
      : [],
    emergency_fund_target_months: value(data, "reserve") || null,
  };
}

export default function Scenarios() {
  const [params, setParams] = useSearchParams();
  const id = params.get("run");
  const [drafts, setDrafts] = useState<Definition[]>([]);
  const plans = useResource<Schema<"GoalPlanListResponse">>(
    "/goal-plans?limit=20",
  );
  const history = useResource<Schema<"ScenarioSimulationListResponse">>(
    "/scenario-simulations?limit=20",
  );
  const run = useResource<Schema<"ScenarioSimulationRunResponse">>(
    `/scenario-simulations/${id}`,
    !!id,
  );
  const mutate = useFinanceMutation();
  return (
    <Stack spacing={3}>
      <Typography variant="h1">Scenarios</Typography>
      <Alert severity="info">
        Explore hypothetical changes against a saved goal plan. Simulating or
        selecting an alternative never changes your transactions, goals or
        approved plan. Probabilities are estimates from the stored simulation.
      </Alert>
      <Result query={plans}>
        {(data) =>
          data.items.length ? (
            <Paper sx={{ p: 2 }}>
              <Form
                title="Build an alternative"
                fields={fields}
                submit="Add alternative"
                onSubmit={async (data) => {
                  setDrafts((current) => [...current, scenarioInput(data)]);
                }}
              />
              <Typography>
                Added {drafts.length} alternatives. The server validates bounds,
                month ranges and goal ownership.
              </Typography>
              {drafts.map((draft, index) => (
                <Stack direction="row" key={index}>
                  <Typography sx={{ flex: 1 }}>{draft.name}</Typography>
                  <Button
                    onClick={() =>
                      setDrafts((current) =>
                        current.filter((_, i) => i !== index),
                      )
                    }
                  >
                    Remove {draft.name}
                  </Button>
                </Stack>
              ))}
              {drafts.length > 0 && (
                <Form
                  title="Run simulation"
                  fields={[
                    {
                      name: "plan",
                      label: "Source plan",
                      required: true,
                      options: data.items.map((plan) => ({
                        value: plan.id,
                        label: `${plan.currency} · ${plan.status} · ${plan.created_at}`,
                      })),
                    },
                  ]}
                  submit="Generate scenarios"
                  onSubmit={async (data) => {
                    const created = await mutate<
                      Schema<"ScenarioSimulationRunResponse">
                    >("/scenario-simulations", "POST", {
                      source_plan_id: value(data, "plan"),
                      scenarios: drafts,
                    });
                    setParams({ run: created.id });
                    setDrafts([]);
                  }}
                />
              )}
            </Paper>
          ) : (
            <Alert severity="info">
              Create a <Link to="/app/goals?tab=plans">goal plan</Link> before
              simulating alternatives.
            </Alert>
          )
        }
      </Result>
      <Result query={history}>
        {(data) => (
          <DataTable
            title="Recent simulations (up to 20)"
            headings={["Created", "Currency", "Trials", "Open"]}
            rows={data.items.map((item) => [
              item.created_at,
              item.currency,
              item.trial_count,
              <Button onClick={() => setParams({ run: item.id })}>
                Open {item.id}
              </Button>,
            ])}
          />
        )}
      </Result>
      {id && (
        <Result query={run}>
          {(data) => (
            <Stack spacing={2}>
              <Typography variant="h2">Simulation results</Typography>
              <Typography>
                {data.currency} · {data.horizon_start} to {data.horizon_end} ·{" "}
                {data.trial_count} trials · {data.probability_method} · Evidence
                cutoff {data.cutoff_at}
              </Typography>
              <Reasons
                items={[...data.snapshot_warnings, ...data.reason_codes]}
              />
              <ConfirmAction
                label="Regenerate simulation"
                detail="Create a new immutable run using the stored assumptions and current eligible evidence."
                action={async () => {
                  const next = await mutate<
                    Schema<"ScenarioSimulationRunResponse">
                  >(`/scenario-simulations/${id}/regenerate`, "POST");
                  setParams({ run: next.id });
                }}
              />
              {data.selected_scenario_id && (
                <ConfirmAction
                  label="Clear selection"
                  detail="Clear this run's current scenario choice."
                  action={() =>
                    mutate(`/scenario-simulations/${id}/select`, "POST", {
                      scenario_definition_id: null,
                      expected_selected_scenario_id: data.selected_scenario_id,
                    })
                  }
                />
              )}
              <DataTable
                title="Ranked alternatives versus baseline"
                headings={[
                  "Rank",
                  "Alternative",
                  "Recommended",
                  "Capacity delta",
                  "Completion probability delta",
                  "Tail shortfall delta",
                  "Decision score",
                ]}
                rows={data.comparisons.map((item) => [
                  item.rank,
                  data.definitions.find(
                    (d) => d.id === item.scenario_definition_id,
                  )?.name,
                  item.recommended ? "Yes" : "No",
                  money(item.expected_capacity_delta, data.currency),
                  item.completion_probability_delta,
                  money(item.tail_shortfall_delta, data.currency),
                  item.decision_score,
                ])}
              />
              {data.definitions.map((def) => (
                <Paper key={def.id} sx={{ p: 2 }}>
                  <Stack spacing={2}>
                    <Typography variant="h2">
                      {def.name}
                      {def.id === data.selected_scenario_id
                        ? " · Selected"
                        : ""}
                    </Typography>
                    <Typography>
                      {def.kind} · {def.evaluation_status} · Risk{" "}
                      {def.risk_status} · Reliability {def.reliability} · Band{" "}
                      {def.selected_band}
                    </Typography>
                    <Reasons items={def.reason_codes} />
                    <DataTable
                      title={`${def.name} outcomes`}
                      headings={["Metric", "Value"]}
                      rows={[
                        [
                          "Expected capacity",
                          money(def.expected_capacity, data.currency),
                        ],
                        [
                          "Expected shortfall",
                          money(def.expected_total_shortfall, data.currency),
                        ],
                        [
                          "Tail shortfall (90%)",
                          money(def.tail_expected_shortfall_90, data.currency),
                        ],
                        [
                          "All goals completion probability (0–1)",
                          def.all_goals_completion_probability,
                        ],
                        [
                          "All deadlines met probability (0–1)",
                          def.all_deadlines_met_probability,
                        ],
                        [
                          "Reserve coverage probability (0–1)",
                          def.reserve_coverage_probability,
                        ],
                        [
                          "Negative savings probability (0–1)",
                          def.negative_savings_probability,
                        ],
                        ["Robustness score", def.robustness_score],
                      ]}
                    />
                    <DataTable
                      title={`${def.name} goal results`}
                      headings={[
                        "Goal",
                        "Risk",
                        "Completion probability",
                        "Deadline probability",
                        "Expected shortfall",
                        "Completion p10 / p50 / p90",
                      ]}
                      rows={def.outcomes.map((o) => [
                        o.goal_id,
                        o.deadline_risk,
                        o.empirical_completion_probability,
                        o.deadline_met_probability,
                        money(o.empirical_expected_shortfall, data.currency),
                        `${o.completion_period_p10 ?? "Unavailable"} / ${o.completion_period_p50 ?? "Unavailable"} / ${o.completion_period_p90 ?? "Unavailable"}`,
                      ])}
                    />
                    <DataTable
                      title={`${def.name} monthly capacity`}
                      headings={[
                        "Month",
                        "Capacity",
                        "Allocated",
                        "Unallocated",
                      ]}
                      rows={def.periods.map((p) => [
                        p.period_start,
                        money(p.selected_capacity, data.currency),
                        money(p.allocated_amount, data.currency),
                        money(p.unallocated_amount, data.currency),
                      ])}
                    />
                    {data.comparisons
                      .filter((c) => c.scenario_definition_id === def.id)
                      .map((c) => (
                        <Stack key={c.scenario_definition_id}>
                          <Reasons items={c.reason_codes} />
                          <DataTable
                            title={`${def.name} sensitivity`}
                            headings={[
                              "Factor",
                              "Capacity effect",
                              "Influence",
                              "Method",
                            ]}
                            rows={c.sensitivity_signals.map((s) => [
                              s.factor,
                              money(s.direct_capacity_effect, data.currency),
                              s.influence_score,
                              s.method,
                            ])}
                          />
                        </Stack>
                      ))}
                    {def.id !== data.selected_scenario_id && (
                      <ConfirmAction
                        label={`Select ${def.name}`}
                        detail="Record this hypothetical choice only. Financial records are unchanged."
                        action={() =>
                          mutate(`/scenario-simulations/${id}/select`, "POST", {
                            scenario_definition_id: def.id,
                            expected_selected_scenario_id:
                              data.selected_scenario_id,
                          })
                        }
                      />
                    )}
                  </Stack>
                </Paper>
              ))}
              <DataTable
                title="Selection history"
                headings={["Time", "Event", "Scenario", "Reason"]}
                rows={data.events.map((e) => [
                  e.occurred_at,
                  e.event_type,
                  e.scenario_definition_id,
                  e.reason_code,
                ])}
              />
            </Stack>
          )}
        </Result>
      )}
    </Stack>
  );
}
