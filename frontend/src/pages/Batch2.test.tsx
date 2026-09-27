import { afterEach, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, within, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router';
import { createQueryClient } from '../api/query';
import { money } from '../api/finance';
import AuthPage from './Auth';
import Accounts from './money/Accounts';
import Transactions, { Transfers } from './money/Transactions';
import Imports from './money/Imports';
import Overview from './Overview';
import type { ReactNode } from 'react';

const owner = { id: 'aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa', email: 'synthetic@example.com', email_verified: true, timezone: 'Asia/Kolkata', default_currency: 'INR', display_name: 'Synthetic' };
const session = vi.hoisted(() => ({ login: vi.fn(), logout: vi.fn(), reloadUser: vi.fn() }));
vi.mock('../auth/session', () => ({ useSession: () => ({ status: 'authenticated', user: owner, ...session }) }));
const account = { id: 'bbbbbbbb-bbbb-4bbb-bbbb-bbbbbbbbbbbb', name: 'Synthetic bank', currency: 'INR', account_type: 'bank', opening_balance: '0.0000', opening_balance_date: '2026-09-01', institution_name: null, masked_reference: null, created_at: '2026-09-01T00:00:00Z', updated_at: '2026-09-01T00:00:00Z' };
const category = { id: 'cccccccc-cccc-4ccc-cccc-cccccccccccc', name: 'Food', kind: 'expense', classification_code: 'groceries', is_system: true, display_order: 0, parent_id: null };
const response = (body: unknown, status = 200) => new Response(status === 204 ? null : JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
const caches: ReturnType<typeof createQueryClient>[] = [];
afterEach(() => { vi.unstubAllGlobals(); caches.forEach(cache => cache.clear()); caches.length = 0; vi.clearAllMocks(); });
function show(element: ReactNode) {
  const cache = createQueryClient(); caches.push(cache);
  return render(<QueryClientProvider client={cache}><MemoryRouter>{element}</MemoryRouter></QueryClientProvider>);
}
async function choose(form: HTMLElement, label: string, option: string) {
  await userEvent.click(within(form).getByRole('combobox', { name: label }));
  await userEvent.click(await screen.findByRole('option', { name: option }));
}

it('formats decimal amounts without losing precision', () => {
  expect(money('999999999999999.1234', 'INR')).toBe('INR 999,999,999,999,999.1234');
  expect(money(null, 'INR')).toBe('Unavailable');
});

it('creates an account using the owner-free API contract', async () => {
  const fetcher = vi.fn(async (_url: string, init?: RequestInit) => response(init?.method === 'POST' ? account : { items: [] }, init?.method === 'POST' ? 201 : 200));
  vi.stubGlobal('fetch', fetcher); show(<Accounts />);
  const form = screen.getByRole('form', { name: 'Add account' });
  await userEvent.type(within(form).getByLabelText(/Account name/), 'Synthetic bank');
  await userEvent.click(within(form).getByRole('button', { name: 'Create account' }));
  await screen.findByText('Request completed.');
  const call = fetcher.mock.calls.find(([, init]) => init?.method === 'POST');
  expect(call?.[0]).toBe('/api/v1/accounts');
  const payload = JSON.parse(call?.[1]?.body as string);
  expect(payload).toMatchObject({ name: 'Synthetic bank', account_type: 'bank', currency: 'INR', opening_balance: '0' });
  expect(payload).not.toHaveProperty('user_id');
});

it('preserves decimal strings when recording transactions and invalidates history', async () => {
  let written = false;
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === '/api/v1/accounts') return response({ items: [account] });
    if (url === '/api/v1/categories') return response({ items: [category] });
    if (init?.method === 'POST') { written = true; return response({}, 201); }
    if (url.startsWith('/api/v1/transactions?')) return response({ items: [], next_cursor: null });
    throw new Error(`Unexpected request: ${url}`);
  });
  vi.stubGlobal('fetch', fetcher); show(<Transactions />);
  const form = await screen.findByRole('form', { name: 'Add transaction' });
  await userEvent.type(within(form).getByLabelText(/^Amount/), '123.4567');
  await userEvent.type(within(form).getByLabelText(/^Description/), 'Synthetic lunch');
  await userEvent.click(within(form).getByRole('button', { name: 'Record transaction' }));
  await waitFor(() => expect(written).toBe(true));
  const payload = JSON.parse(fetcher.mock.calls.find(([, init]) => init?.method === 'POST')?.[1]?.body as string);
  expect(payload.amount).toBe('123.4567'); expect(payload.account_id).toBe(account.id);
  await waitFor(() => expect(fetcher.mock.calls.filter(([url]) => url.startsWith('/api/v1/transactions?')).length).toBeGreaterThan(1));
});

