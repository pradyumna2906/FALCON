import { Box, Stack, SvgIcon, Typography } from "@mui/material";

const paths: Record<string, string> = {
  overview: "M3 3h7v7H3zM14 3h7v7h-7zM3 14h7v7H3zM14 14h7v7h-7z",
  money: "M3 6h18v14H3zM3 6l13-3v3M15 11h6v5h-6z",
  analytics: "M4 20V10M12 20V4M20 20v-7M2 20h20",
  forecasts: "M3 17l6-6 4 3 8-10M15 4h6v6M3 21h18",
  goals: "M12 3a9 9 0 1 0 9 9M12 7a5 5 0 1 0 5 5M12 12l9-9M16 3h5v5",
  scenarios: "M5 3v18M5 7h7l7-4M12 7v10l7 4M2 3h6M2 21h6",
  assistant: "M4 4h16v12H9l-5 4zM8 9h.01M12 9h.01M16 9h.01",
  reports: "M5 3h10l4 4v14H5zM14 3v5h5M8 12h8M8 16h6",
  settings: "M3 6h18M3 12h18M3 18h18M8 3v6M16 9v6M10 15v6",
  arrow: "M5 12h14M13 6l6 6-6 6",
  plus: "M12 5v14M5 12h14",
  shield: "M12 3l8 3v6c0 5-8 9-8 9S4 17 4 12V6zM8 12l3 3 5-6",
  menu: "M4 6h16M4 12h16M4 18h16",
  spark: "M12 3l2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5z",
  upload: "M12 16V3M7 8l5-5 5 5M4 15v6h16v-6",
  calendar: "M4 5h16v16H4zM8 3v4M16 3v4M4 10h16",
};

export function FeatureIcon({
  name,
  size = 22,
}: {
  name: string;
  size?: number;
}) {
  return (
    <SvgIcon aria-hidden="true" sx={{ fontSize: size }} viewBox="0 0 24 24">
      <path
        d={paths[name] || paths.overview}
        fill="none"
        stroke="currentColor"
        strokeWidth="1.7"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </SvgIcon>
  );
}

export function Brand({ light = false }: { light?: boolean }) {
  return (
    <Stack direction="row" spacing={1.3} sx={{ alignItems: "center" }}>
      <Box
        sx={{
          width: 40,
          height: 40,
          display: "grid",
          placeItems: "center",
          bgcolor: "#f4c76b",
          color: "#173e36",
          borderRadius: "11px",
          flexShrink: 0,
        }}
      >
        <FeatureIcon name="forecasts" size={24} />
      </Box>
      <Box>
        <Typography
          sx={{
            color: light ? "#fff" : "#172723",
            fontWeight: 800,
            letterSpacing: ".12em",
            lineHeight: 1.25,
          }}
        >
          FALCON
        </Typography>
        <Typography
          sx={{ color: light ? "#b8d0ca" : "#52665f", fontSize: ".8125rem" }}
        >
          Finance
        </Typography>
      </Box>
    </Stack>
  );
}
