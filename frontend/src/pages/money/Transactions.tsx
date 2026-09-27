import { useState } from "react";
import { Alert, Button, Paper, Stack, Typography } from "@mui/material";
import {
  Form,
  amountField,
  optional,
  value,
  type Field,
} from "../../components/Forms";
import { ConfirmAction } from "../../components/ConfirmAction";
import { LoadingState } from "../../components/States";
import { useSession } from "../../auth/session";
import {
  useResource,
  useFinanceMutation,
  type Schema,
  errorMessage,
  localDate,
  money,
} from "../../api/finance";

export default function Transactions() {
  const { user } = useSession();
  const accounts = useResource<Schema<"AccountListResponse">>("/accounts");
  const categories = useResource<Schema<"CategoryListResponse">>("/categories");
  const [filters, setFilters] = useState("");
  const [cursor, setCursor] = useState("");
  const query = useResource<Schema<"TransactionPageResponse">>(
    `/transactions?limit=25${filters}${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`,
  );
  const [editing, setEditing] = useState<Schema<"TransactionResponse"> | null>(
    null,
  );
  const mutate = useFinanceMutation();
  const accountOptions =
    accounts.data?.items.map((a) => ({
      value: a.id,
      label: `${a.name} (${a.currency})`,
    })) || [];
  const categoryOptions =
    categories.data?.items
      .filter((c) => c.kind !== "transfer")
      .map((c) => ({ value: c.id, label: `${c.name} (${c.kind})` })) || [];
  const fields: Field[] = [
    {
      name: "account_id",
      label: "Account",
      required: true,
      options: accountOptions,
      value: editing?.account_id || accountOptions[0]?.value,
    },
    {
      name: "transaction_type",
      label: "Type",
      required: true,
      options: ["income", "expense"],
      value: editing?.transaction_type || "expense",
    },
    { ...amountField, value: editing?.amount },
    {
      name: "transaction_date",
      label: "Date",
      type: "date",
      required: true,
      value: editing?.transaction_date || localDate(user?.timezone),
    },
    {
      name: "description",
      label: "Description",
      required: true,
      maxLength: 500,
      value: editing?.description,
    },
    {
      name: "merchant_name",
      label: "Merchant",
      maxLength: 200,
      value: editing?.merchant_name || "",
    },
    {
      name: "category_id",
      label: "Category",
      options: [{ value: "", label: "Uncategorized" }, ...categoryOptions],
      value: editing?.category_id || "",
      help: "Choose a category matching the transaction type.",
    },
  ];
  return (
    <Stack spacing={3}>
      {(accounts.error || categories.error) && (
        <Alert severity="error">
          {errorMessage(accounts.error || categories.error)}
        </Alert>
      )}
      {accountOptions.length > 0 ? (
        <Paper sx={{ p: 3 }}>
          <Form
            key={editing?.id || `new-${accountOptions[0]?.value}`}
            title={editing ? "Edit manual transaction" : "Add transaction"}
            fields={fields}
            submit={editing ? "Save transaction" : "Record transaction"}
            onSubmit={async (data) => {
              const payload = {
                account_id: value(data, "account_id"),
                transaction_type: value(data, "transaction_type") as
                  | "income"
                  | "expense",
                amount: value(data, "amount"),
                transaction_date: value(data, "transaction_date"),
                description: value(data, "description"),
                merchant_name: optional(data, "merchant_name"),
                category_id: optional(data, "category_id"),
              } satisfies Schema<"ManualTransactionCreateRequest">;
              await mutate(
                editing ? `/transactions/${editing.id}` : "/transactions",
                editing ? "PUT" : "POST",
                payload,
              );
              setEditing(null);
            }}
          />
          {editing && (
            <Button onClick={() => setEditing(null)}>Cancel edit</Button>
          )}
        </Paper>
      ) : (
        <Alert severity="info">
          Create an active account to record transactions.
        </Alert>
      )}
      <Paper sx={{ p: 2 }}>
        <Form
          title="Filter transactions"
          submit="Apply filters"
          fields={[
            {
              name: "account_id",
              label: "Account filter",
              options: [
                { value: "", label: "All accounts" },
                ...accountOptions,
              ],
            },
            {
              name: "transaction_type",
              label: "Type filter",
              options: [
                { value: "", label: "All types" },
                "income",
                "expense",
                "transfer",
              ],
            },
            { name: "date_from", label: "From date", type: "date" },
            { name: "date_to", label: "To date", type: "date" },
          ]}
          onSubmit={async (data) => {
            const params = new URLSearchParams();
            for (const key of [
              "account_id",
              "transaction_type",
              "date_from",
              "date_to",
            ])
              if (value(data, key)) params.set(key, value(data, key));
            setCursor("");
            setFilters(params.size ? `&${params}` : "");
          }}
        />
      </Paper>
      <Typography variant="h2">Transaction history</Typography>
      {query.isPending && <LoadingState />}
      {query.error && (
        <Alert severity="error">{errorMessage(query.error)}</Alert>
      )}
      {query.data?.items.length === 0 && (
        <Typography>No matching transactions.</Typography>
      )}
      {query.data?.items.map((transaction) => (
        <Paper key={transaction.id} sx={{ p: 2 }}>
          <Typography variant="h3">{transaction.description}</Typography>
          <Typography>
            {transaction.transaction_date} · {transaction.transaction_type} ·{" "}
            {money(
              transaction.amount,
              accounts.data?.items.find((a) => a.id === transaction.account_id)
                ?.currency || "Account currency",
            )}
          </Typography>
          <Typography>
            {categories.data?.items.find(
              (c) => c.id === transaction.category_id,
            )?.name || "Uncategorized"}{" "}
            · {transaction.source_type} · {transaction.status}
          </Typography>
          {transaction.source_type === "manual" &&
            ["income", "expense"].includes(transaction.transaction_type) &&
            accountOptions.some((a) => a.value === transaction.account_id) && (
              <Button
                onClick={() => {
                  setEditing(transaction);
                  window.scrollTo({ top: 0, behavior: "instant" });
                }}
              >
                Edit transaction
              </Button>
            )}
          {transaction.source_type === "manual" &&
            ["income", "expense"].includes(transaction.transaction_type) && (
              <ConfirmAction
                label="Delete transaction"
                detail={`Delete “${transaction.description}”? This changes your ledger and future analytics.`}
                action={() =>
                  mutate(`/transactions/${transaction.id}`, "DELETE")
                }
              />
            )}
          {transaction.source_type !== "manual" &&
            transaction.status === "posted" &&
            ["income", "expense"].includes(transaction.transaction_type) && (
            <Form
              title="Correct category"
              submit="Apply correction"
              fields={[
                {
                  name: "category_id",
                  label: "Reviewed category",
                  required: true,
                  options: categoryOptions.filter((c) =>
                    c.label.endsWith(`(${transaction.transaction_type})`),
                  ),
                  value: transaction.category_id || "",
                },
              ]}
              onSubmit={async (data) => {
                // Corrections require stored classifier provenance. Subsequent
                // user corrections must not rerun automatic classification.
                if (!transaction.category_id && !transaction.is_user_modified) {
                  await mutate(
                    `/transactions/${transaction.id}/classification`,
                    "POST",
                  );
                }
                await mutate(
                  `/transactions/${transaction.id}/classification/correction`,
                  "POST",
                  { category_id: value(data, "category_id") },
                );
              }}
            />
          )}
        </Paper>
      ))}
      <Stack direction="row">
        <Button disabled={!cursor} onClick={() => setCursor("")}>
          First page
        </Button>
        <Button
          disabled={!query.data?.next_cursor || query.isFetching}
          onClick={() => setCursor(query.data?.next_cursor || "")}
        >
          Next page
        </Button>
      </Stack>
    </Stack>
  );
}

