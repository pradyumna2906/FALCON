import { createTheme } from '@mui/material/styles';

export const theme = createTheme({
  palette: {
    primary: { main: '#70558e', dark: '#513b6b', light: '#ede4ff' },
    secondary: { main: '#176e62', light: '#dff4ed' },
    success: { main: '#176e62' }, warning: { main: '#8b570b' }, error: { main: '#ba3e51' }, info: { main: '#5542a5' },
    background: { default: '#f7f5f1', paper: '#ffffff' }, text: { primary: '#272239', secondary: '#696477' }, divider: '#e8e3ed',
  },
  shape: { borderRadius: 18 },
  typography: {
    fontFamily: 'Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
    h1: { fontSize: 'clamp(1.8rem, 3vw, 2.6rem)', fontWeight: 800, letterSpacing: '-0.045em', lineHeight: 1.2 },
    h2: { fontSize: '1.25rem', fontWeight: 750, letterSpacing: '-0.025em' }, h3: { fontSize: '1.08rem', fontWeight: 700 },
    body1: { fontSize: '0.95rem', lineHeight: 1.7 }, body2: { fontSize: '0.84rem', lineHeight: 1.6 }, button: { textTransform: 'none', fontWeight: 700 },
  },
  components: {
    MuiPaper: { defaultProps: { elevation: 0 }, styleOverrides: { root: { border: '1px solid #e8e3ed', backgroundImage: 'none', boxShadow: '0 4px 24px rgba(43,28,68,.035)' } } },
    MuiButton: { defaultProps: { disableElevation: true }, styleOverrides: { root: { minHeight: 44, borderRadius: 12, paddingInline: 18 } } },
    MuiOutlinedInput: { styleOverrides: { root: { borderRadius: 12, backgroundColor: '#fff' }, notchedOutline: { borderColor: '#d9d2e3' } } },
    MuiInputLabel: { styleOverrides: { root: { fontWeight: 600 } } },
    MuiChip: { styleOverrides: { root: { fontWeight: 650, borderRadius: 8, backgroundColor: '#eee8f7', color: '#573a82' } } },
    MuiAlert: { styleOverrides: { root: { borderRadius: 12, boxShadow: 'none' } } },
    MuiTabs: { styleOverrides: { root: { backgroundColor: '#eee9f3', borderRadius: 14, padding: 5, minHeight: 52 }, indicator: { display: 'none' } } },
    MuiTab: { styleOverrides: { root: { textTransform: 'none', fontWeight: 650, minHeight: 42, borderRadius: 10, '&.Mui-selected': { backgroundColor: '#fff', color: '#644c80', boxShadow: '0 2px 8px rgba(43,28,68,.07)' } } } },
    MuiTableCell: { styleOverrides: { head: { backgroundColor: '#f3eff8', color: '#554766', fontWeight: 750, whiteSpace: 'nowrap' }, root: { borderColor: '#eeeaf2', paddingBlock: 14 } } },
    MuiTableRow: { styleOverrides: { root: { '&:last-child td': { borderBottom: 0 }, '&:hover td': { backgroundColor: '#fcfaff' } } } },
    MuiLinearProgress: { styleOverrides: { root: { height: 8, borderRadius: 8, backgroundColor: '#ebe3f5' }, bar: { borderRadius: 8 } } },
    MuiCssBaseline: { styleOverrides: {
      body: { background: '#f7f5f1' }, 'a': { color: '#644c80', textUnderlineOffset: 3 },
      ':focus-visible': { outline: '3px solid #70558e', outlineOffset: 4 }, '::selection': { background: '#e4d5ff', color: '#352147' },
      '@media (prefers-reduced-motion: reduce)': { '*, *::before, *::after': { animation: 'none !important', transition: 'none !important', scrollBehavior: 'auto !important' } },
    } },
  },
});
