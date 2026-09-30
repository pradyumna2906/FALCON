import { lazy, Suspense, useState } from 'react';
import { AppBar, Avatar, Box, Button, Container, Drawer, List, ListItemButton, ListItemText, Paper, Stack, Toolbar, Typography } from '@mui/material';
import { createBrowserRouter, Link, Navigate, NavLink, Outlet, useLocation } from 'react-router';
import { Brand, FeatureIcon } from './components/Brand';
import { useSession } from './auth/session';
import { EmptyState, ErrorState, LoadingState } from './components/States';

const AuthPage = lazy(() => import('./pages/Auth'));
const Overview = lazy(() => import('./pages/Overview'));
const Onboarding = lazy(() => import('./pages/Onboarding'));
const Money = lazy(() => import('./pages/Money'));
const Analytics = lazy(() => import('./pages/Analytics'));
const Forecasts = lazy(() => import('./pages/Forecasts'));
const Goals = lazy(() => import('./pages/Goals'));
const Scenarios = lazy(() => import('./pages/Scenarios'));
const Assistant = lazy(() => import('./pages/Assistant'));
const Reports = lazy(() => import('./pages/Reports'));
const Settings = lazy(() => import('./pages/Settings'));

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
  const location = useLocation();
  const section = navigation.find(([path]) => location.pathname === `/app/${path}`)?.[1] || 'Setup';
  const links = <Box component="nav" aria-label="Main navigation" sx={{ width: 256, minHeight: '100dvh', p: 2.5, bgcolor: '#292239', color: '#fff', display: 'flex', flexDirection: 'column' }}>
    <Box sx={{ pt: 1.5, pb: 4 }}><Brand light /></Box>
    <Typography sx={{ fontSize: '.65rem', letterSpacing: '.14em', color: '#bcb0ce', px: 1.5, mb: 1 }}>DAILY FINANCES</Typography>
    <List sx={{ display: 'grid', gap: .5 }}>{navigation.map(([path, label], i) => <Box key={path}>{(i === 3 || i === 6) && <Typography sx={{ mt: 2.5, mb: 1, px: 1.5, fontSize: '.65rem', letterSpacing: '.12em', color: '#bcb0ce' }}>{i === 3 ? 'PLAN AHEAD' : 'TOOLS & ACCOUNT'}</Typography>}<ListItemButton key={path} component={NavLink} to={`/app/${path}`} onClick={() => setOpen(false)} sx={{ borderRadius: 2, minHeight: 48, gap: 1.5, color: '#d8cfe3', '&:hover': { bgcolor: '#393046' }, '&.active': { bgcolor: '#d3e7dc', color: '#213b33', '& .MuiListItemText-primary': { fontWeight: 800 } }, mt: 0 }}><FeatureIcon name={path} /><ListItemText primary={label} slotProps={{ primary: { sx: { fontSize: '.88rem', fontWeight: 550 } } }} /></ListItemButton></Box>)}</List>

  </Box>;
  return <Box sx={{ display: 'flex', minHeight: '100vh' }}>
    <Box component="a" href="#main" sx={{ position: 'absolute', left: -1000, '&:focus': { left: 12, top: 12, zIndex: 1500, bgcolor: 'white', p: 2 } }}>Skip to content</Box>
    <Box sx={{ display: { xs: 'none', md: 'block' }, position: 'sticky', top: 0, height: '100dvh', overflowY: 'auto', flexShrink: 0 }}>{links}</Box>
    <Drawer open={open} onClose={() => setOpen(false)} slotProps={{ paper: { sx: { borderRadius: 0, bgcolor: '#292239' } } }}>{links}</Drawer>
    <Box sx={{ flex: 1, minWidth: 0 }}>
      <AppBar position="static" color="inherit" elevation={0} sx={{ borderRadius: 0, borderWidth: '0 0 1px', bgcolor: '#ffffffb8' }}><Toolbar sx={{ gap: { xs: .5, sm: 1.5 }, minHeight: { sm: 78 }, px: { xs: 2, lg: 4 } }}>
        <Button sx={{ display: { md: 'none' } }} onClick={() => setOpen(true)} aria-label="Open navigation">Menu</Button>
        <Box sx={{ flex: 1, minWidth: 0 }}><Typography sx={{ fontSize: '.74rem', color: 'text.secondary', display: { xs: 'none', sm: 'block' } }}>Your workspace / {section}</Typography><Typography sx={{ fontWeight: 700, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{user?.display_name || 'Your workspace'}</Typography></Box>
        <Button component={Link} to="/app/onboarding">Setup</Button>
        <Button onClick={() => { void logout(); }} sx={{ color: 'text.secondary' }}>Sign out</Button>
        <Avatar sx={{ display: { xs: 'none', sm: 'flex' }, bgcolor: '#eadff9', color: '#644c80', width: 38, height: 38, fontSize: '.9rem', fontWeight: 800 }} aria-hidden="true">{(user?.display_name || 'F').slice(0, 1).toUpperCase()}</Avatar>
      </Toolbar></AppBar>
      <Container component="main" id="main" tabIndex={-1} maxWidth="lg" sx={{ py: { xs: 3, md: 4 }, px: { xs: 2, lg: 4 } }}>
        <Suspense fallback={<LoadingState />}><Outlet /></Suspense>
      </Container>
    </Box>
  </Box>;
}

function Introduction() {
  return <Container component="main" maxWidth="lg" sx={{ py: { xs: 3, md: 5 } }}>
    <Stack direction="row" sx={{ justifyContent: 'space-between', alignItems: 'center' }}><Brand /><Button component={Link} to="/sign-in" variant="outlined">Sign in</Button></Stack>
    <Box sx={{ my: { xs: 5, md: 9 }, p: { xs: 3, md: 7 }, bgcolor: '#292239', borderRadius: 6, color: '#fff', position: 'relative', overflow: 'hidden', backgroundImage: 'none' }}>
      <Typography sx={{ color: '#d3e7dc', letterSpacing: '.16em', fontSize: '.75rem', fontWeight: 700 }}>LESS GUESSWORK. MORE POSSIBILITY.</Typography>
      <Typography variant="h1" sx={{ my: 3, maxWidth: 740, fontSize: { xs: '2.25rem', md: '3.6rem' }, lineHeight: 1.08 }}>Understand today.<br /><Box component="span" sx={{ color: '#d2c3e3' }}>Plan your financial future.</Box></Typography>
      <Typography sx={{ maxWidth: 560, mb: 4, color: '#e0d8eb', fontSize: '1.05rem' }}>Bring your money, goals and possibilities into one clear picture. Built for life with regular or irregular income.</Typography>
      <Button component={Link} to="/register" variant="contained" endIcon={<FeatureIcon name="arrow" />} sx={{ bgcolor: '#d3e7dc', color: '#243b32', '&:hover': { bgcolor: '#bfd8ca' } }}>Get started</Button>
      <Typography sx={{ mt: 2, color: '#cbbfd9', fontSize: '.8rem' }}>Your own records. Evidence-grounded guidance.</Typography>
    </Box>
    <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2.5}>
      {[
        { title: 'Understand your spending', icon: 'analytics', color: '#edf4ef', detail: 'Spot patterns, review subscriptions and see where your money goes.' },
        { title: 'Compare future scenarios', icon: 'scenarios', color: '#f1edf5', detail: 'Explore what could change before making your next decision.' },
        { title: 'Plan multiple goals', icon: 'goals', color: '#f8f2e6', detail: 'Find a practical balance between the things that matter to you.' },
      ].map(item => <Paper key={item.title} sx={{ p: 3.5, flex: 1 }}><Box sx={{ bgcolor: item.color, width: 48, height: 48, borderRadius: 3, display: 'grid', placeItems: 'center', mb: 3 }}><FeatureIcon name={item.icon} /></Box><Typography variant="h2">{item.title}</Typography><Typography color="text.secondary" sx={{ mt: 1.5 }}>{item.detail}</Typography></Paper>)}
    </Stack>
    <Typography color="text.secondary" sx={{ mt: 4, textAlign: 'center', fontSize: '.85rem' }}>No example figures are presented as your financial data. Create an account, verify your email and connect your financial records.</Typography>
  </Container>;
}

export const routes = [
  { path: '/', element: <Introduction />, errorElement: <ErrorState /> },
  ...(['sign-in', 'register', 'verify-email', 'forgot-password', 'reset-password'] as const).map(mode => ({ path: `/${mode}`, element: <Suspense fallback={<LoadingState />}><AuthPage key={mode} mode={mode} /></Suspense>, errorElement: <ErrorState /> })),
  { element: <RequireSession />, errorElement: <ErrorState />, children: [
    { path: '/app', element: <Shell />, children: [
      { index: true, element: <Navigate to="overview" replace /> },
      { path: 'overview', element: <Overview /> },
      { path: 'money', element: <Money /> },
      { path: 'analytics', element: <Analytics /> },
      { path: 'forecasts', element: <Forecasts /> },
      { path: 'goals', element: <Goals /> },
      { path: 'scenarios', element: <Scenarios /> },
      { path: 'assistant', element: <Assistant /> },
      { path: 'reports', element: <Reports /> },
      { path: 'settings', element: <Settings /> },
      { path: 'onboarding', element: <Onboarding /> },
    ] },
  ] },
  { path: '*', element: <EmptyState title="Page not found" detail="Return to the home page to continue." /> },
];
export const router = createBrowserRouter(routes);
