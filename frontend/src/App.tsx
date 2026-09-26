import { useState } from 'react';
import { AppBar, Box, Button, Chip, Container, Drawer, List, ListItemButton, ListItemText, Paper, Stack, Toolbar, Typography } from '@mui/material';
import { createBrowserRouter, Link, Navigate, Outlet } from 'react-router';
import { useSession } from './auth/session';
import { EmptyState, ErrorState, LoadingState } from './components/States';

export const navigation = [
  ['overview', 'Overview'], ['money', 'Money'], ['analytics', 'Analytics'],
  ['forecasts', 'Forecasts'], ['goals', 'Goals & Plans'], ['scenarios', 'Scenarios'],
  ['assistant', 'Assistant'], ['reports', 'Reports'], ['settings', 'Settings'],
] as const;

export function RequireSession() {
  const { status, user } = useSession();
  if (status === 'loading') return <LoadingState />;
  if (status === 'error') return <ErrorState message="The API is unavailable. Your financial information has not been loaded." />;
  if (status === 'anonymous') return <Navigate to="/sign-in" replace />;
  if (!user?.email_verified) return <Navigate to="/verify-email" replace />;
  return <Outlet />;
}

function Shell() {
  const [open, setOpen] = useState(false);
  const { user, logout } = useSession();
  const links = <Box component="nav" aria-label="Main navigation" sx={{ width: 230, p: 2 }}>
    <Typography variant="h2" sx={{ p: 2 }}>FALCON</Typography>
    <List>{navigation.map(([path, label]) => <ListItemButton key={path} component={Link} to={`/app/${path}`} onClick={() => setOpen(false)} sx={{ minHeight: 44 }}><ListItemText primary={label} /></ListItemButton>)}</List>
  </Box>;
  return <Box sx={{ display: 'flex', minHeight: '100vh' }}>
    <Box component="a" href="#main" sx={{ position: 'absolute', left: -1000, '&:focus': { left: 12, top: 12, zIndex: 1500, bgcolor: 'white', p: 2 } }}>Skip to content</Box>
    <Box sx={{ display: { xs: 'none', md: 'block' }, bgcolor: 'secondary.main', color: 'white' }}>{links}</Box>
    <Drawer open={open} onClose={() => setOpen(false)}>{links}</Drawer>
    <Box sx={{ flex: 1, minWidth: 0 }}>
      <AppBar position="static" color="inherit" elevation={0}><Toolbar sx={{ gap: 2 }}>
        <Button sx={{ display: { md: 'none' } }} onClick={() => setOpen(true)} aria-label="Open navigation">Menu</Button>
        <Typography sx={{ flex: 1 }}>{user?.display_name || 'Your workspace'}</Typography>
        <Chip label="Foundation preview" size="small" />
        <Button onClick={() => { void logout(); }}>Sign out</Button>
      </Toolbar></AppBar>
      <Container component="main" id="main" tabIndex={-1} sx={{ py: 4 }}>
        <Outlet />
      </Container>
    </Box>
  </Box>;
}

function Introduction() {
  return <Container component="main" maxWidth="md" sx={{ py: { xs: 5, md: 10 } }}>
    <Typography sx={{ color: 'primary.main', letterSpacing: 3, fontWeight: 800 }}>FALCON</Typography>
    <Typography variant="h1" sx={{ my: 3 }}>Understand today.<br />Plan your financial future.</Typography>
    <Typography sx={{ maxWidth: 650, mb: 4 }}>A private workspace for your transactions, financial goals and evidence-grounded guidance. Built for regular and irregular income.</Typography>
    <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}>
      {['Understand your spending', 'Compare future scenarios', 'Plan multiple goals'].map(title => <Paper key={title} variant="outlined" sx={{ p: 3, flex: 1 }}><Typography variant="h2">{title}</Typography></Paper>)}
    </Stack>
    <Paper sx={{ p: 3, mt: 4 }}><Typography>This is the Phase 13 foundation preview. No example figures are presented as your financial data. Sign-in and onboarding screens arrive in Batch 2.</Typography><Button component={Link} to="/app/overview" sx={{ mt: 2 }}>Open workspace</Button></Paper>
  </Container>;
}

export const routes = [
  { path: '/', element: <Introduction />, errorElement: <ErrorState /> },
  { path: '/sign-in', element: <EmptyState title="Sign in" detail="Authentication screens are scheduled for Batch 2. No credentials are collected by this preview." /> },
  { path: '/verify-email', element: <EmptyState title="Verify your email" detail="Verification is required before accessing the workspace. The verification screen arrives in Batch 2." /> },
  { element: <RequireSession />, errorElement: <ErrorState />, children: [
    { path: '/app', element: <Shell />, children: [
      { index: true, element: <Navigate to="overview" replace /> },
      ...navigation.map(([path, title]) => ({ path, element: <Paper><EmptyState title={title} detail="This authenticated section is reserved for an approved later checkpoint. No financial results have been generated." /></Paper> })),
    ] },
  ] },
  { path: '*', element: <EmptyState title="Page not found" detail="Return to the home page to continue." /> },
];
export const router = createBrowserRouter(routes);