export function Transfers() {
  const { user } = useSession();
  const query = useResource<Schema<"AccountListResponse">>("/accounts");
  const mutate = useFinanceMutation();
  const options =
    query.data?.items.map((a) => ({
      value: a.id,
      label: `${a.name} (${a.currency})`,
    })) || [];
  if (query.isPending) return <LoadingState />;
  if (query.error)
    return <Alert severity="error">{errorMessage(query.error)}</Alert>;
  return (
    <Paper sx={{ p: 3 }}>
      <Alert severity="info" sx={{ mb: 2 }}>
        Record a transfer between two of your accounts in the same currency.
        This records ledger entries; it does not move money at your bank.
      </Alert>
      {options.length < 2 ? (
        <Typography>
          Add two accounts to record an internal transfer.
        </Typography>
      ) : (
        <Form
          title="Internal transfer"
          submit="Record transfer"
          fields={[
            {
              name: "source_account_id",
              label: "From account",
              options,
              required: true,
            },
            {
              name: "destination_account_id",
              label: "To account",
              options,
              required: true,
            },
            amountField,
            {
              name: "transaction_date",
              label: "Transfer date",
              type: "date",
              required: true,
              value: localDate(user?.timezone),
            },
            {
              name: "description",
              label: "Transfer description",
              required: true,
              maxLength: 500,
            },
          ]}
          onSubmit={async (data) => {
            await mutate("/transfers", "POST", {
              source_account_id: value(data, "source_account_id"),
              destination_account_id: value(data, "destination_account_id"),
              amount: value(data, "amount"),
              transaction_date: value(data, "transaction_date"),
              description: value(data, "description"),
            } satisfies Schema<"TransferCreateRequest">);
          }}
        />
      )}
    </Paper>
  );
}
