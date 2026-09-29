import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Paper,
  Stack,
  Tab,
  Tabs,
  Typography,
} from "@mui/material";
import { Link } from "react-router";
import { api } from "../api/client";
import { useFinanceMutation, useResource, type Schema } from "../api/finance";
import { useSession } from "../auth/session";
import { Form, value, currencyField } from "../components/Forms";
import { ConfirmAction } from "../components/ConfirmAction";
import { DataTable, Result } from "../components/FinancialResults";
import { saveDownload } from "./Reports";

export default function Settings() {
  const [tab, setTab] = useState("preferences");
  return (
    <Stack spacing={3}>
      <Typography variant="h1">Settings & privacy</Typography>
      <Tabs
        value={tab}
        onChange={(_, next: string) => setTab(next)}
        variant="scrollable"
        scrollButtons="auto"
        aria-label="Settings sections"
      >
        <Tab value="preferences" label="Preferences" />
        <Tab value="notifications" label="Notifications" />
        <Tab value="security" label="Sessions & security" />
        <Tab value="privacy" label="Export & erasure" />
      </Tabs>
      {tab === "preferences" && <Preferences />}
      {tab === "notifications" && <Notifications />}
      {tab === "security" && <Security />}
      {tab === "privacy" && <Privacy />}
    </Stack>
  );
}
function Preferences() {
  const query = useResource<Schema<"PreferencesRequest">>("/preferences");
  const mutate = useFinanceMutation();
  const { reloadUser } = useSession();
  return (
    <Result query={query}>
      {(data) => (
        <Form
          key={JSON.stringify(data)}
          title="Workspace preferences"
          fields={[
            {
              name: "display_name",
              label: "Display name",
              value: data.display_name || "",
              maxLength: 120,
            },
            {
              name: "timezone",
              label: "IANA timezone",
              value: data.timezone,
              required: true,
              help: "For example Asia/Kolkata. Changes affect date interpretation, not stored historical snapshots.",
            },
            { ...currencyField, value: data.default_currency },
          ]}
          submit="Save preferences"
          onSubmit={async (form) => {
            await mutate("/preferences", "PUT", {
              display_name: value(form, "display_name") || null,
              timezone: value(form, "timezone"),
              default_currency: value(form, "currency"),
            });
            await reloadUser();
          }}
        />
      )}
    </Result>
  );
}
function Notifications() {
  const [offset, setOffset] = useState(0);
  const prefs = useResource<Schema<"NotificationPreferences">>(
    "/notifications/preferences",
  );
  const query = useResource<Schema<"NotificationList">>(
    `/notifications?limit=20&offset=${offset}`,
  );
  const mutate = useFinanceMutation();
  return (
    <Stack spacing={2}>
      <Alert severity="info">
        Your in-app inbox tracks actual import outcomes. Refresh imports to add
        new events. Disabling notifications prevents new events; retained items
        can still be read or dismissed. External delivery is configured
        separately.
      </Alert>
      <Result query={prefs}>
        {(data) => (
          <Form
            key={String(data.in_app_enabled)}
            title="Notification preferences"
            fields={[
              {
                name: "enabled",
                label: "In-app notifications",
                value: String(data.in_app_enabled),
                options: [
                  { value: "true", label: "Enabled" },
                  { value: "false", label: "Disabled" },
                ],
              },
            ]}
            submit="Save notifications"
            onSubmit={async (form) => {
              await mutate("/notifications/preferences", "PUT", {
                in_app_enabled: value(form, "enabled") === "true",
              });
            }}
          />
        )}
      </Result>
      <Form
        title="Update inbox"
        fields={[]}
        submit="Refresh import notifications"
        onSubmit={async () => {
          await mutate("/notifications/sync", "POST");
        }}
      />
      <Result query={query}>
        {(data) => (
          <>
            <DataTable
              title="Notification inbox"
              headings={[
                "Notification",
                "Details",
                "Created",
                "Status",
                "Actions",
              ]}
              rows={data.items.map((item) => [
                item.title,
                item.detail,
                item.created_at,
                item.read_at ? "Read" : "Unread",
                <Stack>
                  {!item.read_at && (
                    <ConfirmAction
                      label="Mark read"
                      detail="Mark this notification as read."
                      action={() =>
                        mutate(`/notifications/${item.id}/read`, "POST")
                      }
                    />
                  )}
                  <ConfirmAction
                    label="Dismiss"
                    detail="Hide this notification from your inbox."
                    action={() => mutate(`/notifications/${item.id}`, "DELETE")}
                  />
                </Stack>,
              ])}
            />
            <Stack direction="row">
              <Button
                disabled={offset === 0}
                onClick={() => setOffset(offset - 20)}
              >
                Previous notifications
              </Button>
              <Button
                disabled={!data.has_more || offset >= 10000}
                onClick={() => setOffset(offset + 20)}
              >
                Next notifications
              </Button>
            </Stack>
          </>
        )}
      </Result>
    </Stack>
  );
}
function Security() {
  const [offset, setOffset] = useState(0);
  const query = useResource<Schema<"SessionList">>(
    `/security/sessions?limit=20&offset=${offset}`,
  );
  const cache = useQueryClient();
  return (
    <Stack spacing={2}>
      <Alert severity="info">
        Revoking a session immediately invalidates its access and refresh
        credentials. Revoking the current session signs you out.
      </Alert>
      <Button component={Link} to="/forgot-password">
        Reset password securely
      </Button>
      <Result query={query}>
        {(data) => (
          <>
            <DataTable
              title="Active sessions"
              headings={[
                "Session",
                "Created",
                "Last used",
                "Expires",
                "Revoke",
              ]}
              rows={data.items.map((item) => [
                item.current ? "Current session" : item.id,
                item.created_at,
                item.last_used_at,
                item.expires_at,
                <Form
                  key={item.id}
                  title={
                    item.current
                      ? "Revoke current session"
                      : `Revoke session ${item.id}`
                  }
                  fields={[
                    {
                      name: "password",
                      label: "Confirm password to revoke",
                      type: "password",
                      required: true,
                      maxLength: 128,
                    },
                    {
                      name: "confirmation",
                      label: "Type REVOKE",
                      required: true,
                      pattern: "REVOKE",
                    },
                  ]}
                  submit="Revoke session"
                  onSubmit={async (form) => {
                    await api.request(`/security/sessions/${item.id}/revoke`, {
                      method: "POST",
                      body: JSON.stringify({
                        password: String(form.get("password")),
                      }),
                    });
                    if (item.current) api.clearSession();
                    else
                      await cache.invalidateQueries({ queryKey: ["finance"] });
                  }}
                />,
              ])}
            />
            <Stack direction="row">
              <Button disabled={!offset} onClick={() => setOffset(offset - 20)}>
                Previous sessions
              </Button>
              <Button
                disabled={!data.has_more || offset >= 10000}
                onClick={() => setOffset(offset + 20)}
              >
                Next sessions
              </Button>
            </Stack>
          </>
        )}
      </Result>
    </Stack>
  );
}
function Privacy() {
  const [exportKey, setExportKey] = useState(0);
  return (
    <Stack spacing={3}>
      <Alert severity="info">
        Exports include your retained financial records and decrypted
        conversation history. Credentials and authentication delivery secrets
        are excluded. Downloads are generated on demand and are not saved in
        browser storage. The bounded export fails explicitly if it exceeds
        100,000 rows or 32 MiB.
      </Alert>
      <Form
        key={exportKey}
        title="Export personal data"
        fields={[
          {
            name: "password",
            label: "Confirm password to export",
            type: "password",
            required: true,
            maxLength: 128,
          },
        ]}
        submit="Download personal data"
        onSubmit={async (form) => {
          await saveDownload("/privacy/export", "falcon-personal-data.json", {
            password: String(form.get("password")),
          });
          setExportKey((key) => key + 1);
        }}
      />
      <Button component={Link} to="/app/assistant">
        Review or delete individual conversations
      </Button>
      <Paper sx={{ p: 2 }}>
        <Stack spacing={2}>
          <Alert severity="error">
            Account erasure permanently deletes your live account, financial
            records, conversations, notifications and sessions. You will be
            signed out. Previously downloaded files remain with you. Deployment
            backup retention is a separate operational policy.
          </Alert>
          <Form
            title="Permanently erase account"
            fields={[
              {
                name: "password",
                label: "Confirm password to erase",
                type: "password",
                required: true,
                maxLength: 128,
              },
              {
                name: "confirmation",
                label: "Type DELETE MY ACCOUNT",
                required: true,
                pattern: "DELETE MY ACCOUNT",
              },
            ]}
            submit="Permanently delete my account"
            onSubmit={async (form) => {
              await api.request("/privacy/erase", {
                method: "POST",
                body: JSON.stringify({
                  password: String(form.get("password")),
                  confirmation: value(form, "confirmation"),
                }),
              });
              api.clearSession();
            }}
          />
        </Stack>
      </Paper>
    </Stack>
  );
}
