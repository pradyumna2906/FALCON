import { useState } from "react";
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
import { Link } from "react-router";
import { Form, InputError, value } from "../../components/Forms";
import {
  useResource,
  useFinanceMutation,
  type Schema,
  errorMessage,
} from "../../api/finance";
import { LoadingState } from "../../components/States";

function Receipt({ id }: { id: string }) {
  const job = useResource<Schema<"ImportJobResponse">>(`/imports/${id}`);
  if (job.isPending) return <LoadingState />;
  if (job.error)
    return <Alert severity="error">{errorMessage(job.error)}</Alert>;
  const item = job.data;
  if (!item) return null;
  return (
    <Paper sx={{ p: 2 }}>
      <Typography variant="h2">
        Import result: {item.original_filename}
      </Typography>
      <Typography>
        Status: {item.status} · Accepted {item.accepted_count} · Rejected{" "}
        {item.rejected_count}
      </Typography>
      {item.balance_reconciled !== null && (
        <Typography>
          Statement balance reconciled: {item.balance_reconciled ? "Yes" : "No"}
        </Typography>
      )}
      <TableContainer>
        <Table size="small" aria-label="Import row issues">
          <TableHead>
            <TableRow>
              <TableCell>Row</TableCell>
              <TableCell>Code</TableCell>
              <TableCell>Issue</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {item.issues.map((issue, index) => (
              <TableRow key={`${issue.row_number}-${index}`}>
                <TableCell>{issue.row_number}</TableCell>
                <TableCell>{issue.code}</TableCell>
                <TableCell>{issue.message}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableContainer>
      {item.issues_truncated && (
        <Alert severity="warning">
          Only the first bounded set of issues is shown.
        </Alert>
      )}
      <Button
        onClick={() => {
          void job.refetch();
        }}
      >
        Refresh status
      </Button>
      <Button component={Link} to="/app/money?tab=transactions">
        Review imported transactions
      </Button>
    </Paper>
  );
}

export default function Imports() {
  const accounts = useResource<Schema<"AccountListResponse">>("/accounts");
  const [offset, setOffset] = useState(0);
  const history = useResource<Schema<"ImportHistoryResponse">>(
    `/imports?limit=10&offset=${offset}`,
  );
  const [selected, setSelected] = useState("");
  const [draft, setDraft] = useState<FormData | null>(null);
  const [revision, setRevision] = useState(0);
  const [file, setFile] = useState<File | null>(null);
  const mutate = useFinanceMutation();
  const options =
    accounts.data?.items.map((a) => ({
      value: a.id,
      label: `${a.name} (${a.currency})`,
    })) || [];
  return (
    <Stack spacing={3}>
      <Alert severity="info">
        CSV, XLSX and supported digital bank-statement PDFs. Scanned PDFs/OCR
        are not supported. Check account currency and date order before
        importing. Duplicate statements are rejected.
      </Alert>
      {accounts.error && (
        <Alert severity="error">{errorMessage(accounts.error)}</Alert>
      )}
      {!draft && options.length > 0 && (
        <Paper sx={{ p: 3 }}>
          <Form
            key={revision}
            title="1. Select statement"
            submit="Review import"
            fields={[
              {
                name: "account_id",
                label: "Import account",
                options,
                required: true,
              },
              {
                name: "source_type",
                label: "File format",
                required: true,
                value: "csv",
                options: [
                  { value: "csv", label: "CSV" },
                  { value: "excel", label: "Excel (.xlsx)" },
                  {
                    value: "bank_statement",
                    label: "Digital bank statement (.pdf)",
                  },
                ],
              },
              {
                name: "date_order",
                label: "Date order",
                required: true,
                value: "day_first",
                options: ["day_first", "month_first", "year_first"],
              },
              {
                name: "header_row",
                label: "Header row",
                type: "number",
                min: "1",
                max: "50",
                value: "1",
                required: true,
              },
              {
                name: "sheet_name",
                label: "Worksheet name (Excel only)",
                maxLength: 31,
              },
              {
                name: "file_password",
                label: "PDF password (optional; used only for this import)",
                type: "password",
                maxLength: 128,
              },
            ]}
            onSubmit={async (data) => {
              if (!(file instanceof File) || file.size === 0)
                throw new InputError("Choose a nonempty statement file.");
              if (file.size > 10 * 1024 * 1024)
                throw new InputError("Choose a file no larger than 10 MiB.");
              const extension =
                value(data, "source_type") === "csv"
                  ? ".csv"
                  : value(data, "source_type") === "excel"
                    ? ".xlsx"
                    : ".pdf";
              if (!file.name.toLowerCase().endsWith(extension))
                throw new InputError(
                  "The file extension must match the selected format.",
                );
              if (!value(data, "sheet_name")) data.delete("sheet_name");
              if (!String(data.get("file_password") || ""))
                data.delete("file_password");
              data.set("file", file);
              setDraft(data);
            }}
          >
            <label htmlFor="statement-file">Statement file</label>
            <input
              id="statement-file"
              name="file"
              type="file"
              onChange={event => setFile(event.currentTarget.files?.[0] || null)}
              accept=".csv,.xlsx,.pdf"
              required
            />
          </Form>
        </Paper>
      )}
      {accounts.data?.items.length === 0 && (
        <Alert severity="info">
          Create an active account before importing.
        </Alert>
      )}
      {draft && (
        <Paper sx={{ p: 3 }}>
          <Typography>
            Review: {(draft.get("file") as File).name} ·{" "}
            {options.find((a) => a.value === draft.get("account_id"))?.label} ·{" "}
            {value(draft, "date_order")}
          </Typography>
          <Typography>
            The server validates rows and reports rejected records. No financial
            data is saved until you confirm.
          </Typography>
          <Form
            title="2. Confirm import"
            submit="Import statement"
            fields={[]}
            onSubmit={async () => {
              const result = await mutate<Schema<"ImportJobResponse">>(
                "/imports",
                "POST",
                draft,
              );
              setSelected(result.id);
              setDraft(null);
              setFile(null);
              setRevision((r) => r + 1);
              setOffset(0);
            }}
          />
          <Button onClick={() => { setDraft(null); setFile(null); }}>Cancel and clear file</Button>
        </Paper>
      )}
      {selected && <Receipt key={selected} id={selected} />}
      <Typography variant="h2">Import history</Typography>
      {history.isPending && <LoadingState />}
      {history.error && (
        <Alert severity="error">{errorMessage(history.error)}</Alert>
      )}
      {history.data?.items.length === 0 && (
        <Typography>No statement imports yet.</Typography>
      )}
      {history.data?.items.map((job) => (
        <Paper key={job.id} sx={{ p: 2 }}>
          <Typography>
            {job.original_filename} · {job.status} · {job.accepted_count}{" "}
            accepted / {job.rejected_count} rejected
          </Typography>
          <Typography variant="body2">{job.created_at}</Typography>
          <Button onClick={() => setSelected(job.id)}>
            View import issues
          </Button>
        </Paper>
      ))}
      <Stack direction="row">
        <Button
          disabled={offset === 0}
          onClick={() => setOffset(Math.max(0, offset - 10))}
        >
          Previous imports
        </Button>
        <Button
          disabled={
            !history.data?.has_more || offset >= 10000 || history.isFetching
          }
          onClick={() => setOffset(offset + 10)}
        >
          Next imports
        </Button>
      </Stack>
    </Stack>
  );
}
