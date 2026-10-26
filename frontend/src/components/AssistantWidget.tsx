import { lazy, Suspense, useEffect, useRef, useState } from "react";
import { Box, Button, Paper, Stack, Typography } from "@mui/material";
import { FeatureIcon } from "./Brand";
import { LoadingState } from "./States";

const Assistant = lazy(() => import("../pages/Assistant"));

export function AssistantWidget({
  open,
  onOpen,
  onClose,
}: {
  open: boolean;
  onOpen: () => void;
  onClose: () => void;
}) {
  const [mounted, setMounted] = useState(open);
  const launcher = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  if (open && !mounted) setMounted(true);
  useEffect(() => {
    if (open && mounted) panel.current?.focus();
  }, [open, mounted]);
  const close = () => {
    onClose();
    requestAnimationFrame(() => launcher.current?.focus());
  };
  return (
    <>
      <Button
        ref={launcher}
        onClick={onOpen}
        variant="contained"
        aria-expanded={open}
        aria-controls="falcon-chat-panel"
        startIcon={<FeatureIcon name="spark" />}
        sx={{
          display: open ? "none" : "inline-flex",
          position: "fixed",
          bottom: 20,
          right: { xs: 16, md: 28 },
          borderRadius: 20,
          bgcolor: "primary.dark",
          minHeight: 48,
          boxShadow: "0 8px 24px #173e3633",
          zIndex: 1200,
        }}
      >
        Ask FALCON
      </Button>
      {mounted && (
        <Paper
          id="falcon-chat-panel"
          ref={panel}
          tabIndex={-1}
          role="dialog"
          aria-labelledby="falcon-chat-title"
          onKeyDown={(event) => {
            if (
              event.key === "Escape" &&
              !(event.target as HTMLElement).closest(
                '[role="dialog"]:not(#falcon-chat-panel)',
              )
            ) {
              event.stopPropagation();
              close();
            }
          }}
          sx={{
            display: open ? "flex" : "none",
            flexDirection: "column",
            position: "fixed",
            bottom: { xs: 8, sm: 20 },
            right: { xs: 8, sm: 28 },
            width: { xs: "calc(100vw - 16px)", sm: 440 },
            maxWidth: "calc(100vw - 16px)",
            height: "min(760px, calc(100dvh - 32px))",
            zIndex: 1200,
            overflow: "hidden",
            borderRadius: 3,
            boxShadow: "0 16px 60px #173e3640",
          }}
        >
          <Stack
            direction="row"
            sx={{
              p: 2,
              gap: 2,
              alignItems: "center",
              justifyContent: "space-between",
              bgcolor: "primary.dark",
              color: "#fff",
              flexShrink: 0,
            }}
          >
            <Box>
              <Typography
                component="h2"
                id="falcon-chat-title"
                sx={{ color: "#fff", fontWeight: 750 }}
              >
                Assistant
              </Typography>
              <Typography variant="body2" sx={{ color: "#c1d7d0" }}>
                FALCON AI · Your financial evidence
              </Typography>
            </Box>
            <Button
              onClick={close}
              aria-label="Minimize chat"
              sx={{ color: "#fff", minWidth: 44 }}
            >
              Close
            </Button>
          </Stack>
          <Box sx={{ flex: 1, minHeight: 0, p: 1.5 }}>
            <Suspense fallback={<LoadingState />}>
              <Assistant embedded active={open} />
            </Suspense>
          </Box>
        </Paper>
      )}
    </>
  );
}