it.each([false, true])('corrects imported transactions with stored provenance (already corrected: %s)', async (alreadyCorrected) => {
  const transaction = { id: 'dddddddd-dddd-4ddd-dddd-dddddddddddd', account_id: account.id, category_id: alreadyCorrected ? category.id : null, is_user_modified: alreadyCorrected, amount: '20.0000', transaction_date: '2026-09-01', transaction_type: 'expense', description: 'Imported groceries', source_type: 'import', status: 'posted' };
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith('/accounts')) return response({ items: [account] });
    if (url.endsWith('/categories')) return response({ items: [category] });
    if (init?.method === 'POST') return response({});
    return response({ items: [transaction], next_cursor: null });
  });
  vi.stubGlobal('fetch', fetcher); show(<Transactions />);
  await screen.findByText('Imported groceries');
  expect(screen.queryByRole('button', { name: 'Edit transaction' })).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Delete transaction' })).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole('combobox', { name: 'Reviewed category' }));
  await userEvent.click(screen.getByRole('option', { name: 'Food (expense)' }));
  await userEvent.click(screen.getByRole('button', { name: 'Apply correction' }));
  await waitFor(() => expect(fetcher.mock.calls.some(([url, init]) => url.endsWith('/classification/correction') && init?.body === JSON.stringify({ category_id: category.id }))).toBe(true));
  expect(fetcher.mock.calls.filter(([, init]) => init?.method === 'POST').map(([url]) => url.split('/').at(-1))).toEqual(alreadyCorrected ? ['correction'] : ['classification', 'correction']);
});

it('requires confirmation before uploading a statement and shows row rejections', async () => {
  const job = { id: 'eeeeeeee-eeee-4eee-eeee-eeeeeeeeeeee', original_filename: 'synthetic.csv', status: 'partial', accepted_count: 1, rejected_count: 1, balance_reconciled: null, issues: [{ row_number: 3, code: 'zero_amount', message: 'Amount must not be zero.' }], issues_truncated: false };
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith('/accounts')) return response({ items: [account] });
    if (init?.method === 'POST') return response(job, 201);
    if (url.startsWith('/api/v1/imports?')) return response({ items: [], has_more: false });
    return response(job);
  });
  vi.stubGlobal('fetch', fetcher); show(<Imports />);
  const form = await screen.findByRole('form', { name: '1. Select statement' });
  await choose(form, 'Import account', 'Synthetic bank (INR)');
  await userEvent.upload(screen.getByLabelText('Statement file'), new File(['date,description,amount\n2026-09-01,Test,-20'], 'synthetic.csv', { type: 'text/csv' }));
  // jsdom does not integrate user-event's synthetic FileList with native validity.
  fireEvent.submit(form);
  expect(fetcher.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(0);
  await userEvent.click(screen.getByRole('button', { name: 'Import statement' }));
  await screen.findByText('Amount must not be zero.');
  const upload = fetcher.mock.calls.find(([, init]) => init?.method === 'POST')?.[1];
  expect(upload?.body).toBeInstanceOf(FormData);
  expect((upload?.headers as Headers).has('Content-Type')).toBe(false);
  expect((upload?.body as FormData).has('file_password')).toBe(false);
});

it('keeps server errors visible without replaying a transfer', async () => {
  const fetcher = vi.fn(async (_url: string, init?: RequestInit) => init?.method === 'POST' ? response({}, 409) : response({ items: [account, { ...account, id: category.id, name: 'Wallet' }] }));
  vi.stubGlobal('fetch', fetcher); show(<Transfers />);
  const form = await screen.findByRole('form', { name: 'Internal transfer' });
  await choose(form, 'From account', 'Synthetic bank (INR)'); await choose(form, 'To account', 'Wallet (INR)');
  await userEvent.type(within(form).getByLabelText(/^Amount/), '10'); await userEvent.type(within(form).getByLabelText(/Transfer description/), 'Synthetic transfer');
  await userEvent.click(within(form).getByRole('button', { name: 'Record transfer' }));
  await screen.findByText(/conflicts with an existing record/);
  expect(fetcher.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(1);
});

it('uses enumeration-resistant recovery feedback without claiming delivery', async () => {
  const fetcher = vi.fn().mockResolvedValue(response({ status: 'accepted' }, 202));
  vi.stubGlobal('fetch', fetcher); show(<AuthPage mode="forgot-password" />);
  await userEvent.type(screen.getByLabelText(/^Email/), owner.email);
  await userEvent.click(screen.getByRole('button', { name: 'Request reset' }));
  await screen.findByText(/If the account is eligible/);
  expect(fetcher).toHaveBeenCalledTimes(1);
});

it('does not show made-up overview totals when the API is unavailable', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response({}, 503)));
  show(<Overview />);
  await waitFor(() => expect(screen.getAllByRole('alert').length).toBeGreaterThan(0));
  expect(screen.queryByText('INR 0.0000')).not.toBeInTheDocument();
});
