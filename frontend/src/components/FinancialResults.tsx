import type { ReactNode } from "react";
import {
  Alert,
  Button,
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
import { errorMessage, type Schema } from "../api/finance";
import { LoadingState } from "./States";

export const words = (value: string) => value.replaceAll("_", " ");

export function Result<T>({
  query,
  children,
}: {
  query: {
    isPending: boolean;
    error: unknown;
    data: T | undefined;
    refetch: () => unknown;
  };
  children: (data: T) => ReactNode;
}) {
  if (query.isPending) return <LoadingState />;
  if (query.error)
    return (
      <Alert severity="error">
        {errorMessage(query.error)}{" "}
        <Button
          onClick={() => {
            void query.refetch();
          }}
        >
          Retry loading
        </Button>
      </Alert>
    );
  return query.data === undefined ? (
    <Alert severity="info">No result available.</Alert>
  ) : (
    <>{children(query.data)}</>
  );
}

export function DataTable({
  title,
  headings,
  rows,
}: {
  title: string;
  headings: string[];
  rows: ReactNode[][];
}) {
  return (
    <TableContainer component={Paper} variant="outlined">
      <Table size="small" aria-label={title}>
        <caption>{title}</caption>
        <TableHead>
          <TableRow>
            {headings.map((h) => (
              <TableCell key={h} scope="col">
                {h}
              </TableCell>
            ))}
          </TableRow>
        </TableHead>
        <TableBody>
          {rows.length ? (
            rows.map((row, i) => (
              <TableRow key={i}>
                {row.map((cell, j) => (
                  <TableCell key={j}>{cell ?? "Unavailable"}</TableCell>
                ))}
              </TableRow>
            ))
          ) : (
            <TableRow>
              <TableCell colSpan={headings.length}>
                No records for this selection.
              </TableCell>
            </TableRow>
          )}
        </TableBody>
      </Table>
    </TableContainer>
  );
}

export function Evidence({ context }: { context: Schema<"AnalyticsContext"> }) {
  return (
    <Stack spacing={1}>
      <Typography>
        {context.currency} · {context.period.date_from} to{" "}
        {context.period.date_to} · {context.period.timezone}
      </Typography>
      <Typography variant="body2">
        Calculated {context.freshness.calculated_at} · Source updated{" "}
        {context.freshness.source_last_updated_at || "No source records"}
      </Typography>
      <Alert
        severity={
          context.completeness.data_confidence === "high" ? "info" : "warning"
        }
      >
        Data confidence: {context.completeness.data_confidence}.{" "}
        {context.completeness.eligible_transaction_count} eligible transactions.
        Classification coverage (ratio):{" "}
        {context.completeness.classification_coverage ?? "Unavailable"}. This is
        data coverage, not a prediction probability.
      </Alert>
      <Typography variant="body2">
        Excluded: {context.completeness.exclusions.other_currency_count}{" "}
        other-currency, {context.completeness.exclusions.pending_count} pending,{" "}
        {context.completeness.exclusions.transfer_entry_count} transfer entries,{" "}
        {context.completeness.exclusions.adjustment_count} adjustments.
      </Typography>
      {context.completeness.eligible_transaction_count === 0 && (
        <Alert severity="info">
          No eligible transactions in this period. Add or import records to
          build this analysis.
        </Alert>
      )}
    </Stack>
  );
}

export function Reasons({ items }: { items: readonly string[] }) {
  return items.length > 0 ? (
    <ul>
      {items.map((item, i) => (
        <li key={`${item}-${i}`}>{words(item)}</li>
      ))}
    </ul>
  ) : null;
}
