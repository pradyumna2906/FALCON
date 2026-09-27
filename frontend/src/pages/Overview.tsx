import { useState } from "react";
import {
  Alert,
  Box,
  Button,
  Chip,
  LinearProgress,
  Paper,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Typography,
} from "@mui/material";
import { Link } from "react-router";
import { Form, currencyField, value } from "../components/Forms";
import {
  useResource,
  type Schema,
  localDate,
  money,
  errorMessage,
} from "../api/finance";
import { useSession } from "../auth/session";
import { LoadingState } from "../components/States";

function GoalCard({ goal }: { goal: Schema<"GoalResponse"> }) {
  const progress = useResource<Schema<"GoalProgressResponse">>(
    `/goals/${goal.id}/progress`,
  );
  return (
    <Paper variant="outlined" sx={{ p: 2 }}>
      <Typography variant="h3">{goal.name}</Typography>
      <Typography>
        Target {money(goal.target_amount, goal.currency)} · {goal.target_date}
      </Typography>
      {progress.error && (
        <Alert severity="warning">
          Goal progress unavailable. {errorMessage(progress.error)}
        </Alert>
      )}
      {progress.data && (
        <>
          <Typography>
            {money(progress.data.current_amount, goal.currency)} saved ·{" "}
            {progress.data.funding_percentage}% funded
          </Typography>
          <LinearProgress
            aria-label={`${goal.name} funding`}
            variant="determinate"
            value={Math.min(
              100,
              Math.max(0, Number(progress.data.funding_percentage)),
            )}
          />
          <Typography>
            {progress.data.funding_state.replaceAll("_", " ")}
          </Typography>
        </>
      )}
    </Paper>
  );
}

