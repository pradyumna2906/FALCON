import { Alert, Button, Paper, Stack, Typography } from "@mui/material";
import { Link } from "react-router";
import { Form, optional, value } from "../components/Forms";
import {
  useFinanceMutation,
  useResource,
  type Schema,
  errorMessage,
} from "../api/finance";
import { ApiError } from "../api/client";
import { LoadingState } from "../components/States";

export default function Onboarding() {
  const profile = useResource<Schema<"FinancialProfileResponse">>("/profile");
  const accounts = useResource<Schema<"AccountListResponse">>("/accounts");
  const mutate = useFinanceMutation();
  if (profile.isPending || accounts.isPending) return <LoadingState />;
  if (
    (profile.error &&
      !(profile.error instanceof ApiError && profile.error.status === 404)) ||
    accounts.error
  )
    return (
      <Alert severity="error">
        {errorMessage(profile.error || accounts.error)}
      </Alert>
    );
  const p = profile.data;
  return (
    <Stack spacing={3}>
      <Typography component="h1" variant="h1">
        Set up your financial workspace
      </Typography>
      <Typography>
        1. Describe your household. 2. Add an account. 3. Import a statement or
        record a transaction.
      </Typography>
      <Paper sx={{ p: 3 }}>
        <Form
          key={p?.updated_at || "new"}
          title="Financial profile"
          submit="Save profile"
          fields={[
            {
              name: "income_pattern",
              label: "Income pattern",
              required: true,
              value: p?.income_pattern || "salaried",
              options: ["salaried", "self_employed", "irregular", "mixed"],
            },
            {
              name: "income_stability",
              label: "Income stability",
              required: true,
              value: p?.income_stability || "stable",
              options: ["stable", "variable", "unstable"],
            },
            {
              name: "has_household_responsibilities",
              label: "Household responsibilities",
              required: true,
              value: String(p?.has_household_responsibilities ?? false),
              options: [
                { value: "false", label: "No" },
                { value: "true", label: "Yes" },
              ],
            },
            {
              name: "dependant_count",
              label: "Number of dependants",
              type: "number",
              required: true,
              min: "0",
              max: "50",
              value: String(p?.dependant_count ?? 0),
            },
            {
              name: "emergency_fund_target_months",
              label: "Emergency fund target (months)",
              value: p?.emergency_fund_target_months || "6",
              pattern: "[0-9]{1,2}(\\.[0-9]{1,2})?",
              help: "0–60 months",
            },
          ]}
          onSubmit={async (data) => {
            await mutate("/profile", "PUT", {
              income_pattern: value(data, "income_pattern"),
              income_stability: value(data, "income_stability"),
              has_household_responsibilities:
                value(data, "has_household_responsibilities") === "true",
              dependant_count: Number(value(data, "dependant_count")),
              emergency_fund_target_months: optional(
                data,
                "emergency_fund_target_months",
              ),
            });
          }}
        />
      </Paper>
      <Paper sx={{ p: 3 }}>
        <Typography variant="h2">Accounts and first transactions</Typography>
        <Typography>
          {accounts.data?.items.length || 0} active accounts available.
        </Typography>
        <Button component={Link} to="/app/money?tab=accounts">
          Add an account
        </Button>
        <Button component={Link} to="/app/money?tab=imports">
          Import a statement
        </Button>
        <Button component={Link} to="/app/money?tab=transactions">
          Record a transaction
        </Button>
      </Paper>
      <Button component={Link} to="/app/overview">
        Go to overview
      </Button>
    </Stack>
  );
}
