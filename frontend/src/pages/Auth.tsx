import { useState } from "react";
import {
  Alert,
  Box,
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
import { Brand, FeatureIcon } from "../components/Brand";

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
    <Container component="main" maxWidth="lg" sx={{ py: { xs: 3, md: 6 } }}>
      <Box component={Link} to="/" sx={{ display: 'inline-block', textDecoration: 'none', mb: 4 }} aria-label="FALCON home"><Brand /></Box>
      <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', md: '0.9fr 1.1fr' }, gap: 3, alignItems: 'start' }}>
      <Box sx={{ display: { xs: 'none', md: 'flex' }, flexDirection: 'column', minHeight: 480, p: 5, borderRadius: 5, bgcolor: '#292239', color: '#fff', backgroundImage: 'radial-gradient(ellipse at 0% 100%, #584076, transparent 75%)' }}>
        <Box sx={{ width: 54, height: 54, bgcolor: '#d3e7dc', color: '#292239', borderRadius: 4, display: 'grid', placeItems: 'center', mb: 5 }}><FeatureIcon name="goals" size={30} /></Box>
        <Typography component="p" sx={{ fontSize: '2.4rem', fontWeight: 800, letterSpacing: '-.05em', lineHeight: 1.15 }}>Big plans.<br />Small steps.<br /><Box component="span" sx={{ color: '#d2c3e3' }}>A clearer future.</Box></Typography>
        <Typography sx={{ mt: 3, color: '#e0d6eb', maxWidth: 320 }}>Build a financial picture that makes sense to you. Your spending, your goals, your next chapter.</Typography>
        <Stack direction="row" spacing={1.5} sx={{ alignItems: 'center', mt: 'auto', pt: 6, color: '#d3e7dc' }}><FeatureIcon name="shield" /><Typography sx={{ fontSize: '.85rem' }}>Private, verified access to your workspace</Typography></Stack>
      </Box>
      <Paper sx={{ p: { xs: 3, sm: 4.5 }, borderRadius: 5 }}>
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
          <Stack spacing={1} sx={{ borderTop: '1px solid', borderColor: 'divider', pt: 2 }}>
            {mode === 'sign-in' ? <>
              <Button component={Link} to="/forgot-password" sx={{ alignSelf: 'flex-start', px: 0 }}>Forgot password?</Button>
              <Typography variant="body2" color="text.secondary">New to FALCON? <Link to="/register">Create an account</Link></Typography>
            </> : <Typography variant="body2" color="text.secondary">Already have an account? <Link to="/sign-in">Sign in</Link></Typography>}
            {mode === 'forgot-password' && <Typography variant="body2" color="text.secondary">Have a reset token? <Link to="/reset-password">Reset your password</Link></Typography>}
          </Stack>
        </Stack>
      </Paper>
      </Box>
    </Container>
  );
}
