import { createTheme } from "@mui/material/styles";

// Reference: FALCON Finance. One theme keeps all existing workflows consistent.
export const theme = createTheme({
  palette: {
    primary: { main: "#23685b", dark: "#173e36", light: "#e7f1ed" },
    secondary: { main: "#8a5a20", light: "#f4c76b" },
    success: { main: "#23685b" },
    warning: { main: "#92521e" },
    error: { main: "#ad433c" },
    info: { main: "#48659a" },
    background: { default: "#f5f4ef", paper: "#fffefa" },
    text: { primary: "#172723", secondary: "#52665f" },
    divider: "#e2e7e1",
  },
  shape: { borderRadius: 14 },
  typography: {
    fontFamily:
      '"DM Sans", Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
    h1: {
      fontSize: "clamp(1.8rem, 3vw, 2.5rem)",
      fontWeight: 700,
      letterSpacing: "-0.045em",
      lineHeight: 1.2,
    },
    h2: {
      fontSize: "1.25rem",
      fontWeight: 700,
      letterSpacing: "-0.025em",
      lineHeight: 1.35,
    },
    h3: { fontSize: "1.05rem", fontWeight: 700, lineHeight: 1.4 },
    body1: { fontSize: "1rem", lineHeight: 1.65 },
    body2: { fontSize: ".875rem", lineHeight: 1.6 },
    button: { textTransform: "none", fontWeight: 650, fontSize: ".875rem" },
  },
  components: {
    MuiTypography: { styleOverrides: { root: { overflowWrap: 'anywhere' } } },
    MuiPaper: {
      defaultProps: { elevation: 0 },
      styleOverrides: {
        root: {
          border: "1px solid #e2e7e1",
          backgroundImage: "none",
          boxShadow: "0 4px 18px rgba(25,52,45,.025)",
        },
      },
    },
    MuiButton: {
      defaultProps: { disableElevation: true },
      styleOverrides: {
        root: {
          minHeight: 44,
          borderRadius: 9,
          paddingInline: 16,
          transition: "background-color .18s, box-shadow .18s",
          "&:focus-visible": { outline: "3px solid #b68629", outlineOffset: 3 },
        },
      },
    },
    MuiOutlinedInput: {
      styleOverrides: {
        root: { borderRadius: 9, backgroundColor: "#fffefa", fontSize: "1rem" },
        notchedOutline: { borderColor: "#c6d2ca" },
      },
    },
    MuiInputLabel: {
      styleOverrides: { root: { fontWeight: 550, color: "#52665f" } },
    },
    MuiFormHelperText: {
      styleOverrides: { root: { fontSize: ".8125rem", marginInline: 0 } },
    },
    MuiChip: {
      styleOverrides: {
        root: {
          fontWeight: 650,
          borderRadius: 8,
          backgroundColor: "#e7f1ed",
          color: "#23685b",
          fontSize: ".8125rem",
        },
      },
    },
    MuiAlert: {
      styleOverrides: {
        root: { borderRadius: 10, boxShadow: "none" },
        message: { overflowWrap: "anywhere", minWidth: 0 },
        action: { flexShrink: 0 },
      },
    },
    MuiTabs: {
      styleOverrides: {
        root: { borderBottom: "1px solid #e2e7e1", minHeight: 52 },
        indicator: { height: 3, borderRadius: 3 },
      },
    },
    MuiTab: {
      styleOverrides: {
        root: {
          textTransform: "none",
          fontWeight: 650,
          fontSize: ".875rem",
          minHeight: 52,
          paddingInline: 16,
          "&.Mui-selected": { color: "#23685b", backgroundColor: "#e7f1ed" },
        },
      },
    },
    MuiTableCell: {
      styleOverrides: {
        head: {
          backgroundColor: "#f1f4ee",
          color: "#48605a",
          fontWeight: 700,
          whiteSpace: "nowrap",
        },
        root: { borderColor: "#e8ece5", paddingBlock: 14, fontSize: ".875rem" },
      },
    },
    MuiTableRow: {
      styleOverrides: {
        root: {
          "&:last-child td": { borderBottom: 0 },
          "&:hover td": { backgroundColor: "#f6f8f2" },
        },
      },
    },
    MuiLinearProgress: {
      styleOverrides: {
        root: { height: 7, borderRadius: 8, backgroundColor: "#e8ece5" },
        bar: { borderRadius: 8 },
      },
    },
    MuiCssBaseline: {
      styleOverrides: {
        html: { scrollBehavior: "smooth" },
        body: { background: "#f5f4ef" },
        a: { color: "#23685b", textUnderlineOffset: 3 },
        ":focus-visible": { outline: "3px solid #b68629", outlineOffset: 3 },
        "::selection": { background: "#f4c76b", color: "#173e36" },
        summary: { cursor: "pointer" },
        svg: { maxWidth: "100%" },
        "@media (prefers-reduced-motion: reduce)": {
          "*, *::before, *::after": {
            animation: "none !important",
            transition: "none !important",
            scrollBehavior: "auto !important",
          },
        },
      },
    },
  },
});
