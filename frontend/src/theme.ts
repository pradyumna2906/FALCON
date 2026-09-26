import { createTheme } from '@mui/material/styles';

export const theme = createTheme({
  palette: { primary: { main: '#1565c0' }, secondary: { main: '#102a43' }, background: { default: '#f3f7fb', paper: '#ffffff' }, success: { main: '#087f70' } },
  shape: { borderRadius: 12 },
  typography: { fontFamily: 'Inter, system-ui, sans-serif', h1: { fontSize: '2.2rem', fontWeight: 750 }, h2: { fontSize: '1.5rem', fontWeight: 700 }, button: { textTransform: 'none' } },
  components: { MuiButton: { styleOverrides: { root: { minHeight: 44 } } }, MuiCssBaseline: { styleOverrides: {
    ':focus-visible': { outline: '3px solid #1565c0', outlineOffset: 3 },
    '@media (prefers-reduced-motion: reduce)': { '*, *::before, *::after': { animation: 'none !important', transition: 'none !important', scrollBehavior: 'auto !important' } },
  } } },
});
