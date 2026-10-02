import { useState } from "react";
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
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
import { Form, currencyField, InputError, value } from "../components/Forms";
import {
  useResource,
  type Schema,
  localDate,
  money,
  errorMessage,
} from "../api/finance";
import { useSession } from "../auth/session";
import { LoadingState } from "../components/States";
import { FeatureIcon } from "../components/Brand";
import { CashFlowChart, SpendingDonut } from "../components/DashboardCharts";
import { ForecastChart } from "./Forecasts";
import { words } from "../components/FinancialResults";

const panel = { p: { xs: 2.5, sm: 3 }, minWidth: 0 };
function PanelTitle({
  kicker,
  title,
  to,
  action,
}: {
  kicker: string;
  title: string;
  to?: string;
  action?: string;
}) {
  return (
    <Stack
      direction="row"
      spacing={2}
      sx={{ alignItems: "center", justifyContent: "space-between", mb: 2 }}
    >
      <Box>
        <Typography
          variant="body2"
          color="text.secondary"
          sx={{
            mb: 0.5,
            fontSize: ".75rem",
            letterSpacing: ".08em",
            fontWeight: 650,
          }}
        >
          {kicker.toUpperCase()}
        </Typography>
        <Typography variant="h2">{title}</Typography>
      </Box>
      {to && (
        <Button component={Link} to={to} sx={{ flexShrink: 0 }}>
          {action || "View all"}
        </Button>
      )}
    </Stack>
  );
}
function GoalCard({ goal }: { goal: Schema<"GoalResponse"> }) {
  const progress = useResource<Schema<"GoalProgressResponse">>(
    `/goals/${goal.id}/progress`,
  );
  return (
    <Paper variant="outlined" sx={{ p: 2.5, bgcolor: "#f8f9f4", minWidth: 0 }}>
      <Stack direction="row" sx={{ justifyContent: "space-between", mb: 2 }}>
        <Box
          sx={{
            width: 36,
            height: 36,
            borderRadius: 2,
            bgcolor: "#e7f1ed",
            color: "primary.main",
            display: "grid",
            placeItems: "center",
          }}
        >
          <FeatureIcon name="goals" />
        </Box>
        <Chip size="small" label={`${goal.priority} priority`} />
      </Stack>
      <Typography variant="h3">{goal.name}</Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
        Target {money(goal.target_amount, goal.currency)} · {goal.target_date}
      </Typography>
      {progress.isPending && (
        <Typography variant="body2" sx={{ mt: 2 }}>
          Loading goal progress…
        </Typography>
      )}
      {progress.error && (
        <Alert severity="warning" sx={{ mt: 2 }}>
          Goal progress unavailable. {errorMessage(progress.error)}
        </Alert>
      )}
      {progress.data && (
        <>
          <Typography sx={{ mt: 2, mb: 1, fontWeight: 700 }}>
            {money(progress.data.current_amount, goal.currency)} saved
          </Typography>
          <LinearProgress
            aria-label={`${goal.name} funding`}
            variant="determinate"
            value={Math.min(
              100,
              Math.max(0, Number(progress.data.funding_percentage)),
            )}
          />
          <Stack
            direction="row"
            sx={{ justifyContent: "space-between", mt: 1, gap: 1 }}
          >
            <Typography variant="body2" color="text.secondary">
              {progress.data.funding_percentage}% funded
            </Typography>
            <Typography variant="body2" color="text.secondary">
              {words(progress.data.funding_state)}
            </Typography>
          </Stack>
        </>
      )}
      <Button
        component={Link}
        to="/app/goals"
        fullWidth
        variant="outlined"
        sx={{ mt: 2, borderColor: "divider" }}
      >
        Manage goal
      </Button>
    </Paper>
  );
}
function ForecastPreview({ currency }: { currency: string }) {
  const history = useResource<Schema<"ForecastRunListResponse">>(
    "/forecasts?limit=20",
  );
  const latest = history.data?.items.find((run) => run.currency === currency);
  const result = useResource<Schema<"ForecastRunResponse">>(
    `/forecasts/${latest?.id || "none"}`,
    !!latest,
  );
  return (
    <Paper sx={panel}>
      <PanelTitle
        kicker="Cognitive forecast"
        title="Your financial outlook"
        to="/app/forecasts"
        action="Forecasts"
      />
      {history.isPending && <LoadingState />}
      {history.error && (
        <Alert severity="warning">{errorMessage(history.error)}</Alert>
      )}
      {history.data && !latest && (
        <Box sx={{ py: 3 }}>
          <Typography variant="h3">
            Give your future a clearer shape.
          </Typography>
          <Typography color="text.secondary" sx={{ mt: 1, mb: 2 }}>
            Generate a forecast from your transaction history to explore income,
            expenses, cash flow or savings.
          </Typography>
          <Button component={Link} to="/app/forecasts" variant="contained">
            Create a forecast
          </Button>
          <Typography variant="body2" color="text.secondary" sx={{ mt: 2 }}>
            No {currency} forecast in your 20 most recent runs.
          </Typography>
        </Box>
      )}
      {latest && (
        <>
          <Stack
            direction="row"
            useFlexGap
            sx={{ flexWrap: "wrap", gap: 1, mb: 2 }}
          >
            <Chip label={words(latest.target)} />
            <Chip
              label={`${words(latest.uncertainty_reliability)} reliability`}
            />
          </Stack>
          <Typography variant="body2" color="text.secondary">
            Saved {latest.created_at.slice(0, 10)} · {latest.forecast_start} to{" "}
            {latest.forecast_end}
          </Typography>
          {result.isPending && <LoadingState />}
          {result.error && (
            <Alert severity="warning">{errorMessage(result.error)}</Alert>
          )}
          {result.data && <ForecastChart run={result.data} />}
          <Button
            component={Link}
            to={`/app/forecasts?run=${encodeURIComponent(latest.id)}`}
          >
            Review exact values and evidence
          </Button>
        </>
      )}
    </Paper>
  );
}
function RecentTransactions({
  period,
}: {
  period: { date_from: string; date_to: string; currency: string };
}) {
  const accounts = useResource<Schema<"AccountListResponse">>("/accounts");
  const transactions = useResource<Schema<"TransactionPageResponse">>(
    `/transactions?${new URLSearchParams({ date_from: period.date_from, date_to: period.date_to, limit: "5" })}`,
  );
  return (
    <Paper sx={panel}>
      <PanelTitle
        kicker="Latest activity"
        title="Recent transactions"
        to="/app/money?tab=transactions"
        action="View all"
      />
      <Typography variant="body2" color="text.secondary">
        Five most recent entries in this period across your accounts. Each uses
        its account currency.
      </Typography>
      {transactions.isPending && <LoadingState />}
      {transactions.error && (
        <Alert severity="warning">{errorMessage(transactions.error)}</Alert>
      )}
      {accounts.error && (
        <Alert severity="warning">
          Account currencies unavailable. {errorMessage(accounts.error)}
        </Alert>
      )}
      {transactions.data?.items.length === 0 && (
        <Typography color="text.secondary" sx={{ py: 3 }}>
          No transactions in this period. Add one or import a statement to get
          started.
        </Typography>
      )}
      {transactions.data?.items.map((t) => {
        const account = accounts.data?.items.find((a) => a.id === t.account_id);
        return (
          <Box
            key={t.id}
            sx={{
              display: "flex",
              gap: 2,
              alignItems: "center",
              py: 2,
              borderBottom: "1px solid",
              borderColor: "divider",
            }}
          >
            <Box
              sx={{
                display: { xs: "none", sm: "grid" },
                placeItems: "center",
                width: 36,
                height: 36,
                bgcolor: "#e7f1ed",
                color: "primary.main",
                borderRadius: 2,
                flexShrink: 0,
              }}
            >
              <FeatureIcon name="money" size={18} />
            </Box>
            <Box sx={{ flex: 1, minWidth: 0 }}>
              <Typography sx={{ fontWeight: 650, overflowWrap: "anywhere" }}>
                {t.merchant_name || t.description}
              </Typography>
              <Typography variant="body2" color="text.secondary">
                {t.transaction_date} · {words(t.transaction_type)} · {t.status}
              </Typography>
            </Box>
            <Typography
              variant="body2"
              sx={{
                fontWeight: 700,
                textAlign: "right",
                overflowWrap: "anywhere",
                maxWidth: "45%",
                color:
                  t.transaction_type === "income"
                    ? "primary.main"
                    : "text.primary",
              }}
            >
              {account
                ? money(t.amount, account.currency)
                : `${t.amount} · Currency unavailable`}
            </Typography>
          </Box>
        );
      })}
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
  const data = dashboard.data,
    best = insights.data?.insights[0],
    score = health.data?.score;
  return (
    <Stack spacing={2.5}>
      <Stack
        direction={{ xs: "column", lg: "row" }}
        spacing={2}
        sx={{ alignItems: { lg: "center" }, justifyContent: "space-between" }}
      >
        <Box>
          <Typography component="h1" variant="h1">
            Your financial overview
          </Typography>
          <Typography color="text.secondary" sx={{ mt: 0.5 }}>
            Your money today. Your possibilities for tomorrow.
          </Typography>
        </Box>
        <Stack direction="row" useFlexGap sx={{ flexWrap: "wrap", gap: 1 }}>
          <Button
            component={Link}
            to="/app/money?tab=transactions"
            variant="contained"
            startIcon={<FeatureIcon name="plus" size={18} />}
          >
            Add transaction
          </Button>
          <Button
            component={Link}
            to="/app/money?tab=imports"
            variant="outlined"
            startIcon={<FeatureIcon name="upload" size={18} />}
          >
            Import statement
          </Button>
        </Stack>
      </Stack>
      <Paper component="details" sx={{ px: 2.5, py: 1.5 }}>
        <Box
          component="summary"
          sx={{ display: "list-item", fontSize: ".875rem", fontWeight: 650 }}
        >
          <Box
            component="span"
            sx={{ display: "inline-flex", alignItems: "center", gap: 1, ml: 1 }}
          >
            <FeatureIcon name="calendar" size={18} />
            {period.date_from} – {period.date_to} · {period.currency} · Change
            period
          </Box>
        </Box>
        <Box sx={{ pt: 3, pb: 1 }}>
          <Form
            layout="inline"
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
              const date_from = value(form, "date_from"),
                date_to = value(form, "date_to");
              if (date_from > date_to)
                throw new InputError("From date must not be after To date.");
              setPeriod({
                date_from,
                date_to,
                currency: value(form, "currency").toUpperCase(),
              });
            }}
          />
        </Box>
      </Paper>
      <Box
        sx={{
          display: "grid",
          gridTemplateColumns: {
            xs: "1fr",
            lg: "minmax(0, 1.7fr) minmax(0, 1fr)",
          },
          gap: 2.5,
        }}
      >
        <Paper
          sx={{
            ...panel,
            bgcolor: "#204f45",
            color: "#fff",
            borderColor: "#204f45",
            display: "flex",
            flexDirection: { xs: "column", sm: "row" },
            gap: 3,
            alignItems: "center",
            minHeight: 270,
          }}
        >
          <Box sx={{ flex: 1, alignSelf: "stretch" }}>
            <Typography
              variant="body2"
              sx={{
                color: "#bed4cf",
                fontWeight: 650,
                letterSpacing: ".08em",
                mb: 2,
              }}
            >
              FINANCIAL HEALTH
            </Typography>
            <Typography
              variant="h2"
              sx={{
                fontSize: "1.8rem",
                lineHeight: 1.2,
                letterSpacing: "-.04em",
              }}
            >
              {health.data && score != null
                ? "See where you stand. Decide what comes next."
                : "A clearer picture starts with your records."}
            </Typography>
            {health.isPending && (
              <Typography sx={{ mt: 2 }}>Loading health factors…</Typography>
            )}
            {health.error && (
              <Alert severity="warning" sx={{ mt: 2 }}>
                {errorMessage(health.error)}
              </Alert>
            )}
            {health.data && (
              <Typography sx={{ mt: 2, color: "#d2e2dc" }}>
                {health.data.explanation}
              </Typography>
            )}
            <Stack
              direction="row"
              useFlexGap
              sx={{ flexWrap: "wrap", gap: 1, mt: 3 }}
            >
              <Button
                component={Link}
                to="/app/analytics?tab=health"
                sx={{
                  bgcolor: "#f4c76b",
                  color: "#173e36",
                  "&:hover": { bgcolor: "#e9b958" },
                }}
              >
                Review health factors
              </Button>
              <Button
                href="#insights"
                sx={{
                  color: "#fff",
                  border: "1px solid #6e9488",
                  "&:hover": { bgcolor: "#2b5a4f" },
                }}
              >
                View insights
              </Button>
            </Stack>
          </Box>
          <Box
            sx={{
              flexShrink: 0,
              position: "relative",
              width: 144,
              height: 144,
              display: "grid",
              placeItems: "center",
            }}
            role="img"
            aria-label={
              score == null
                ? "Financial health score unavailable"
                : `Financial health score ${score} out of 100`
            }
          >
          <CircularProgress
            aria-hidden="true"
            variant="determinate"
              value={100}
              size={144}
              thickness={3.5}
              sx={{ color: "#426c61", position: "absolute" }}
            />
          <CircularProgress
            aria-hidden="true"
            variant="determinate"
              value={
                score == null ? 0 : Math.max(0, Math.min(100, Number(score)))
              }
              size={144}
              thickness={3.5}
              sx={{ color: "#f4c76b", position: "absolute" }}
            />
            <Box sx={{ textAlign: "center" }}>
              <Typography
                sx={{
                  fontSize: score == null ? "1rem" : "2.5rem",
                  fontWeight: 750,
                  lineHeight: 1.15,
                }}
              >
                {score ?? "Unavailable"}
              </Typography>
              <Typography variant="body2" sx={{ color: "#bed4cf", mt: 0.5 }}>
                {score == null ? "More data needed" : "out of 100"}
              </Typography>
            </Box>
          </Box>
        </Paper>
        <Paper sx={{ ...panel, bgcolor: "#fff3e9", borderColor: "#eedfd1" }}>
          <Stack
            direction="row"
            spacing={1.5}
            sx={{ alignItems: "center", mb: 2 }}
          >
            <Box
              sx={{
                color: "#92521e",
                bgcolor: "#f5d4be",
                borderRadius: 2,
                p: 1,
                display: "grid",
              }}
            >
              <FeatureIcon name="spark" />
            </Box>
            <Typography
              variant="body2"
              sx={{ color: "#7d4824", letterSpacing: ".06em", fontWeight: 700 }}
            >
              YOUR NEXT STEP
            </Typography>
          </Stack>
          {insights.isPending && <Typography>Loading insights…</Typography>}
          {insights.error && (
            <Alert severity="warning">{errorMessage(insights.error)}</Alert>
          )}
          {best ? (
            <>
              <Typography variant="h2">{best.title}</Typography>
              <Typography sx={{ mt: 1, color: "#715640" }}>
                {best.recommended_action}
              </Typography>
              <Chip
                label={`${best.severity} · ${best.confidence} confidence`}
                sx={{ mt: 2, bgcolor: "#fffefa", color: "#7d4824" }}
              />
              <Button
                href="#insights"
                sx={{
                  display: "flex",
                  mt: 2,
                  color: "#7d4824",
                  px: 0,
                  justifyContent: "flex-start",
                }}
              >
                Review supporting evidence
              </Button>
            </>
          ) : (
            insights.data && (
              <>
                <Typography variant="h2">
                  Build a plan from your own data.
                </Typography>
                <Typography sx={{ mt: 1, color: "#715640" }}>
                  {insights.data.explanation}
                </Typography>
                <Button
                  component={Link}
                  to="/app/onboarding"
                  sx={{ mt: 2, color: "#7d4824" }}
                >
                  Complete setup
                </Button>
              </>
            )
          )}
        </Paper>
      </Box>
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
              gap: 1.5,
            }}
          >
            {(
              [
                ["Income", data.metrics.gross_income.value],
                ["Expenses", data.metrics.total_expense.value],
                ["Net cash flow", data.metrics.net_cash_flow.value],
                ["Savings", data.metrics.savings_amount.value],
              ] as const
            ).map(([label, amount], i) => (
              <Paper
                component="section"
                aria-label={`${label} summary`}
                key={label}
                sx={{
                  p: 2.5,
                  display: "flex",
                  gap: 1.5,
                  alignItems: "center",
                  minWidth: 0,
                }}
              >
                <Box
                  sx={{
                    display: "grid",
                    placeItems: "center",
                    width: 40,
                    height: 40,
                    flexShrink: 0,
                    borderRadius: 2,
                    bgcolor: ["#e7f1ed", "#fbede5", "#e8edf7", "#efeaf5"][i],
                    color: ["#23685b", "#92521e", "#48659a", "#786399"][i],
                  }}
                >
                  <FeatureIcon
                    name={["money", "money", "forecasts", "goals"][i]}
                  />
                </Box>
                <Box sx={{ minWidth: 0 }}>
                  <Typography variant="body2" color="text.secondary">
                    {label}
                  </Typography>
                  <Typography
                    sx={{
                      fontSize: "1.4rem",
                      fontWeight: 750,
                      letterSpacing: "-.035em",
                      fontVariantNumeric: "tabular-nums",
                      overflowWrap: "anywhere",
                    }}
                  >
                    {money(amount, data.context.currency)}
                  </Typography>
                  <Typography variant="body2" color="text.secondary">
                    Selected period
                  </Typography>
                </Box>
              </Paper>
            ))}
          </Box>
          <Box
            sx={{
              display: "grid",
              gridTemplateColumns: {
                xs: "1fr",
                lg: "minmax(0, 1.7fr) minmax(0, 1fr)",
              },
              gap: 2.5,
            }}
          >
            <Paper sx={panel}>
              <PanelTitle
                kicker="Cash flow"
                title="Income and spending over time"
                to="/app/analytics"
                action="Explore"
              />
              <CashFlowChart data={data} />
              <Box component="details" sx={{ mt: 2 }}>
                <Box
                  component="summary"
                  sx={{ fontWeight: 650, fontSize: ".875rem", py: 1 }}
                >
                  View exact cash-flow history
                </Box>
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
                      {data.series.map((p) => (
                        <TableRow key={p.period_start}>
                          <TableCell>{p.period_start}</TableCell>
                          <TableCell>
                            {money(p.gross_income.value, data.context.currency)}
                          </TableCell>
                          <TableCell>
                            {money(
                              p.total_expense.value,
                              data.context.currency,
                            )}
                          </TableCell>
                          <TableCell>
                            {money(
                              p.net_cash_flow.value,
                              data.context.currency,
                            )}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </TableContainer>
              </Box>
            </Paper>
            <Paper sx={panel}>
              <PanelTitle
                kicker="Selected period"
                title="Where your money went"
                to="/app/analytics?tab=spending"
                action="Details"
              />
              <SpendingDonut data={data} />
              {data.spending.categories.length === 0 && (
                <Typography color="text.secondary" sx={{ py: 3 }}>
                  No categorized spending yet.
                </Typography>
              )}
            </Paper>
          </Box>
          <Paper component="details" sx={{ px: 2.5, py: 1.5 }}>
            <Box
              component="summary"
              sx={{ fontWeight: 650, fontSize: ".875rem" }}
            >
              Data coverage · {data.context.completeness.data_confidence}{" "}
              confidence ·{" "}
              {data.context.completeness.eligible_transaction_count} eligible
              transactions
            </Box>
            <Typography variant="body2" sx={{ mt: 2 }}>
              Calculated {data.context.freshness.calculated_at} · Source updated{" "}
              {data.context.freshness.source_last_updated_at ||
                "No transactions yet"}{" "}
              · {data.context.period.timezone}
            </Typography>
            <Typography variant="body2" sx={{ mt: 1 }}>
              Excluded:{" "}
              {data.context.completeness.exclusions.other_currency_count}{" "}
              other-currency entries,{" "}
              {data.context.completeness.exclusions.pending_count} pending
              entries,{" "}
              {data.context.completeness.exclusions.transfer_entry_count}{" "}
              transfer entries,{" "}
              {data.context.completeness.exclusions.adjustment_count}{" "}
              adjustments.
            </Typography>
          </Paper>
        </>
      )}
      <Paper sx={panel}>
        <PanelTitle
          kicker="Your plan"
          title="Active goals"
          to="/app/goals"
          action="View all goals"
        />
        {goals.isPending && <LoadingState />}
        {goals.error && (
          <Alert severity="warning">{errorMessage(goals.error)}</Alert>
        )}
        {goals.data?.items.length === 0 && (
          <Typography color="text.secondary">
            No active goals yet.{" "}
            <Link to="/app/goals">Create your first goal.</Link>
          </Typography>
        )}
        <Box
          sx={{
            display: "grid",
            gridTemplateColumns: {
              xs: "1fr",
              sm: "1fr 1fr",
              lg: "repeat(3, 1fr)",
            },
            gap: 2,
          }}
        >
          {goals.data?.items.map((goal) => (
            <GoalCard key={goal.id} goal={goal} />
          ))}
        </Box>
      </Paper>
      <Box
        sx={{
          display: "grid",
          gridTemplateColumns: {
            xs: "1fr",
            lg: "minmax(0, 1.7fr) minmax(0, 1fr)",
          },
          gap: 2.5,
        }}
      >
        <ForecastPreview currency={period.currency} />
        <Paper sx={{ ...panel, bgcolor: "#eaf2ef", borderColor: "#d6e4df" }}>
          <Box
            sx={{
              display: "grid",
              placeItems: "center",
              width: 52,
              height: 52,
              bgcolor: "primary.main",
              color: "#f4c76b",
              borderRadius: 2,
              mb: 3,
            }}
          >
            <FeatureIcon name="reports" size={28} />
          </Box>
          <Typography variant="h2">Your month, in perspective.</Typography>
          <Typography color="text.secondary" sx={{ mt: 1, mb: 3 }}>
            Review a completed month’s cash flow and spending with a PDF report,
            or export transactions to CSV.
          </Typography>
          <Button component={Link} to="/app/reports" variant="contained">
            Open monthly report
          </Button>
          <Button
            component={Link}
            to="/app/scenarios"
            sx={{ display: "flex", mt: 1 }}
          >
            Explore a what-if scenario
          </Button>
        </Paper>
      </Box>
      <RecentTransactions period={period} />
      <Paper id="insights" sx={{ ...panel, scrollMarginTop: 100 }}>
        <PanelTitle
          kicker="Evidence-based guidance"
          title="Prioritized insights"
          to="/app/analytics?tab=insights"
          action="View all"
        />
        {insights.isPending && <Typography>Loading insights…</Typography>}
        {insights.error && (
          <Alert severity="warning">{errorMessage(insights.error)}</Alert>
        )}
        {insights.data && (
          <>
            <Typography color="text.secondary">
              {insights.data.explanation}
            </Typography>
            {insights.data.insights.map((insight) => (
              <Box
                key={insight.insight_id}
                sx={{
                  mt: 2,
                  pt: 2,
                  borderTop: "1px solid",
                  borderColor: "divider",
                }}
              >
                <Chip
                  label={`${insight.severity} · ${insight.confidence} confidence`}
                />
                <Typography variant="h3" sx={{ mt: 1 }}>
                  {insight.title}
                </Typography>
                <Typography color="text.secondary">
                  {insight.explanation}
                </Typography>
                <Typography sx={{ fontWeight: 650, mt: 1 }}>
                  {insight.recommended_action}
                </Typography>
              </Box>
            ))}
          </>
        )}
        <Box component="details" sx={{ mt: 3 }}>
          <Box
            component="summary"
            sx={{ fontSize: ".875rem", fontWeight: 650 }}
          >
            View health factors
          </Box>
          {health.data?.factors.map((f) => (
            <Box key={f.factor} sx={{ mt: 2 }}>
              <Typography sx={{ fontWeight: 650 }}>
                {words(f.factor)}: {f.factor_score ?? "Unavailable"}
              </Typography>
              <Typography color="text.secondary">{f.explanation}</Typography>
            </Box>
          ))}
        </Box>
      </Paper>
    </Stack>
  );
}
