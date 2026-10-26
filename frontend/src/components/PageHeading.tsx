import { Box, Stack, Typography } from "@mui/material";
import { FeatureIcon } from "./Brand";

export function PageHeading({
  title,
  description,
  icon,
}: {
  title: string;
  description: string;
  icon: string;
}) {
  return (
    <Stack direction="row" spacing={2} sx={{ alignItems: "center" }}>
      <Box
        sx={{
          width: 48,
          height: 48,
          display: { xs: "none", sm: "grid" },
          placeItems: "center",
          borderRadius: 2.5,
          bgcolor: "#e7f1ed",
          color: "primary.main",
          flexShrink: 0,
        }}
      >
        <FeatureIcon name={icon} size={25} />
      </Box>
      <Box>
        <Typography component="h1" variant="h1">
          {title}
        </Typography>
        <Typography color="text.secondary" sx={{ mt: 0.5 }}>
          {description}
        </Typography>
      </Box>
    </Stack>
  );
}
