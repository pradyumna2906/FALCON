import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { CssBaseline, ThemeProvider } from '@mui/material';
import { QueryClientProvider } from '@tanstack/react-query';
import { RouterProvider } from 'react-router/dom';
import { router } from './App';
import { SessionProvider } from './auth/session';
import { queryClient } from './api/query';
import { theme } from './theme';

createRoot(document.getElementById('root')!).render(
  <StrictMode><ThemeProvider theme={theme}><CssBaseline />
    <QueryClientProvider client={queryClient}><SessionProvider><RouterProvider router={router} /></SessionProvider></QueryClientProvider>
  </ThemeProvider></StrictMode>,
);
