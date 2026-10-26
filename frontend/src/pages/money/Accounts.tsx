import { useState } from "react";
import { Alert, Button, Paper, Stack, Typography } from "@mui/material";
import { useSession } from "../../auth/session";
import {
  Form,
  amountField,
  currencyField,
  optional,
  value,
  type Field,
} from "../../components/Forms";
import { ConfirmAction } from "../../components/ConfirmAction";
import { LoadingState } from "../../components/States";
import { ApiError } from "../../api/client";
import {
  useResource,
  useFinanceMutation,
  type Schema,
  errorMessage,
  localDate,
  money,
} from "../../api/finance";

const types: Schema<"AccountType">[] = [
  "bank",
  "cash",
  "wallet",
  "credit_card",
  "investment",
  "loan",
];
const metadata: Field[] = [
  { name: "name", label: "Account name", required: true, maxLength: 120 },
  { name: "institution_name", label: "Institution", maxLength: 160 },
  {
    name: "masked_reference",
    label: "Masked reference (last digits only)",
    maxLength: 64,
  },
];

function Liability({ account }: { account: Schema<"AccountResponse"> }) {
  const existing = useResource<Schema<"LiabilityResponse">>(
    `/accounts/${account.id}/liability`,
  );
  const mutate = useFinanceMutation();
  if (existing.isPending) return <LoadingState />;
  if (
    existing.error &&
    !(existing.error instanceof ApiError && existing.error.status === 404)
  )
    return <Alert severity="error">{errorMessage(existing.error)}</Alert>;
  const saved = existing.data;
  return (
    <Form
      key={saved?.updated_at || account.id}
      title={`Debt terms: ${account.name}`}
      submit="Save debt terms"
      fields={[
        ...(
          ["principal_amount", "outstanding_amount", "minimum_payment"] as const
        ).map((name) => ({
          ...amountField,
          name,
          label: `${name.replaceAll("_", " ")} (${account.currency})`,
          required: false,
          value: saved?.[name] ?? "",
          help: "Nonnegative amount; leave blank if unknown.",
        })),
        {
          name: "annual_interest_rate",
          label: "Annual interest rate (ratio)",
          value: saved?.annual_interest_rate ?? "",
          pattern: "(0(\\.[0-9]{1,6})?|1(\\.0{1,6})?)",
          help: "Enter 0.12 for 12%. Leave blank if unknown.",
        },
        {
          name: "payment_due_day",
          label: "Payment due day",
          type: "number",
          min: "1",
          max: "31",
          value: saved?.payment_due_day?.toString() ?? "",
        },
        {
          name: "start_date",
          label: "Start date",
          type: "date",
          value: saved?.start_date ?? "",
        },
        {
          name: "maturity_date",
          label: "Maturity date",
          type: "date",
          value: saved?.maturity_date ?? "",
        },
      ]}
      onSubmit={async (data) => {
        const payload = {
          liability_subtype: account.account_type as "loan" | "credit_card",
          principal_amount: optional(data, "principal_amount"),
          outstanding_amount: optional(data, "outstanding_amount"),
          minimum_payment: optional(data, "minimum_payment"),
          annual_interest_rate: optional(data, "annual_interest_rate"),
          payment_due_day: value(data, "payment_due_day")
            ? Number(value(data, "payment_due_day"))
            : null,
          start_date: optional(data, "start_date"),
          maturity_date: optional(data, "maturity_date"),
        } satisfies Schema<"LiabilityRequest">;
        await mutate(`/accounts/${account.id}/liability`, "PUT", payload);
      }}
    />
  );
}

export default function Accounts() {
  const { user } = useSession();
  const query = useResource<Schema<"AccountListResponse">>("/accounts");
  const mutate = useFinanceMutation();
  const [selected, setSelected] = useState<string | null>(null);
  return (
    <Stack spacing={3}>
      <Paper sx={{ p: 3 }}>
        <Form
          title="Add account"
          submit="Create account"
          fields={[
            ...metadata,
            {
              name: "account_type",
              label: "Account type",
              required: true,
              value: "bank",
              options: types,
            },
            { ...currencyField, value: user?.default_currency || "INR" },
            {
              ...amountField,
              name: "opening_balance",
              label: "Opening balance",
              value: "0",
              pattern: "-?[0-9]{1,15}(\\.[0-9]{1,4})?",
              help: "Opening balance only; FALCON calculates subsequent results.",
            },
            {
              name: "opening_balance_date",
              label: "Opening balance date",
              type: "date",
              required: true,
              value: localDate(user?.timezone),
            },
          ]}
          onSubmit={async (data) => {
            const payload = {
              name: value(data, "name"),
              account_type: value(
                data,
                "account_type",
              ) as Schema<"AccountType">,
              currency: value(data, "currency"),
              opening_balance: value(data, "opening_balance"),
              opening_balance_date: value(data, "opening_balance_date"),
              institution_name: optional(data, "institution_name"),
              masked_reference: optional(data, "masked_reference"),
            } satisfies Schema<"AccountCreateRequest">;
            await mutate("/accounts", "POST", payload);
          }}
        />
      </Paper>
      <Typography variant="h2">Active accounts</Typography>
      {query.isPending && <LoadingState />}
      {query.error && (
        <Alert severity="error">{errorMessage(query.error)}</Alert>
      )}
      {query.data?.items.length === 0 && (
        <Alert severity="info">
          Add your first account before recording or importing transactions.
        </Alert>
      )}
      {query.data?.items.map((account) => (
        <Paper key={account.id} sx={{ p: 3 }}>
          <Stack spacing={2}>
            <Typography variant="h3">{account.name}</Typography>
            <Typography>
              {account.account_type.replaceAll("_", " ")} · {account.currency} ·{" "}
              {account.masked_reference || "No reference"}
            </Typography>
            <Typography>
              Opening balance:{" "}
              {money(account.opening_balance, account.currency)} on{" "}
              {account.opening_balance_date}
            </Typography>
            <Stack direction="row">
              <Button
                onClick={() =>
                  setSelected(selected === account.id ? null : account.id)
                }
              >
                {selected === account.id ? "Close editor" : "Edit account"}
              </Button>
              <ConfirmAction
                label={`Archive ${account.name}`}
                detail="This removes the account from active selection. Historical transactions and analytics are retained."
                action={async () => {
                  await mutate(`/accounts/${account.id}/archive`, "POST");
                }}
              />
            </Stack>
            {selected === account.id && (
              <>
                <Form
                  key={account.updated_at}
                  title="Account details"
                  submit="Save account details"
                  fields={metadata.map((field) => ({
                    ...field,
                    value:
                      account[
                        field.name as
                          | "name"
                          | "institution_name"
                          | "masked_reference"
                      ] ?? "",
                  }))}
                  onSubmit={async (data) => {
                    await mutate(`/accounts/${account.id}`, "PUT", {
                      name: value(data, "name"),
                      institution_name: optional(data, "institution_name"),
                      masked_reference: optional(data, "masked_reference"),
                    } satisfies Schema<"AccountMetadataRequest">);
                  }}
                />
                {(account.account_type === "loan" ||
                  account.account_type === "credit_card") && (
                  <Liability account={account} />
                )}
              </>
            )}
          </Stack>
        </Paper>
      ))}
    </Stack>
  );
}
