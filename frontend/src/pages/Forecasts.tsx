import { Alert, Box, Button, Paper, Stack, Typography } from "@mui/material";
import { useSearchParams } from "react-router";
import { useSession } from "../auth/session";
import {
  useFinanceMutation,
  useResource,
  money,
  localDate,
  type Schema,
} from "../api/finance";
import { Form, currencyField, InputError, value } from "../components/Forms";
import { DataTable, Result, words } from "../components/FinancialResults";

// Floating-point conversion is confined to SVG positioning. Exact values stay
// in the accessible table and are never used for client-side financial advice.
export function ForecastChart({ run }: { run: Schema<"ForecastRunResponse"> }) {
  const points = run.points;
  if (!points.length)
    return <Alert severity="info">This run contains no forecast points.</Alert>;
  const values = points.flatMap((p) =>
    [p.lower_95, p.upper_95, p.expected_value].map(Number),
  );
  if (values.some((v) => !Number.isFinite(v)))
    return (
      <Alert severity="warning">
        Chart unavailable. Review the exact values below.
      </Alert>
    );
  const low = Math.min(...values),
    high = Math.max(...values);
  const x = (i: number) =>
    55 + (points.length === 1 ? 300 : (i * 600) / (points.length - 1));
  const y = (n: string) => 230 - ((Number(n) - low) / (high - low || 1)) * 190;
  const band = (
    lower: "lower_80" | "lower_95",
    upper: "upper_80" | "upper_95",
  ) =>
    [
      ...points.map((p, i) => `${x(i)},${y(p[upper])}`),
      ...points.map((p, i) => `${x(i)},${y(p[lower])}`).reverse(),
    ].join(" ");
  return (
    <Box>
      <svg
        viewBox="0 0 710 275"
        role="img"
        aria-label={`${words(run.target)} expected forecast with 80% and 95% prediction intervals; exact values in the table below`}
        style={{ width: "100%", maxHeight: 360 }}
      >
        <polygon points={band("lower_95", "upper_95")} fill="#dbeafe" />
        <polygon points={band("lower_80", "upper_80")} fill="#93c5fd" />
        <polyline
          points={points
            .map((p, i) => `${x(i)},${y(p.expected_value)}`)
            .join(" ")}
          fill="none"
          stroke="#1565c0"
          strokeWidth="3"
        />
        {points.map((p, i) => (
          <circle
            key={p.step}
            cx={x(i)}
            cy={y(p.expected_value)}
            r="3"
            fill="#102a43"
          >
            <title>
              {p.period_start}: {money(p.expected_value, run.currency)}
            </title>
          </circle>
        ))}
        <text x="55" y="20" fontSize="12">
          {run.currency} · approximate chart scale
        </text>
        <text x="55" y="255" fontSize="12">
          {points[0].period_start}
        </text>
        <text x="655" y="255" textAnchor="end" fontSize="12">
          {points.at(-1)?.period_start}
        </text>
      </svg>
      <Typography variant="body2">
        Dark line: expected · blue band: 80% · pale band: 95%. Prediction
        intervals are estimates, not guarantees.
      </Typography>
    </Box>
  );
}

export function ForecastDetail({ id }: { id: string }) {
  const query = useResource<Schema<"ForecastRunResponse">>(
    `/forecasts/${encodeURIComponent(id)}`,
  );
  return (
    <Result query={query}>
      {(run) => (
        <Stack spacing={2}>
          <Typography variant="h2">Forecast result</Typography>
          <Typography>
            {words(run.target)} · {run.currency} · {run.forecast_start} to{" "}
            {run.forecast_end}
          </Typography>
          <Typography variant="body2" sx={{ overflowWrap: "anywhere" }}>
            Immutable run {run.id} · Created {run.created_at} · Data cutoff{" "}
            {run.data_cutoff_at}
          </Typography>
          <Alert
            severity={
              run.uncertainty_reliability === "normal" ? "info" : "warning"
            }
          >
            Reliability: {words(run.uncertainty_reliability)}. Short or sparse
            history can produce provisional estimates. These bands do not
            guarantee future results.
          </Alert>
          <Typography>
            Selected model: {run.model_code} ({run.model_version}). Selection
            metric: {words(run.selection_metric)}. Uncertainty:{" "}
            {words(run.uncertainty_method)}.
          </Typography>
          <Typography>
            History: {run.history_start} to {run.history_end} ·{" "}
            {run.granularity} · {run.horizon} forecast periods
          </Typography>
          <ForecastChart run={run} />
          <DataTable
            title="Exact forecast values"
            headings={[
              "Period",
              `Expected (${run.currency})`,
              "80% lower",
              "80% upper",
              "95% lower",
              "95% upper",
            ]}
            rows={run.points.map((p) => [
              p.period_start,
              p.expected_value,
              p.lower_80,
              p.upper_80,
              p.lower_95,
              p.upper_95,
            ])}
          />
          <DataTable
            title="Model evaluation"
            headings={["Split", "MAE", "RMSE", "Bias", "WAPE (ratio)"]}
            rows={[
              [
                "Validation",
                run.validation_mae,
                run.validation_rmse,
                run.validation_bias,
                run.validation_wape,
              ],
              [
                "Test",
                run.test_mae,
                run.test_rmse,
                run.test_bias,
                run.test_wape,
              ],
            ]}
          />
          <Typography variant="body2">
            Error amounts use {run.currency}; WAPE is unavailable when no valid
            denominator exists. Source last updated:{" "}
            {run.source_last_updated_at || "Unavailable"}.
          </Typography>
        </Stack>
      )}
    </Result>
  );
}

