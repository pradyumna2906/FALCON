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
import { useSession } from "../auth/session";
import {
  useResource,
  useFinanceMutation,
  money,
  type Schema,
} from "../api/finance";
import {
  Form,
  currencyField,
  amountField,
  InputError,
  value,
} from "../components/Forms";
import {
  DataTable,
  Evidence,
  Reasons,
  Result,
  words,
} from "../components/FinancialResults";

function CashFlow({ query }: { query: string }) {
  const result = useResource<Schema<"CashFlowAnalyticsResponse">>(
    `/analytics/cash-flow?${query}`,
  );
  return (
    <Result query={result}>
      {(d) => (
        <Stack spacing={2}>
          <Evidence context={d.context} />
          {d.context.comparison_period && (
            <Typography>
              Comparison: {d.context.comparison_period.date_from} to{" "}
              {d.context.comparison_period.date_to}
            </Typography>
          )}
          <DataTable
            title="Cash-flow comparison"
            headings={["Metric", "Selected period", "Previous period"]}
            rows={(
              [
                "gross_income",
                "total_expense",
                "net_cash_flow",
                "savings_amount",
                "internal_transfer_volume",
                "net_adjustment",
              ] as const
            ).map((k) => [
              words(k),
              money(d.metrics[k].value, d.context.currency),
              money(d.previous_period?.[k].value, d.context.currency),
            ])}
          />
          <Typography>
            Savings rate (ratio):{" "}
            {d.metrics.savings_rate.value ?? "Unavailable"} · Previous:{" "}
            {d.previous_period?.savings_rate.value ?? "Unavailable"}
          </Typography>
          <DataTable
            title="Cash-flow trend"
            headings={[
              "Period",
              "Income",
              "Expenses",
              "Net cash flow",
              "Transactions",
            ]}
            rows={d.series.map((p) => [
              p.period_start,
              money(p.gross_income.value, d.context.currency),
              money(p.total_expense.value, d.context.currency),
              money(p.net_cash_flow.value, d.context.currency),
              p.transaction_count,
            ])}
          />
        </Stack>
      )}
    </Result>
  );
}

function AccountDrilldown({
  account,
  context,
  close,
}: {
  account: Schema<"SpendingAccount">;
  context: Schema<"AnalyticsContext">;
  close: () => void;
}) {
  const [cursor, setCursor] = useState("");
  const params = new URLSearchParams({
    account_id: account.account_id,
    transaction_type: "expense",
    status: "posted",
    date_from: context.period.date_from,
    date_to: context.period.date_to,
    limit: "25",
  });
  if (cursor) params.set("cursor", cursor);
  const result = useResource<Schema<"TransactionPageResponse">>(
    `/transactions?${params}`,
  );
  return (
    <Paper variant="outlined" sx={{ p: 2 }}>
      <Stack spacing={2}>
        <Typography variant="h2">{account.name} expenses</Typography>
        <Typography>
          {context.currency} · Posted expenses in the selected period, 25 per
          page.
        </Typography>
        <Button onClick={close}>Close account details</Button>
        <Result query={result}>
          {(d) => (
            <>
              <DataTable
                title="Account expense details"
                headings={["Date", "Description", "Merchant", "Amount"]}
                rows={d.items.map((t) => [
                  t.transaction_date,
                  t.description,
                  t.merchant_name || "—",
                  money(t.amount, context.currency),
                ])}
              />
              <Stack direction="row">
                <Button disabled={!cursor} onClick={() => setCursor("")}>
                  First page
                </Button>
                <Button
                  disabled={!d.next_cursor || result.isFetching}
                  onClick={() => setCursor(d.next_cursor || "")}
                >
                  Next page
                </Button>
              </Stack>
            </>
          )}
        </Result>
      </Stack>
    </Paper>
  );
}