export default function Overview() {
  const { user } = useSession();
  const today = localDate(user?.timezone);
  const [period, setPeriod] = useState({
    date_from: `${today.slice(0, 7)}-01`,
    date_to: today,
    currency: user?.default_currency || "INR",
  });
  const params = new URLSearchParams(period).toString();
  const dashboard = useResource<Schema<"AnalyticsDashboardResponse">>(
    `/analytics/dashboard?${params}`,
  );
  const health = useResource<Schema<"FinancialHealthScoreResponse">>(
    `/analytics/health-score?${params}`,
  );
  const insights = useResource<Schema<"InsightAnalyticsResponse">>(
    `/analytics/insights?${params}&limit=5`,
  );
  const goals = useResource<Schema<"GoalListResponse">>(
    "/goals?status=active&limit=5",
  );
  const data = dashboard.data;
  return (
    <Stack spacing={3}>
      <Box>
        <Typography component="h1" variant="h1">
          Your financial overview
        </Typography>
        <Typography color="text.secondary">
          Live, owner-scoped results. Each currency is shown separately.
        </Typography>
      </Box>
      <Stack direction="row" sx={{ flexWrap: "wrap" }} useFlexGap spacing={1}>
        <Button
          component={Link}
          to="/app/money?tab=transactions"
          variant="contained"
        >
          Add transaction
        </Button>
        <Button component={Link} to="/app/money?tab=imports">
          Import statement
        </Button>
        <Button component={Link} to="/app/onboarding">
          Complete setup
        </Button>
        <Button href="#insights">View insights</Button>
      </Stack>
      <Paper sx={{ p: 2 }}>
        <Form
          title="Reporting period"
          submit="Apply filters"
          fields={[
            {
              name: "date_from",
              label: "From",
              type: "date",
              required: true,
              value: period.date_from,
            },
            {
              name: "date_to",
              label: "To",
              type: "date",
              required: true,
              value: period.date_to,
            },
            { ...currencyField, value: period.currency },
          ]}
          onSubmit={async (form) => {
            setPeriod({
              date_from: value(form, "date_from"),
              date_to: value(form, "date_to"),
              currency: value(form, "currency"),
            });
          }}
        />
      </Paper>
      {dashboard.isPending && <LoadingState />}
      {dashboard.error && (
        <Alert
          severity="error"
          action={
            <Button
              onClick={() => {
                void dashboard.refetch();
              }}
            >
              Retry
            </Button>
          }
        >
          {errorMessage(dashboard.error)}
        </Alert>
      )}
      {data && (
        <>
          <Stack
            direction="row"
            useFlexGap
            sx={{ flexWrap: "wrap" }}
            spacing={1}
          >
            <Chip
              label={`Coverage: ${data.context.completeness.data_confidence}`}
            />
            <Chip
              label={`${data.context.completeness.eligible_transaction_count} eligible transactions`}
            />
          </Stack>
          <Typography variant="body2">
            Calculated {data.context.freshness.calculated_at} · Source updated{" "}
            {data.context.freshness.source_last_updated_at ||
              "No transactions yet"}{" "}
            · {data.context.period.timezone}
          </Typography>
          {data.context.completeness.eligible_transaction_count === 0 && (
            <Alert severity="info">
              No eligible transactions in this period and currency. Add or
              import transactions to build your overview.
            </Alert>
          )}
          <Box
            sx={{
              display: "grid",
              gridTemplateColumns: {
                xs: "1fr",
                sm: "1fr 1fr",
                lg: "repeat(4, 1fr)",
              },
              gap: 2,
            }}
          >
            {(
              [
                ["Income", data.metrics.gross_income.value],
                ["Expenses", data.metrics.total_expense.value],
                ["Net cash flow", data.metrics.net_cash_flow.value],
                ["Savings", data.metrics.savings_amount.value],
              ] as const
            ).map(([label, amount]) => (
              <Paper key={label} sx={{ p: 2 }}>
                <Typography color="text.secondary">{label}</Typography>
                <Typography variant="h2" sx={{ overflowWrap: "anywhere" }}>
                  {money(amount, data.context.currency)}
                </Typography>
              </Paper>
            ))}
          </Box>
          <Paper sx={{ p: 2 }}>
            <Typography variant="h2">Cash-flow history</Typography>
            <TableContainer>
              <Table size="small" aria-label="Cash-flow history">
                <TableHead>
                  <TableRow>
                    {["Period", "Income", "Expenses", "Net cash flow"].map(
                      (label) => (
                        <TableCell key={label}>{label}</TableCell>
                      ),
                    )}
                  </TableRow>
                </TableHead>
                <TableBody>
                  {data.series.map((point) => (
                    <TableRow key={point.period_start}>
                      <TableCell>{point.period_start}</TableCell>
                      <TableCell>
                        {money(point.gross_income.value, data.context.currency)}
                      </TableCell>
                      <TableCell>
                        {money(
                          point.total_expense.value,
                          data.context.currency,
                        )}
                      </TableCell>
                      <TableCell>
                        {money(
                          point.net_cash_flow.value,
                          data.context.currency,
                        )}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableContainer>
            {data.series.length === 0 && (
              <Typography>No observed periods yet.</Typography>
            )}
          </Paper>
          <Paper sx={{ p: 2 }}>
            <Typography variant="h2">Spending by category</Typography>
            <Stack spacing={2} sx={{ mt: 2 }}>
              {data.spending.categories.map((category) => (
                <Box key={category.category_id}>
                  <Typography>
                    {category.name} ·{" "}
                    {money(category.amount.value, data.context.currency)}
                  </Typography>
                  <LinearProgress
                    aria-label={`${category.name} spending share`}
                    variant="determinate"
                    value={Math.min(
                      100,
                      Math.max(0, Number(category.share.value || 0) * 100),
                    )}
                  />
                </Box>
              ))}
            </Stack>
            {data.spending.categories.length === 0 && (
              <Typography>No categorized spending yet.</Typography>
            )}
          </Paper>
          <Typography variant="body2">
            Excluded:{" "}
            {data.context.completeness.exclusions.other_currency_count}{" "}
            other-currency entries,{" "}
            {data.context.completeness.exclusions.pending_count} pending
            entries, {data.context.completeness.exclusions.transfer_entry_count}{" "}
            transfer entries,{" "}
            {data.context.completeness.exclusions.adjustment_count} adjustments.
          </Typography>
        </>
      )}
      <Paper sx={{ p: 2 }}>
        <Typography variant="h2">Financial health</Typography>
        {health.isPending && <Typography>Loading health factors…</Typography>}
        {health.error && (
          <Alert severity="warning">{errorMessage(health.error)}</Alert>
        )}
        {health.data && (
          <>
            <Typography variant="h2">
              {health.data.score ?? "Unavailable"}{" "}
              {health.data.score != null ? "/ 100" : ""}
            </Typography>
            <Typography>
              {health.data.status} · {health.data.explanation}
            </Typography>
            {health.data.factors.map((factor) => (
              <Box key={factor.factor} sx={{ mt: 1 }}>
                <Typography sx={{ fontWeight: 600 }}>
                  {factor.factor.replaceAll("_", " ")}:{" "}
                  {factor.factor_score ?? "Unavailable"}
                </Typography>
                <Typography>{factor.explanation}</Typography>
              </Box>
            ))}
          </>
        )}
      </Paper>
      <Paper id="insights" sx={{ p: 2 }}>
        <Typography variant="h2">Prioritized insights</Typography>
        {insights.isPending && <Typography>Loading insights…</Typography>}
        {insights.error && (
          <Alert severity="warning">{errorMessage(insights.error)}</Alert>
        )}
        {insights.data && (
          <>
            <Typography>{insights.data.explanation}</Typography>
            {insights.data.insights.map((insight) => (
              <Box key={insight.insight_id} sx={{ mt: 2 }}>
                <Chip
                  label={`${insight.severity} · ${insight.confidence} confidence`}
                />
                <Typography variant="h3">{insight.title}</Typography>
                <Typography>{insight.explanation}</Typography>
                <Typography sx={{ fontWeight: 600 }}>
                  {insight.recommended_action}
                </Typography>
              </Box>
            ))}
          </>
        )}
      </Paper>
      <Typography variant="h2">Active goals</Typography>
      {goals.error && (
        <Alert severity="warning">{errorMessage(goals.error)}</Alert>
      )}
      {goals.data?.items.length === 0 && (
        <Typography>
          No active goals yet. Goal creation arrives with the Goals checkpoint.
        </Typography>
      )}
      {goals.data?.items.map((goal) => (
        <GoalCard key={goal.id} goal={goal} />
      ))}
    </Stack>
  );
}
