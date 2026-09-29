import { useState } from "react";
import {
  Alert,
  Button,
  Container,
  Paper,
  Stack,
  Typography,
} from "@mui/material";
import { Link, Navigate, useNavigate } from "react-router";
import { Form, value, optional, type Field } from "../components/Forms";
import { api } from "../api/client";
import { useSession } from "../auth/session";

const email: Field = {
  name: "email",
  label: "Email",
  type: "email",
  required: true,
  maxLength: 320,
};
const password: Field = {
  name: "password",
  label: "Password",
  type: "password",
  required: true,
  maxLength: 128,
};
const token: Field = {
  name: "token",
  label: "Token from your email",
  required: true,
  minLength: 43,
  maxLength: 256,
  pattern: "[A-Za-z0-9_-]+",
};
const send = (path: string, body: unknown) =>
  api.request(
    `/auth/${path}`,
    { method: "POST", body: JSON.stringify(body) },
    false,
  );

export default function AuthPage({
  mode,
}: {
  mode:
    | "sign-in"
    | "register"
    | "verify-email"
    | "forgot-password"
    | "reset-password";
}) {
  const session = useSession();
  const navigate = useNavigate();
  const [notice, setNotice] = useState("");
  const title = {
    "sign-in": "Sign in",
    register: "Create your account",
    "verify-email": "Verify your email",
    "forgot-password": "Recover your account",
    "reset-password": "Reset your password",
  }[mode];
  if (
    (mode === "sign-in" || mode === "register") &&
    session.status === "authenticated"
  )
    return (
      <Navigate
        to={session.user?.email_verified ? "/app/overview" : "/verify-email"}
        replace
      />
    );
  return (
    <Container component="main" maxWidth="sm" sx={{ py: 6 }}>
      <Paper sx={{ p: { xs: 2, sm: 4 } }}>
        <Stack spacing={3}>
          <Typography component="h1" variant="h1">
            {title}
          </Typography>
          {notice && <Alert severity="info">{notice}</Alert>}
          {mode === "sign-in" && (
            <Form
              title="Welcome back"
              fields={[email, password]}
              submit="Sign in"
              onSubmit={async (data) => {
                const user = await session.login(
                  value(data, "email"),
                  String(data.get("password")),
                );
                navigate(
                  user.email_verified ? "/app/overview" : "/verify-email",
                  { replace: true },
                );
              }}
            />
          )}
          {mode === "register" && (
            <Form
              title="Your details"
              submit="Create account"
              fields={[
                email,
                {
                  ...password,
                  name: "new_password",
                  minLength: 12,
                  help: "12–128 characters. Use a unique password.",
                },
                { name: "display_name", label: "Display name", maxLength: 120 },
                {
                  name: "timezone",
                  label: "IANA timezone",
                  value: "Asia/Kolkata",
                  required: true,
                },
                {
                  name: "default_currency",
                  label: "Default currency",
                  value: "INR",
                  required: true,
                  pattern: "[A-Z]{3}",
                },
              ]}
              onSubmit={async (data) => {
                await send("register", {
                  email: value(data, "email"),
                  password: String(data.get("new_password")),
                  display_name: optional(data, "display_name"),
                  timezone: value(data, "timezone"),
                  default_currency: value(data, "default_currency"),
                });
                navigate("/sign-in", { replace: true });
              }}
            />
          )}
          {mode === "verify-email" && (
            <>
              <Typography>
                Enter the verification token delivered to your email. Financial
                access requires verification.
              </Typography>
              <Form
                title="Confirm verification"
                fields={[token]}
                submit="Verify email"
                onSubmit={async (data) => {
                  await send("email-verification/confirm", {
                    token: value(data, "token"),
                  });
                  if (session.status === "authenticated") {
                    await session.reloadUser();
                    navigate("/app/onboarding", { replace: true });
                  } else {
                    navigate("/sign-in", { replace: true });
                  }
                }}
              />
              <Form
                title="Request another verification message"
                fields={[{ ...email, value: session.user?.email }]}
                submit="Request verification"
                onSubmit={async (data) => {
                  await send("email-verification/request", {
                    email: value(data, "email"),
                  });
                  setNotice(
                    "If the account is eligible, a verification message has been queued. Delivery depends on the configured email service.",
                  );
                }}
              />
              {session.status === "authenticated" && (
                <Button
                  onClick={() => {
                    void session.logout();
                  }}
                >
                  Sign out
                </Button>
              )}
            </>
          )}
          {mode === "forgot-password" && (
            <Form
              title="Request a reset message"
              fields={[email]}
              submit="Request reset"
              onSubmit={async (data) => {
                await send("password-reset/request", {
                  email: value(data, "email"),
                });
                setNotice(
                  "If the account is eligible, a reset message has been queued. Delivery depends on the configured email service.",
                );
              }}
            />
          )}
          {mode === "reset-password" && (
            <Form
              title="Choose a new password"
              fields={[
                token,
                { ...password, name: "new_password", minLength: 12 },
              ]}
              submit="Reset password"
              onSubmit={async (data) => {
                await send("password-reset/confirm", {
                  token: value(data, "token"),
                  new_password: String(data.get("new_password")),
                });
                api.clearSession();
                navigate("/sign-in", { replace: true });
              }}
            />
          )}
          <Stack direction="row" useFlexGap sx={{ flexWrap: "wrap" }}>
            <Button component={Link} to="/sign-in">
              Sign in
            </Button>
            <Button component={Link} to="/register">
              Register
            </Button>
            <Button component={Link} to="/forgot-password">
              Forgot password?
            </Button>
            <Button component={Link} to="/reset-password">
              Use reset token
            </Button>
          </Stack>
        </Stack>
      </Paper>
    </Container>
  );
}