function Spending({ query }: { query: string }) {
  const result = useResource<Schema<"SpendingAnalyticsResponse">>(
    `/analytics/spending?${query}&limit=25`,
  );
  const [account, setAccount] = useState<Schema<"SpendingAccount"> | null>(
    null,
  );
  return (
    <Result query={result}>
      {(d) => (
        <Stack spacing={2}>
          <Evidence context={d.context} />
          <Typography>
            Total expenses: {money(d.total_expense.value, d.context.currency)} ·
            Previous period:{" "}
            {money(d.previous_period_total_expense?.value, d.context.currency)}
          </Typography>
          {d.context.comparison_period && (
            <Typography>
              Previous period: {d.context.comparison_period.date_from} to{" "}
              {d.context.comparison_period.date_to}
            </Typography>
          )}
          <Typography variant="body2">
            Top 25 entries per dimension. Shares are server-provided ratios
            (0–1); rows may not represent all spending.
          </Typography>
          <DataTable
            title="Spending by category"
            headings={["Category", "Amount", "Share", "Transactions"]}
            rows={d.categories.map((c) => [
              c.name,
              money(c.amount.value, d.context.currency),
              c.share.value,
              c.transaction_count,
            ])}
          />
          <DataTable
            title="Spending by merchant"
            headings={["Merchant", "Amount", "Share", "Transactions"]}
            rows={d.merchants.map((m) => [
              m.display_name || m.normalized_merchant || "Unknown merchant",
              money(m.amount.value, d.context.currency),
              m.share.value,
              m.transaction_count,
            ])}
          />
          <DataTable
            title="Spending by account"
            headings={["Account", "Amount", "Share", "Transactions", "Details"]}
            rows={d.accounts.map((a) => [
              a.name,
              money(a.amount.value, d.context.currency),
              a.share.value,
              a.transaction_count,
              <Button onClick={() => setAccount(a)}>Explore {a.name}</Button>,
            ])}
          />
          {account && (
            <AccountDrilldown
              key={account.account_id}
              account={account}
              context={d.context}
              close={() => setAccount(null)}
            />
          )}
        </Stack>
      )}
    </Result>
  );
}

function Recurring({ query }: { query: string }) {
  const result = useResource<Schema<"RecurringAnalyticsResponse">>(
    `/analytics/recurring?${query}&limit=25&include_abstained=true`,
  );
  return (
    <Result query={result}>
      {(d) => (
        <Stack spacing={2}>
          <Evidence context={d.context} />
          <Typography>
            {d.summary.detected_pattern_count} detected patterns ·{" "}
            {d.summary.abstained_pattern_count} abstained ·{" "}
            {d.minimum_occurrences} minimum occurrences
          </Typography>
          <Alert severity="info">
            Recurring candidates and subscriptions are observations, not
            confirmed contracts. Abstained means there is not enough consistent
            evidence.
          </Alert>
          {d.summary.truncated && (
            <Alert severity="info">
              Showing the first {d.summary.returned_pattern_count} patterns.
            </Alert>
          )}
          {d.patterns.length === 0 && (
            <Typography>
              No recurring patterns found for this selection.
            </Typography>
          )}
          {d.patterns.map((p, i) => (
            <Paper key={i} variant="outlined" sx={{ p: 2 }}>
              <Typography variant="h2">
                {p.display_name ||
                  p.normalized_merchant ||
                  p.category_name ||
                  "Unknown merchant"}
              </Typography>
              <Typography>
                {words(p.pattern_type)} · {p.decision} · {p.cadence} ·{" "}
                {p.confidence_band} confidence
              </Typography>
              <Typography>{p.explanation}</Typography>
              <Typography>
                {p.occurrence_count} occurrences · {p.first_observed_date} to{" "}
                {p.last_observed_date} · Typical{" "}
                {money(p.median_amount.value, d.context.currency)} · Observed
                total {money(p.observed_total.value, d.context.currency)}
              </Typography>
              <Reasons items={p.reason_codes} />
            </Paper>
          ))}
        </Stack>
      )}
    </Result>
  );
}

function Signals({ query }: { query: string }) {
  const result = useResource<Schema<"SpendingSignalAnalyticsResponse">>(
    `/analytics/spending-signals?${query}&limit=25`,
  );
  return (
    <Result query={result}>
      {(d) => (
        <Stack spacing={2}>
          <Evidence context={d.context} />
          <Alert severity="info">
            Leaks and anomalies are review signals. They do not establish fraud,
            duplicates, or guaranteed savings.
          </Alert>
          <DataTable
            title="Signal evaluation coverage"
            headings={["Check", "Status", "Observations", "Explanation"]}
            rows={d.evaluations.map((e) => [
              words(e.signal_type),
              words(e.status),
              e.source_observation_count,
              e.explanation,
            ])}
          />
          {d.summary.truncated && (
            <Alert severity="info">
              Results are truncated to {d.summary.returned_signal_count}{" "}
              signals.
            </Alert>
          )}
          {d.signals.length === 0 && (
            <Typography>
              No signals returned. Review evaluation coverage for
              insufficient-data checks.
            </Typography>
          )}
          {d.signals.map((s, i) => (
            <Paper key={i} variant="outlined" sx={{ p: 2 }}>
              <Typography variant="h2">{words(s.signal_type)}</Typography>
              <Typography>
                {s.severity} severity · {words(s.family)} ·{" "}
                {s.display_name || s.category_name || "Period evidence"}
              </Typography>
              <Typography>{s.explanation}</Typography>
              <Typography>
                Observed {money(s.observed_amount.value, d.context.currency)} ·
                Baseline {money(s.baseline_amount?.value, d.context.currency)} ·
                Excess {money(s.excess_amount?.value, d.context.currency)}
              </Typography>
              <Reasons items={s.reason_codes} />
            </Paper>
          ))}
        </Stack>
      )}
    </Result>
  );
}

