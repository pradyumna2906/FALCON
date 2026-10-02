import { lazy, Suspense, useState } from "react";
import {
  AppBar,
  Avatar,
  Box,
  Button,
  Container,
  Drawer,
  List,
  ListItemButton,
  ListItemText,
  Stack,
  Toolbar,
  Typography,
  Tooltip,
} from "@mui/material";
import {
  createBrowserRouter,
  Link,
  Navigate,
  NavLink,
  Outlet,
  useLocation,
} from "react-router";
import { Brand, FeatureIcon } from "./components/Brand";
import { useSession } from "./auth/session";
import { EmptyState, ErrorState, LoadingState } from "./components/States";

const Introduction = lazy(() => import("./pages/Introduction"));
const AuthPage = lazy(() => import("./pages/Auth"));
const Overview = lazy(() => import("./pages/Overview"));
const Onboarding = lazy(() => import("./pages/Onboarding"));
const Money = lazy(() => import("./pages/Money"));
const Analytics = lazy(() => import("./pages/Analytics"));
const Forecasts = lazy(() => import("./pages/Forecasts"));
const Goals = lazy(() => import("./pages/Goals"));
const Scenarios = lazy(() => import("./pages/Scenarios"));
const Assistant = lazy(() => import("./pages/Assistant"));
const Reports = lazy(() => import("./pages/Reports"));
const Settings = lazy(() => import("./pages/Settings"));

export const navigation = [
  ["overview", "Overview"],
  ["money", "Money"],
  ["analytics", "Analytics"],
  ["forecasts", "Forecasts"],
  ["goals", "Goals & Plans"],
  ["scenarios", "Scenarios"],
  ["assistant", "Assistant"],
  ["reports", "Reports"],
  ["settings", "Settings"],
] as const;

export function RequireSession() {
  const { status, user } = useSession();
  const location = useLocation();
  if (status === "loading") return <LoadingState />;
  if (status === "error")
    return (
      <ErrorState message="The API is unavailable. Your financial information has not been loaded." />
    );
  if (status === "anonymous")
    return (
      <Navigate
        to="/sign-in"
        state={{ returnTo: location.pathname + location.search }}
        replace
      />
    );
  if (!user?.email_verified) return <Navigate to="/verify-email" replace />;
  return <Outlet />;
}

