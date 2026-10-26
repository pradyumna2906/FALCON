import { PageHeading } from "../components/PageHeading";
import { lazy, Suspense } from "react";
import { Stack, Tab, Tabs } from "@mui/material";
import { useSearchParams } from "react-router";
import { LoadingState } from "../components/States";
const Accounts = lazy(() => import("./money/Accounts"));
const Transactions = lazy(() => import("./money/Transactions"));
const Transfers = lazy(() =>
  import("./money/Transactions").then((module) => ({
    default: module.Transfers,
  })),
);
const Imports = lazy(() => import("./money/Imports"));
const Memory = lazy(() => import("./money/Memory"));
const sections = {
  accounts: Accounts,
  transactions: Transactions,
  transfers: Transfers,
  imports: Imports,
  memory: Memory,
};
export default function Money() {
  const [params, setParams] = useSearchParams();
  const name = params.get("tab") || "accounts";
  const tab = Object.hasOwn(sections, name)
    ? (name as keyof typeof sections)
    : "accounts";
  const Page = sections[tab];
  return (
    <Stack spacing={3}>
      <PageHeading
        title="Money"
        description="Your accounts, transactions, imports and merchant memory."
        icon="money"
      />
      <Tabs
        value={tab}
        variant="scrollable"
        scrollButtons="auto"
        aria-label="Money sections"
        onChange={(_, next: string) => setParams({ tab: next })}
      >
        {Object.keys(sections).map((key) => (
          <Tab
            key={key}
            value={key}
            label={key === "memory" ? "Merchant memory" : key}
            id={`money-tab-${key}`}
            aria-controls="money-panel"
          />
        ))}
      </Tabs>
      <div
        role="tabpanel"
        id="money-panel"
        aria-labelledby={`money-tab-${tab}`}
      >
        <Suspense fallback={<LoadingState />}>
          <Page />
        </Suspense>
      </div>
    </Stack>
  );
}
