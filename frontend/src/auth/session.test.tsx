import { afterEach, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SessionProvider, useSession } from './session';
import { queryClient } from '../api/query';

const user = { id: '6e9daa03-38ab-4511-a579-63de4bb1a2fe', email: 'synthetic@example.com', display_name: null, email_verified: true, timezone: 'UTC', default_currency: 'INR' };
const credentials = { access_token: 'synthetic', token_type: 'bearer', expires_at: '2026-09-26T18:00:00Z' };
const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200 });
afterEach(() => { vi.unstubAllGlobals(); queryClient.clear(); });

function Probe() {
  const { status, logout } = useSession();
  return <><span>{status}</span>{status === 'authenticated' && <button onClick={() => { void logout(); }}>Sign out</button>}</>;
}

it('preserves a revocation retry after private content unmounts and clears cached data', async () => {
  const fetcher = vi.fn().mockResolvedValueOnce(json(credentials)).mockResolvedValueOnce(json(user))
    .mockRejectedValueOnce(new TypeError('offline')).mockResolvedValueOnce(new Response(null, { status: 204 }));
  vi.stubGlobal('fetch', fetcher);
  queryClient.setQueryData(['private'], { balance: '123.45' });
  render(<SessionProvider><Probe /></SessionProvider>);
  await userEvent.click(await screen.findByRole('button', { name: 'Sign out' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('server sign-out could not be confirmed');
  expect(screen.getByText('anonymous')).toBeInTheDocument();
  expect(queryClient.getQueryData(['private'])).toBeUndefined();
  await userEvent.click(screen.getByRole('button', { name: 'Retry sign out' }));
  expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  expect(fetcher).toHaveBeenCalledTimes(4);
});