function Shell() {
  const [open, setOpen] = useState(false);
  const { user, logout } = useSession();
  const location = useLocation();
  const section =
    navigation.find(([path]) => location.pathname === `/app/${path}`)?.[1] ||
    "Setup";
  const date = new Intl.DateTimeFormat("en-IN", {
    timeZone: user?.timezone || "Asia/Kolkata",
    weekday: "long",
    day: "numeric",
    month: "long",
  }).format(new Date());
  const links = (
    <Box
      component="nav"
      aria-label="Main navigation"
      sx={{
        width: 240,
        minHeight: "100dvh",
        p: 2,
        bgcolor: "#173e36",
        color: "#fff",
        display: "flex",
        flexDirection: "column",
      }}
    >
      <Box
        component={Link}
        to="/app/overview"
        aria-label="FALCON overview"
        onClick={() => setOpen(false)}
        sx={{ px: 1, pt: 1.5, pb: 4, textDecoration: "none" }}
      >
        <Brand light />
      </Box>
      <Typography
        sx={{
          fontSize: ".75rem",
          letterSpacing: ".12em",
          color: "#a9c8c0",
          px: 1.5,
          mb: 1,
        }}
      >
        WORKSPACE
      </Typography>
    <List component="div" sx={{ display: "grid", gap: 0.5 }}>
        {navigation.map(([path, label], i) => (
          <Box key={path}>
            {(i === 3 || i === 6) && (
              <Typography
                sx={{
                  mt: 2,
                  mb: 1,
                  px: 1.5,
                  fontSize: ".75rem",
                  letterSpacing: ".1em",
                  color: "#a9c8c0",
                }}
              >
                {i === 3 ? "PLAN AHEAD" : "TOOLS & ACCOUNT"}
              </Typography>
            )}
            <ListItemButton
              component={NavLink}
              to={`/app/${path}`}
              onClick={() => setOpen(false)}
              sx={{
                borderRadius: "10px",
                minHeight: 46,
                gap: 1.5,
                color: "#c1d7d0",
                position: "relative",
                "&:hover": { bgcolor: "#204d43", color: "#fff" },
                "&.active": {
                  bgcolor: "#2b5a4f",
                  color: "#fff",
                  "&::after": {
                    content: '""',
                    position: "absolute",
                    right: -16,
                    height: 20,
                    width: 4,
                    borderRadius: 4,
                    bgcolor: "#f4c76b",
                  },
                  "& .MuiListItemText-primary": { fontWeight: 750 },
                },
              }}
            >
              <FeatureIcon name={path} size={20} />
              <ListItemText
                primary={label}
                slotProps={{ primary: { sx: { fontSize: ".875rem" } } }}
              />
            </ListItemButton>
          </Box>
        ))}
      </List>
      <Box sx={{ mt: "auto", pt: 4 }}>
        <Button
          component={Link}
          to="/app/onboarding"
          onClick={() => setOpen(false)}
          fullWidth
          startIcon={<FeatureIcon name="plus" />}
          sx={{
            bgcolor: "#204d43",
            color: "#fff",
            border: "1px solid #3e655b",
            justifyContent: "flex-start",
            "&:hover": { bgcolor: "#2b5a4f" },
          }}
        >
          Your financial profile
        </Button>
        <Stack
          direction="row"
          spacing={1}
          sx={{
            mt: 2.5,
            px: 1,
            pt: 2,
            borderTop: "1px solid #3e655b",
            color: "#b8d0ca",
            alignItems: "center",
          }}
        >
          <FeatureIcon name="shield" size={18} />
          <Typography variant="body2">Your private workspace</Typography>
        </Stack>
      </Box>
    </Box>
  );
  return (
    <Box sx={{ display: "flex", minHeight: "100vh" }}>
      <Box
        component="a"
        href="#main"
        sx={{
          position: "absolute",
          left: -1000,
          "&:focus": {
            left: 12,
            top: 12,
            zIndex: 1500,
            bgcolor: "background.paper",
            p: 2,
          },
        }}
      >
        Skip to content
      </Box>
      <Box
        sx={{
          display: { xs: "none", md: "block" },
          position: "sticky",
          top: 0,
          height: "100dvh",
          overflowY: "auto",
          flexShrink: 0,
        }}
      >
        {links}
      </Box>
      <Drawer
        open={open}
        onClose={() => setOpen(false)}
        slotProps={{ paper: { sx: { borderRadius: 0, bgcolor: "#173e36" } } }}
      >
        {links}
      </Drawer>
      <Box sx={{ flex: 1, minWidth: 0 }}>
        <AppBar
          position="sticky"
          color="inherit"
          elevation={0}
          sx={{
            borderRadius: 0,
            borderWidth: "0 0 1px",
            bgcolor: "#f5f4efee",
            backdropFilter: "blur(12px)",
            boxShadow: "none",
          }}
        >
          <Toolbar
            sx={{
              gap: { xs: 0.5, sm: 1.5 },
              minHeight: { xs: 72, sm: 86 },
              px: { xs: 2, lg: 4 },
            }}
          >
            <Button
              sx={{ display: { md: "none" }, minWidth: 44, px: 1 }}
              onClick={() => setOpen(true)}
              aria-label="Open navigation"
            >
              <FeatureIcon name="menu" />
            </Button>
            <Box sx={{ flex: 1, minWidth: 0 }}>
              <Typography
                sx={{
                  fontSize: ".75rem",
                  color: "text.secondary",
                  display: { xs: "none", sm: "block" },
                  mb: 0.5,
                }}
              >
                {date}
              </Typography>
              <Typography
                sx={{
                  fontWeight: 650,
                  fontSize: { xs: "1rem", sm: "1.25rem" },
                  letterSpacing: "-.025em",
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                }}
              >
                {section === "Overview"
                  ? `Welcome back${user?.display_name ? `, ${user.display_name.split(" ")[0]}` : ""}.`
                  : section}
              </Typography>
            </Box>
            <Tooltip title="Manage your currency and profile">
              <Button
                component={Link}
                to="/app/settings"
                variant="outlined"
                sx={{
                  display: { xs: "none", sm: "inline-flex" },
                  bgcolor: "background.paper",
                  borderColor: "divider",
                  minWidth: 60,
                }}
              >
                {user?.default_currency || "INR"}
              </Button>
            </Tooltip>
            <Button
              component={Link}
              to="/app/onboarding"
              sx={{ display: { xs: "none", sm: "inline-flex" } }}
            >
              Setup
            </Button>
            <Button
              onClick={() => {
                void logout();
              }}
              sx={{ color: "text.secondary", px: { xs: 1, sm: 2 } }}
            >
              Sign out
            </Button>
            <Tooltip title="Account settings">
              <Box
                component={Link}
                to="/app/settings"
                aria-label="Open account settings"
                sx={{
                  display: { xs: "none", sm: "block" },
                  textDecoration: "none",
                }}
              >
                <Avatar
                  sx={{
                    bgcolor: "primary.main",
                    color: "#fff",
                    width: 38,
                    height: 38,
                    fontSize: ".875rem",
                    fontWeight: 750,
                  }}
                >
                  {(user?.display_name || "F").slice(0, 1).toUpperCase()}
                </Avatar>
              </Box>
            </Tooltip>
          </Toolbar>
        </AppBar>
        <Container
          component="main"
          id="main"
          tabIndex={-1}
          maxWidth={false}
          sx={{
            maxWidth: 1540,
            py: { xs: 3, md: 3.5 },
            pb: { xs: 12, md: 13 },
            px: { xs: 2, lg: 4 },
          }}
        >
          <Suspense fallback={<LoadingState />}>
            <Outlet />
          </Suspense>
        </Container>
        {section !== "Assistant" && (
          <Button
            component={Link}
            to="/app/assistant"
            variant="contained"
            startIcon={<FeatureIcon name="spark" />}
            sx={{
              position: "fixed",
              bottom: 20,
              right: { xs: 16, md: 28 },
              borderRadius: 20,
              bgcolor: "primary.dark",
              minHeight: 48,
              boxShadow: "0 8px 24px #173e3633",
              zIndex: 100,
            }}
          >
            Ask FALCON
          </Button>
        )}
      </Box>
    </Box>
  );
}