function Health({ query }: { query: string }) {
  const result = useResource<Schema<"FinancialHealthScoreResponse">>(
    `/analytics/health-score?${query}`,
  );
  return (
    <Result query={result}>
      {(d) => (
        <Stack spacing={2}>
          <Evidence context={d.context} />
          <Typography variant="h2">
            Health score: {d.score ?? "Unavailable"} · {d.status}
          </Typography>
          <Typography>{d.explanation}</Typography>
          <DataTable
            title="Health factors"
            headings={[
              "Factor",
              "Status",
              "Score",
              "Observed",
              "Benchmark",
              "Effective weight",
              "Explanation",
            ]}
            rows={d.factors.map((f) => [
              words(f.factor),
              f.status,
              f.factor_score,
              f.observed_value,
              f.benchmark_value,
              f.effective_weight,
              f.explanation,
            ])}
          />
        </Stack>
      )}
    </Result>
  );
}

function Insights({ query }: { query: string }) {
  const result = useResource<Schema<"InsightAnalyticsResponse">>(
    `/analytics/insights?${query}&limit=25`,
  );
  return (
    <Result query={result}>
      {(d) => (
        <Stack spacing={2}>
          <Evidence context={d.context} />
          <Typography>
            {words(d.status)} · {d.explanation}
          </Typography>
          {d.summary.truncated && (
            <Alert severity="info">
              Showing {d.summary.returned_insight_count} prioritized insights.
            </Alert>
          )}
          {d.insights.length === 0 && (
            <Typography>
              No recommendations available for this selection.
            </Typography>
          )}
          {d.insights.map((i) => (
            <Paper key={i.insight_id} variant="outlined" sx={{ p: 2 }}>
              <Typography variant="h2">{i.title}</Typography>
              <Typography>
                {i.severity} severity · {i.urgency} · {i.confidence} confidence
              </Typography>
              <Typography>{i.explanation}</Typography>
              <Typography>Suggested action: {i.recommended_action}</Typography>
              <Typography>
                Estimated period impact:{" "}
                {money(i.estimated_period_impact?.value, d.context.currency)} ·{" "}
                {words(i.impact_basis || "No quantified impact")}
              </Typography>
              <Reasons items={i.reason_codes} />
            </Paper>
          ))}
        </Stack>
      )}
    </Result>
  );
}

function BudgetResult({ id }: { id: string }) {
  const result = useResource<Schema<"BudgetAnalyticsResponse">>(
    `/analytics/budgets/${encodeURIComponent(id)}`,
  );
  return (
    <Result query={result}>
      {(d) => (
        <Stack spacing={2}>
          <Evidence context={d.context} />
          <Typography variant="h2">
            {d.budget.name} · {words(d.status)}
          </Typography>
          <Typography>
            Stored budget period: {d.budget.period_start_date} to{" "}
            {d.budget.period_end_date}; observed through {d.observed_to}. Budget
            analysis uses its own period and currency.
          </Typography>
          <Alert severity="info">
            Overspending projections use observed spending pace, not the
            forecasting model.
          </Alert>
          <DataTable
            title="Budget variance and risk"
            headings={[
              "Scope",
              "Limit",
              "Spent",
              "Remaining",
              "Pace variance",
              "Projected spend",
              "Projected overspend",
              "Risk",
              "Warning",
            ]}
            rows={[
              { name: "Overall", performance: d.overall },
              ...d.categories,
            ].map(({ name, performance: p }) => [
              name,
              money(p.limit_amount?.value, d.context.currency),
              money(p.spent_amount.value, d.context.currency),
              money(p.remaining_allowance?.value, d.context.currency),
              money(p.pace_variance?.value, d.context.currency),
              money(p.pace_projected_spend?.value, d.context.currency),
              money(p.projected_overspend_amount?.value, d.context.currency),
              p.risk_level,
              words(p.warning_status),
            ])}
          />
          <Typography>
            Outside configured categories:{" "}
            {money(d.outside_configured_categories.value, d.context.currency)}
          </Typography>
        </Stack>
      )}
    </Result>
  );
}

