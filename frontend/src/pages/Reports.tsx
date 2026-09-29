import { Stack, Typography, Alert } from "@mui/material";
import { api } from "../api/client";
import { useSession } from "../auth/session";
import { Form, currencyField, value } from "../components/Forms";

export async function saveDownload(path: string, name: string, body?: unknown) {
  const blob = await api.request<Blob>(
    path,
    body === undefined ? {} : { method: "POST", body: JSON.stringify(body) },
    true,
    true,
  );
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = name;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export default function Reports() {
  const { user } = useSession();
  return (
    <Stack spacing={3}>
      <Typography variant="h1">Reports</Typography>
      <Alert severity="info">
        Download a monthly cash-flow PDF or the month's transaction CSV in one
        currency. The PDF includes data confidence and exclusions. CSV includes
        transaction statuses and types, with spreadsheet formula protection.
        Choose a completed month for the PDF.
      </Alert>
      <Form
        title="Download financial report"
        fields={[
          {
            name: "month",
            label: "Report month",
            type: "month",
            required: true,
          },
          { ...currencyField, value: user?.default_currency || "INR" },
          {
            name: "format",
            label: "Format",
            required: true,
            value: "pdf",
            options: [
              { value: "pdf", label: "Monthly PDF" },
              { value: "csv", label: "Transaction CSV" },
            ],
          },
        ]}
        submit="Download report"
        onSubmit={async (data) => {
          const format = value(data, "format"),
            month = value(data, "month"),
            currency = value(data, "currency");
          await saveDownload(
            `/reports/${format === "pdf" ? "monthly.pdf" : "transactions.csv"}?${new URLSearchParams({ month, currency })}`,
            `falcon-${month}-${currency}.${format}`,
          );
        }}
      />
    </Stack>
  );
}