export const routes = [
  {
    path: "/",
    element: (
      <Suspense fallback={<LoadingState />}>
        <Introduction />
      </Suspense>
    ),
    errorElement: <ErrorState />,
  },
  ...(
    [
      "sign-in",
      "register",
      "verify-email",
      "forgot-password",
      "reset-password",
    ] as const
  ).map((mode) => ({
    path: `/${mode}`,
    element: (
      <Suspense fallback={<LoadingState />}>
        <AuthPage key={mode} mode={mode} />
      </Suspense>
    ),
    errorElement: <ErrorState />,
  })),
  {
    element: <RequireSession />,
    errorElement: <ErrorState />,
    children: [
      {
        path: "/app",
        element: <Shell />,
        children: [
          { index: true, element: <Navigate to="overview" replace /> },
          { path: "overview", element: <Overview /> },
          { path: "money", element: <Money /> },
          { path: "analytics", element: <Analytics /> },
          { path: "forecasts", element: <Forecasts /> },
          { path: "goals", element: <Goals /> },
          { path: "scenarios", element: <Scenarios /> },
          { path: "assistant", element: <Assistant /> },
          { path: "reports", element: <Reports /> },
          { path: "settings", element: <Settings /> },
          { path: "onboarding", element: <Onboarding /> },
        ],
      },
    ],
  },
  {
    path: "*",
    element: (
      <EmptyState
        title="Page not found"
        detail="Return to the home page to continue."
      />
    ),
  },
];
export const router = createBrowserRouter(routes);
