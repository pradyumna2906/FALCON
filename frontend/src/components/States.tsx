import { Alert, Box, Button, CircularProgress, Typography } from '@mui/material';

export function LoadingState() {
  return <Box role="status" aria-live="polite" sx={{ p: 4 }}><CircularProgress aria-label="Loading" /><Typography>Restoring your secure session…</Typography></Box>;
}
export function ErrorState({ message = 'We could not load this page.' }: { message?: string }) {
  return <Box sx={{ p: 4 }}><Alert severity="error">{message}</Alert><Button onClick={() => window.location.reload()}>Try again</Button></Box>;
}
export function EmptyState({ title, detail }: { title: string; detail: string }) {
  return <Box sx={{ p: 3 }}><Typography component="h1" variant="h2">{title}</Typography><Typography sx={{ mt: 2 }}>{detail}</Typography></Box>;
}
