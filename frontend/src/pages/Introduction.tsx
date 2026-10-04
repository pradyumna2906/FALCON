import {
  Box,
  Button,
  Container,
  Paper,
  Stack,
  Typography,
} from "@mui/material";
import { Link } from "react-router";
import { Brand, FeatureIcon } from "../components/Brand";

const features = [
  [
    "money",
    "Your money, in one place",
    "Add transactions or import CSV, Excel and supported PDF statements. Keep accounts and categories organized.",
  ],
  [
    "analytics",
    "Find the patterns",
    "Understand cash flow, review recurring spending, and spot budget pressure with explainable insights.",
  ],
  [
    "forecasts",
    "See what could come next",
    "Forecast income, expenses and savings with prediction intervals and clear evidence about reliability.",
  ],
  [
    "goals",
    "Make room for every goal",
    "Track contributions and explore how to allocate savings across the things that matter to you.",
  ],
  [
    "scenarios",
    "Try the what-ifs",
    "Compare changes in income, expenses and priorities before deciding on your next step.",
  ],
  [
    "assistant",
    "Ask with confidence",
    "Explore your financial picture with an assistant that grounds its answers in your available evidence.",
  ],
] as const;

export default function Introduction() {
  return (
    <Box>
      <Container maxWidth="lg">
        <Stack
          component="header"
          direction="row"
          sx={{
            py: 3,
            alignItems: "center",
            justifyContent: "space-between",
            gap: 2,
          }}
        >
          <Brand />
          <Stack direction="row" spacing={1}>
            <Button
              href="#features"
              sx={{ display: { xs: "none", sm: "inline-flex" } }}
            >
              Explore FALCON
            </Button>
            <Button component={Link} to="/sign-in">
              Sign in
            </Button>
            <Button
              component={Link}
              to="/register"
              variant="contained"
              sx={{ display: { xs: "none", sm: "inline-flex" } }}
            >
              Get started
            </Button>
          </Stack>
        </Stack>
        <Box component="main">
          <Box
            sx={{
              display: "grid",
              gridTemplateColumns: { xs: "1fr", md: "1.1fr .9fr" },
              alignItems: "center",
              gap: { xs: 5, md: 7 },
              py: { xs: 5, md: 9 },
            }}
          >
            <Box>
              <Stack
                direction="row"
                spacing={1}
                sx={{ color: "primary.main", alignItems: "center", mb: 3 }}
              >
                <FeatureIcon name="spark" size={18} />
                <Typography
                  variant="body2"
                  sx={{ fontWeight: 700, letterSpacing: ".06em" }}
                >
                  A LITTLE CLARITY. A BIGGER FUTURE.
                </Typography>
              </Stack>
              <Typography
                component="h1"
                sx={{
                  fontSize: { xs: "2.8rem", md: "3.9rem" },
                  fontWeight: 700,
                  lineHeight: 1.08,
                  letterSpacing: "-.055em",
                }}
              >
                Understand today.
                <br />
                <Box component="span" sx={{ color: "primary.main" }}>
                  Plan your financial future.
                </Box>
              </Typography>
              <Typography
                color="text.secondary"
                sx={{ mt: 3, mb: 4, maxWidth: 510, fontSize: "1.1rem" }}
              >
                Your spending, your goals, and a clearer view of what comes
                next. Bring them together in one personal financial workspace.
              </Typography>
              <Stack
                direction="row"
                spacing={1.5}
                useFlexGap
                sx={{ flexWrap: "wrap" }}
              >
                <Button
                  component={Link}
                  to="/register"
                  variant="contained"
                  size="large"
                >
                  Create your account
                </Button>
                <Button
                  component={Link}
                  to="/sign-in"
                  variant="outlined"
                  size="large"
                >
                  Sign in to FALCON
                </Button>
              </Stack>
              <Stack
                direction="row"
                spacing={1}
                sx={{ alignItems: "center", mt: 3, color: "text.secondary" }}
              >
                <FeatureIcon name="shield" size={18} />
                <Typography variant="body2">
                  Verified access. Your own records. Your own plan.
                </Typography>
              </Stack>
            </Box>
            <Paper
              sx={{
                p: { xs: 3, sm: 4 },
                bgcolor: "#204f45",
                color: "#fff",
                borderRadius: 4,
                borderColor: "#204f45",
                boxShadow: "0 24px 60px #173e361c",
              }}
            >
              <Typography
                variant="body2"
                sx={{ color: "#bed4cf", letterSpacing: ".08em", mb: 1 }}
              >
                YOUR FINANCIAL WORKSPACE
              </Typography>
              <Typography
                variant="h2"
                sx={{
                  fontSize: "1.9rem",
                  letterSpacing: "-.045em",
                  maxWidth: 300,
                }}
              >
                A plan built around your life.
              </Typography>
              <Stack spacing={1.5} sx={{ mt: 4 }}>
                {[
                  [
                    "money",
                    "Understand your money",
                    "Accounts, transactions & insights",
                  ],
                  [
                    "forecasts",
                    "Explore your possibilities",
                    "Forecasts & scenario comparisons",
                  ],
                  [
                    "goals",
                    "Move toward your goals",
                    "Contributions & allocation plans",
                  ],
                ].map(([icon, title, detail], i) => (
                  <Box
                    key={title}
                    sx={{
                      display: "flex",
                      alignItems: "center",
                      gap: 2,
                      p: 2.2,
                      borderRadius: 2,
                      bgcolor: i === 1 ? "#f4c76b" : "#2b5a4f",
                      color: i === 1 ? "#173e36" : "#fff",
                    }}
                  >
                    <FeatureIcon name={icon} size={28} />
                    <Box>
                      <Typography sx={{ fontWeight: 650 }}>{title}</Typography>
                      <Typography
                        variant="body2"
                        sx={{ color: i === 1 ? "#3e4b32" : "#c1d7d0" }}
                      >
                        {detail}
                      </Typography>
                    </Box>
                  </Box>
                ))}
              </Stack>
              <Typography variant="body2" sx={{ mt: 3, color: "#bed4cf" }}>
                Built for regular and irregular income, with evidence you can
                review.
              </Typography>
            </Paper>
          </Box>
          <Box
            id="features"
            sx={{
              scrollMarginTop: 24,
              py: { xs: 4, md: 7 },
              borderTop: "1px solid",
              borderColor: "divider",
            }}
          >
            <Typography
              variant="body2"
              color="primary"
              sx={{ fontWeight: 700, letterSpacing: ".1em", mb: 1 }}
            >
              FROM TODAY TO WHAT’S NEXT
            </Typography>
            <Typography
              variant="h2"
              sx={{ fontSize: { xs: "1.8rem", sm: "2.3rem" }, mb: 4 }}
            >
              One picture. Every part of your finances.
            </Typography>
            <Box
              sx={{
                display: "grid",
                gridTemplateColumns: {
                  xs: "1fr",
                  sm: "1fr 1fr",
                  md: "repeat(3, 1fr)",
                },
                gap: 2.5,
              }}
            >
              {features.map(([icon, title, detail], i) => (
                <Paper key={title} sx={{ p: 3 }}>
                  <Box
                    sx={{
                      display: "grid",
                      placeItems: "center",
                      width: 46,
                      height: 46,
                      borderRadius: 2,
                      bgcolor: ["#e7f1ed", "#fbede5", "#e8edf7"][i % 3],
                      color: ["#23685b", "#92521e", "#48659a"][i % 3],
                      mb: 2.5,
                    }}
                  >
                    <FeatureIcon name={icon} />
                  </Box>
                  <Typography variant="h3">{title}</Typography>
                  <Typography color="text.secondary" sx={{ mt: 1 }}>
                    {detail}
                  </Typography>
                </Paper>
              ))}
            </Box>
          </Box>
          <Paper
            sx={{
              display: "flex",
              flexDirection: { xs: "column", sm: "row" },
              gap: 3,
              alignItems: { sm: "center" },
              justifyContent: "space-between",
              p: { xs: 3, md: 4 },
              my: 4,
              bgcolor: "#e7f1ed",
              borderColor: "#d6e4df",
            }}
          >
            <Box>
              <Typography variant="h2">
                Start with your financial picture.
              </Typography>
              <Typography color="text.secondary" sx={{ mt: 1 }}>
                Create an account, verify your email, and add your records.
              </Typography>
            </Box>
            <Button
              component={Link}
              to="/register"
              variant="contained"
              sx={{
                flexShrink: 0,
                alignSelf: { xs: "flex-start", sm: "auto" },
              }}
            >
              Get started
            </Button>
          </Paper>
        </Box>
        <Stack
          component="footer"
          direction={{ xs: "column", sm: "row" }}
          spacing={2}
          sx={{
            justifyContent: "space-between",
            py: 4,
            borderTop: "1px solid",
            borderColor: "divider",
          }}
        >
          <Typography variant="body2" color="text.secondary">
            FALCON · Your money. Your future.
          </Typography>
          <Typography
            variant="body2"
            color="text.secondary"
            sx={{ maxWidth: 560 }}
          >
            No example figures are presented as your financial data. Forecasts
            and guidance depend on the records you provide.
          </Typography>
        </Stack>
      </Container>
    </Box>
  );
}