function Budgets({ currency }: { currency: string }) {
  const [offset, setOffset] = useState(0),
    [id, setId] = useState("");
  const result = useResource<Schema<"BudgetListResponse">>(
    `/budgets?limit=20&offset=${offset}`,
  );
  const mutate = useFinanceMutation();
  return (
    <Stack spacing={3}>
      <Form
        title="Create budget"
        submit="Create budget"
        fields={[
          {
            name: "name",
            label: "Budget name",
            required: true,
            maxLength: 120,
          },
          { ...currencyField, value: currency },
          {
            name: "period_start_date",
            label: "Budget start",
            type: "date",
            required: true,
          },
          {
            name: "period_end_date",
            label: "Budget end",
            type: "date",
            required: true,
          },
          {
            ...amountField,
            name: "overall_limit",
            label: "Overall spending limit",
          },
        ]}
        onSubmit={async (data) => {
          if (value(data, "period_start_date") > value(data, "period_end_date"))
            throw new InputError("Budget start must not be after budget end.");
          const b = await mutate<Schema<"BudgetResponse">>("/budgets", "POST", {
            name: value(data, "name"),
            currency: value(data, "currency").toUpperCase(),
            period_start_date: value(data, "period_start_date"),
            period_end_date: value(data, "period_end_date"),
            overall_limit: value(data, "overall_limit"),
            limits: [],
          } satisfies Schema<"BudgetRequest">);
          setId(b.id);
        }}
      />
      <Result query={result}>
        {(d) => (
          <>
            <DataTable
              title="Active budgets"
              headings={["Name", "Currency", "Period", "Analysis"]}
              rows={d.items.map((b) => [
                b.name,
                b.currency,
                `${b.period_start_date} – ${b.period_end_date}`,
                <Button onClick={() => setId(b.id)}>Analyze {b.name}</Button>,
              ])}
            />
            <Stack direction="row">
              <Button
                disabled={!offset}
                onClick={() => setOffset(Math.max(0, offset - 20))}
              >
                Previous budgets
              </Button>
              <Button
                disabled={!d.has_more || offset >= 10000 || result.isFetching}
                onClick={() => setOffset(offset + 20)}
              >
                Next budgets
              </Button>
            </Stack>
          </>
        )}
      </Result>
      {id && <BudgetResult id={id} />}
    </Stack>
  );
}

const sections = {
  cash: "Cash flow",
  spending: "Spending",
  recurring: "Recurring & subscriptions",
  signals: "Leaks & anomalies",
  budgets: "Budgets & risk",
  health: "Health factors",
  insights: "Insights",
};
export default function Analytics() {
  const { user } = useSession();
  const [tab, setTab] = useState<keyof typeof sections>("cash");
  const [filters, setFilters] = useState({
    currency: user?.default_currency || "INR",
    date_from: "",
    date_to: "",
    comparison: "previous_period",
    granularity: "month",
  });
  const base = new URLSearchParams({ currency: filters.currency });
  if (filters.date_from) base.set("date_from", filters.date_from);
  if (filters.date_to) base.set("date_to", filters.date_to);
  const common = base.toString();
  return (
    <Stack spacing={3}>
      <Typography component="h1" variant="h1">
        Analytics
      </Typography>
      <Paper sx={{ p: 3 }}>
        <Form
          title="Analysis filters"
          submit="Apply analysis filters"
          fields={[
            { ...currencyField, value: filters.currency },
            { name: "date_from", label: "From date", type: "date" },
            { name: "date_to", label: "To date", type: "date" },
            {
              name: "comparison",
              label: "Comparison",
              value: filters.comparison,
              options: ["previous_period", "none"],
            },
            {
              name: "granularity",
              label: "Cash-flow buckets",
              value: filters.granularity,
              options: ["day", "month"],
            },
          ]}
          onSubmit={async (data) => {
            if (
              value(data, "date_from") &&
              value(data, "date_to") &&
              value(data, "date_from") > value(data, "date_to")
            )
              throw new InputError("From date must not be after To date.");
            setFilters({
              currency: value(data, "currency").toUpperCase(),
              date_from: value(data, "date_from"),
              date_to: value(data, "date_to"),
              comparison: value(data, "comparison"),
              granularity: value(data, "granularity"),
            });
          }}
        />
      </Paper>
      <Tabs
        value={tab}
        variant="scrollable"
        scrollButtons="auto"
        aria-label="Analytics sections"
        onChange={(_, next: keyof typeof sections) => setTab(next)}
      >
        {Object.entries(sections).map(([key, label]) => (
          <Tab
            key={key}
            value={key}
            label={label}
            id={`analytics-${key}`}
            aria-controls="analytics-panel"
          />
        ))}
      </Tabs>
      <Stack
        key={`${tab}-${common}-${filters.comparison}-${filters.granularity}`}
        role="tabpanel"
        id="analytics-panel"
        aria-labelledby={`analytics-${tab}`}
        spacing={2}
      >
        {tab === "cash" && (
          <CashFlow
            query={`${common}&comparison=${filters.comparison}&granularity=${filters.granularity}`}
          />
        )}
        {tab === "spending" && (
          <Spending query={`${common}&comparison=${filters.comparison}`} />
        )}
        {tab === "recurring" && <Recurring query={common} />}
        {tab === "signals" && <Signals query={common} />}
        {tab === "budgets" && <Budgets currency={filters.currency} />}
        {tab === "health" && <Health query={common} />}
        {tab === "insights" && <Insights query={common} />}
      </Stack>
    </Stack>
  );
}