export default function Forecasts() {
  const { user } = useSession();
  const [params, setParams] = useSearchParams();
  const id = params.get("run");
  const history = useResource<Schema<"ForecastRunListResponse">>(
    "/forecasts?limit=20",
  );
  const mutate = useFinanceMutation();
  return (
    <Stack spacing={3}>
      <Typography component="h1" variant="h1">
        Forecasts
      </Typography>
      <Alert severity="info">
        Generate from your stored transaction history. Select completed history
        periods; insufficient history is rejected by the server. More history
        enables stronger evaluation. Generating a run may take time; do not
        resubmit while it is running.
      </Alert>
      <Paper sx={{ p: 3 }}>
        <Form
          title="Generate forecast"
          submit="Generate forecast"
          fields={[
            {
              name: "target",
              label: "Forecast target",
              required: true,
              value: "savings_amount",
              options: [
                { value: "gross_income", label: "Income" },
                { value: "total_expense", label: "Expenses" },
                { value: "net_cash_flow", label: "Cash flow" },
                { value: "savings_amount", label: "Savings" },
              ],
            },
            { ...currencyField, value: user?.default_currency || "INR" },
            {
              name: "granularity",
              label: "Period size",
              required: true,
              value: "month",
              options: ["day", "month"],
            },
            {
              name: "history_start",
              label: "History start",
              type: "date",
              required: true,
            },
            {
              name: "history_end",
              label: "History end",
              type: "date",
              required: true,
              max: localDate(user?.timezone),
            },
            {
              name: "horizon",
              label: "Forecast periods",
              type: "number",
              required: true,
              value: "6",
              min: "1",
              max: "366",
              help: "Maximum 24 monthly periods or 366 daily periods.",
            },
          ]}
          onSubmit={async (data) => {
            if (value(data, "history_start") > value(data, "history_end"))
              throw new InputError(
                "History start must not be after history end.",
              );
            if (
              value(data, "granularity") === "month" &&
              Number(value(data, "horizon")) > 24
            )
              throw new InputError(
                "Monthly forecasts support up to 24 periods.",
              );
            const payload = {
              target: value(data, "target") as Schema<"ForecastTarget">,
              currency: value(data, "currency").toUpperCase(),
              granularity: value(
                data,
                "granularity",
              ) as Schema<"ForecastGranularity">,
              history_start: value(data, "history_start"),
              history_end: value(data, "history_end"),
              horizon: Number(value(data, "horizon")),
            } satisfies Schema<"ForecastGenerationRequest">;
            const run = await mutate<Schema<"ForecastRunResponse">>(
              "/forecasts",
              "POST",
              payload,
            );
            setParams({ run: run.id });
          }}
        />
      </Paper>
      <Typography variant="h2">Recent forecasts</Typography>
      <Result query={history}>
        {(data) => (
          <>
            <Typography variant="body2">
              Up to 20 most recent runs. Every run retains its original
              evidence.
            </Typography>
            <DataTable
              title="Forecast history"
              headings={[
                "Created",
                "Target",
                "Currency",
                "Model",
                "Reliability",
                "Open",
              ]}
              rows={data.items.map((run) => [
                run.created_at,
                words(run.target),
                run.currency,
                run.model_code,
                words(run.uncertainty_reliability),
                <Button onClick={() => setParams({ run: run.id })}>
                  View forecast {run.id.slice(0, 8)}
                </Button>,
              ])}
            />
          </>
        )}
      </Result>
      {id && (
        <Paper sx={{ p: 3 }}>
          <ForecastDetail key={id} id={id} />
        </Paper>
      )}
    </Stack>
  );
}
