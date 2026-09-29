import { test, expect } from '@playwright/test';

test('onboard, import, correct and review in the production browser build', async ({ page }) => {
  // Synthetic API fixtures isolate browser behavior. PostgreSQL API integration
  // is independently exercised by test_postgresql_frontend_workflow.py.
  const owner = { id: 'aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa', email: 'synthetic@example.com', email_verified: true, timezone: 'UTC', default_currency: 'INR', display_name: 'Synthetic' };
  const account = { id: 'bbbbbbbb-bbbb-4bbb-bbbb-bbbbbbbbbbbb', name: 'Synthetic bank', account_type: 'bank', currency: 'INR', opening_balance: '0', opening_balance_date: '2026-09-01', institution_name: null, masked_reference: null, created_at: '2026-09-01T00:00:00Z', updated_at: '2026-09-01T00:00:00Z' };
  const category = { id: 'cccccccc-cccc-4ccc-cccc-cccccccccccc', name: 'Food', kind: 'expense', classification_code: 'groceries', is_system: true, display_order: 0, parent_id: null };
  let hasAccount = false, imported = false, corrected = false;
  let profile: Record<string, unknown> | null = null;
  let loggedIn = false;
  const transaction = { id: 'dddddddd-dddd-4ddd-dddd-dddddddddddd', account_id: account.id, category_id: null as string | null, transaction_type: 'expense', amount: '123.4567', transaction_date: '2026-09-01', description: 'Synthetic groceries', source_type: 'import', status: 'posted', merchant_name: null };
  const job = { id: 'eeeeeeee-eeee-4eee-eeee-eeeeeeeeeeee', original_filename: 'synthetic.csv', status: 'partial', accepted_count: 1, rejected_count: 1, balance_reconciled: null, issues: [{ row_number: 3, code: 'zero_amount', message: 'Amount must not be zero.' }], issues_truncated: false, created_at: '2026-09-01T00:00:00Z' };
  const unexpected: string[] = [];
  await page.route('**/api/v1/**', async route => {
    const request = route.request(); const url = new URL(request.url()); const path = url.pathname.replace('/api/v1', ''); const method = request.method();
    const reply = (body: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: status === 204 ? undefined : JSON.stringify(body) });
    if (path === '/auth/refresh') return reply({}, 401);
    if (path === '/auth/login') { loggedIn = true; return reply({ access_token: 'synthetic-only', token_type: 'bearer', expires_at: '2026-09-28T12:00:00Z' }); }
    if (path === '/auth/me') return reply(owner, loggedIn ? 200 : 401);
    if (path === '/auth/logout') { loggedIn = false; return reply(null, 204); }
    if (path === '/profile') { if (method === 'PUT') { profile = { ...request.postDataJSON(), id: owner.id, completion_status: 'complete', updated_at: '2026-09-01T00:00:00Z' }; return reply(profile, 201); } return reply(profile || {}, profile ? 200 : 404); }
    if (path === '/accounts') { if (method === 'POST') { hasAccount = true; return reply(account, 201); } return reply({ items: hasAccount ? [account] : [] }); }
    if (path === '/categories') return reply({ items: [category] });
    if (path === '/transactions') return reply({ items: imported ? [{ ...transaction, category_id: corrected ? category.id : null }] : [], next_cursor: null });
    if (path.endsWith('/classification')) return reply({});
    if (path.endsWith('/classification/correction')) { expect(request.postDataJSON()).toEqual({ category_id: category.id }); corrected = true; return reply({}); }
    if (path === '/imports') { if (method === 'POST') { expect(request.postData()).toContain('synthetic.csv'); imported = true; return reply(job, 201); } return reply({ items: imported ? [job] : [], has_more: false }); }
    if (path === `/imports/${job.id}`) return reply(job);
    if (path === '/goals') return reply({ items: [] });
    if (path === '/analytics/health-score') return reply({ score: null, status: 'unavailable', explanation: 'More history is required.', factors: [] });
    if (path === '/analytics/insights') return reply({ explanation: 'No supported insights yet.', insights: [] });
    if (path === '/analytics/dashboard') {
      const amount = imported ? '123.4567' : '0.0000';
      return reply({ context: { currency: 'INR', period: { timezone: 'UTC' }, freshness: { calculated_at: '2026-09-01T12:00:00Z', source_last_updated_at: imported ? '2026-09-01T12:00:00Z' : null }, completeness: { data_confidence: 'low', eligible_transaction_count: imported ? 1 : 0, exclusions: { other_currency_count: 0, pending_count: 0, transfer_entry_count: 0, adjustment_count: 0 } } }, metrics: { gross_income: { value: '0.0000' }, total_expense: { value: amount }, net_cash_flow: { value: imported ? '-123.4567' : '0.0000' }, savings_amount: { value: imported ? '-123.4567' : '0.0000' } }, series: [], spending: { categories: corrected ? [{ category_id: category.id, name: 'Food', amount: { value: amount }, share: { value: '1.000000' } }] : [] } });
    }
    unexpected.push(`${method} ${path}`); return reply({}, 500);
  });
  await page.goto('/sign-in');
  await page.getByLabel('Email', { exact: false }).fill(owner.email);
  await page.getByLabel('Password', { exact: false }).fill('Synthetic-Password-2026!');
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Your financial overview' })).toBeVisible();
  await page.getByRole('link', { name: 'Complete setup' }).click();
  await page.getByRole('button', { name: 'Save profile' }).click();
  await expect.poll(() => profile?.completion_status).toBe('complete');
  await page.getByRole('link', { name: 'Add an account' }).click();
  await page.getByLabel('Account name', { exact: false }).fill('Synthetic bank');
  await page.getByRole('button', { name: 'Create account' }).click();
  await expect(page.getByRole('heading', { name: 'Synthetic bank', exact: true })).toBeVisible();
  await page.getByRole('tab', { name: 'imports', exact: true }).click();
  await page.getByRole('combobox', { name: 'Import account' }).click();
  await page.getByRole('option', { name: 'Synthetic bank (INR)' }).click();
  await page.getByLabel('Statement file').setInputFiles({ name: 'synthetic.csv', mimeType: 'text/csv', buffer: Buffer.from('Date,Description,Amount\n2026-09-01,Synthetic groceries,-123.4567\n2026-09-01,Zero,0') });
  await page.getByRole('button', { name: 'Review import' }).click();
  expect(imported).toBe(false);
  await page.getByRole('button', { name: 'Import statement', exact: true }).click();
  await expect(page.getByText('Amount must not be zero.')).toBeVisible();
  await page.getByRole('link', { name: 'Review imported transactions' }).click();
  await page.getByRole('combobox', { name: 'Reviewed category' }).click();
  await page.getByRole('option', { name: 'Food (expense)' }).click();
  await page.getByRole('button', { name: 'Apply correction' }).click();
  await expect.poll(() => corrected).toBe(true);
  await page.getByRole('link', { name: 'Overview', exact: true }).click();
  await expect(page.getByText('INR 123.4567', { exact: true })).toBeVisible();
  await page.screenshot({ path: 'test-results/batch2-desktop.png', fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByRole('button', { name: 'Open navigation' })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: 'test-results/batch2-mobile.png', fullPage: true });
  await page.getByRole('button', { name: 'Sign out', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Sign in', exact: true })).toBeVisible();
  expect(await page.evaluate(() => localStorage.length + sessionStorage.length)).toBe(0);
  expect(unexpected).toEqual([]);
});
