import { Box, Stack, Typography } from "@mui/material";
import type { Schema } from "../api/finance";
import { money } from "../api/finance";

export const chartColors = [
  "#23685b",
  "#b95a33",
  "#48659a",
  "#9b5873",
  "#8c783c",
  "#786399",
];

// Numbers are used only for chart geometry. Exact decimal amounts are displayed
// from the API in the accompanying labels and tables, never recomputed as advice.
export function CashFlowChart({
  data,
}: {
  data: Schema<"AnalyticsDashboardResponse">;
}) {
  const points = data.series;
  if (!points.length)
    return (
      <Typography color="text.secondary" sx={{ py: 4 }}>
        No observed periods yet. Add transactions to see your cash-flow trend.
      </Typography>
    );
  const values = points.flatMap((p) =>
    [p.gross_income.value, p.total_expense.value, p.net_cash_flow.value].map(
      Number,
    ),
  );
  if (values.some((n) => !Number.isFinite(n)))
    return (
      <Typography>Chart unavailable. Review the exact values below.</Typography>
    );
  const low = Math.min(0, ...values),
    high = Math.max(0, ...values),
    range = high - low || 1;
  const x = (i: number) =>
    55 + (points.length === 1 ? 265 : (i * 530) / (points.length - 1));
  const y = (n: number) => 185 - ((n - low) / range) * 155;
  const lines = [
    ["gross_income", "Income", "#23685b", ""],
    ["total_expense", "Expenses", "#b95a33", "5 5"],
    ["net_cash_flow", "Net cash flow", "#48659a", "2 4"],
  ] as const;
  return (
    <Box sx={{ mt: 2 }}>
      <svg
        viewBox="0 0 620 220"
        role="img"
        aria-label="Observed income, expenses and net cash flow; exact amounts in Cash-flow history"
        style={{ width: "100%", display: "block" }}
      >
        {[0, 0.5, 1].map((t) => (
          <g key={t}>
            <line
              x1="55"
              x2="585"
              y1={y(low + range * t)}
              y2={y(low + range * t)}
              stroke="#e2e7e1"
            />
            <text
              x="48"
              y={y(low + range * t) + 4}
              textAnchor="end"
              fontSize="12"
              fill="#52665f"
            >
              {new Intl.NumberFormat("en", {
                notation: "compact",
                maximumFractionDigits: 1,
              }).format(low + range * t)}
            </text>
          </g>
        ))}
        {lines.map(([key, label, color, dash]) => (
          <g key={key}>
            <polyline
              points={points
                .map((p, i) => `${x(i)},${y(Number(p[key].value))}`)
                .join(" ")}
              fill="none"
              stroke={color}
              strokeWidth="2.5"
              strokeDasharray={dash}
              strokeLinejoin="round"
            />
            {points.map((p, i) => (
              <circle
                key={p.period_start}
                cx={x(i)}
                cy={y(Number(p[key].value))}
                r="3.5"
                fill="#fffefa"
                stroke={color}
                strokeWidth="2"
              >
                <title>
                  {label} · {p.period_start}:{" "}
                  {money(p[key].value, data.context.currency)}
                </title>
              </circle>
            ))}
          </g>
        ))}
        <text x="55" y="212" fontSize="12" fill="#52665f">
          {points[0].period_start}
        </text>
        <text x="585" y="212" textAnchor="end" fontSize="12" fill="#52665f">
          {points.length > 1 ? points.at(-1)?.period_start : ""}
        </text>
      </svg>
      <Stack
        direction="row"
        spacing={2}
        useFlexGap
        sx={{ flexWrap: "wrap", justifyContent: "center", my: 1 }}
      >
        {lines.map(([, label, color, dash]) => (
          <Stack
            key={label}
            direction="row"
            spacing={0.7}
            sx={{ alignItems: "center" }}
          >
            <Box
              sx={{
                width: 18,
                borderTop: `3px ${dash ? "dashed" : "solid"} ${color}`,
              }}
            />
            <Typography variant="body2" color="text.secondary">
              {label}
            </Typography>
          </Stack>
        ))}
      </Stack>
      <Typography variant="body2" color="text.secondary">
        {data.context.currency} · Observed history · Approximate chart scale
      </Typography>
    </Box>
  );
}

export function SpendingDonut({
  data,
}: {
  data: Schema<"AnalyticsDashboardResponse">;
}) {
  const categories = data.spending.categories;
  const shares = categories.map((c) => Number(c.share.value || 0));
  if (!categories.length) return null;
  const valid =
    !shares.some((n) => !Number.isFinite(n) || n < 0 || n > 1) &&
    shares.reduce((a, b) => a + b, 0) <= 1.001;
  const radius = 62,
    circumference = 2 * Math.PI * radius;

  return (
    <Box
      sx={{
        display: "grid",
        gridTemplateColumns: {
          xs: "1fr",
          sm: "180px minmax(0, 1fr)",
          lg: "1fr",
        },
        gap: 2,
        alignItems: "center",
        mt: 2,
      }}
    >
      {valid && (
        <Box
          sx={{
            maxWidth: 200,
            width: "100%",
            mx: "auto",
            position: "relative",
          }}
        >
          <svg
            viewBox="0 0 180 180"
            role="img"
            aria-label="Spending distribution using server-provided category shares; exact amounts in the category list"
            style={{ width: "100%", display: "block" }}
          >
            <circle
              cx="90"
              cy="90"
              r={radius}
              fill="none"
              stroke="#e8ece5"
              strokeWidth="22"
            />
            {categories.map((c, i) => {
              const start =
                shares.slice(0, i).reduce((a, b) => a + b, 0) * circumference;
              return (
                <circle
                  key={c.category_id}
                  cx="90"
                  cy="90"
                  r={radius}
                  fill="none"
                  stroke={chartColors[i % chartColors.length]}
                  strokeWidth="22"
                  strokeDasharray={`${shares[i] * circumference} ${circumference}`}
                  strokeDashoffset={-start}
                  transform="rotate(-90 90 90)"
                >
                  <title>
                    {c.name}: {money(c.amount.value, data.context.currency)} ·{" "}
                    {c.share.value} share
                  </title>
                </circle>
              );
            })}
          </svg>
          <Box
            sx={{
              position: "absolute",
              inset: "30% 19%",
              textAlign: "center",
              display: "grid",
              alignContent: "center",
            }}
          >
            <Typography variant="body2" color="text.secondary">
              Spending
            </Typography>
            <Typography sx={{ fontWeight: 700 }}>
              {data.context.currency}
            </Typography>
            <Typography variant="body2" color="text.secondary">
              By category
            </Typography>
          </Box>
        </Box>
      )}
      <Stack spacing={1.5}>
        {categories.map((c, i) => (
          <Box
            key={c.category_id}
            sx={{
              display: "grid",
              gridTemplateColumns: "10px minmax(0, 1fr) auto",
              gap: 1,
              alignItems: "center",
            }}
          >
            <Box
              sx={{
                width: 8,
                height: 8,
                bgcolor: chartColors[i % chartColors.length],
                borderRadius: 10,
              }}
            />
            <Typography variant="body2">{c.name}</Typography>
            <Typography
              variant="body2"
              sx={{ fontWeight: 700, overflowWrap: "anywhere" }}
            >
              {money(c.amount.value, data.context.currency)}
            </Typography>
          </Box>
        ))}
      </Stack>
    </Box>
  );
}
