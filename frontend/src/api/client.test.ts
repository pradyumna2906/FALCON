import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiClient, ApiError } from './client';

const credentials = { access_token: 'test-token', token_type: 'bearer', expires_at: '2026-09-26T18:00:00Z' };
const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } });
afterEach(() => vi.unstubAllGlobals());

describe('secure transport', () => {
  it('discards response bodies completed after sign-out', async () => {
    let resolve!: (value: unknown) => void;
    const body = new Promise(r => { resolve = r; });
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, status: 200, json: () => body }));
    const client = new ApiClient();
    const pending = client.request('/accounts');
    await Promise.resolve();
    client.clearSession();
    resolve({ items: ['private'] });
    await expect(pending).rejects.toMatchObject({ status: 401 });
  });

  it('reuses a rotated token when a stale unauthorized response arrives late', async () => {
    let resolve!: (value: Response) => void;
    const fetcher = vi.fn()
      .mockImplementationOnce(() => new Promise<Response>(r => { resolve = r; }))
      .mockResolvedValueOnce(json(credentials))
      .mockResolvedValueOnce(json({ items: [] }));
    vi.stubGlobal('fetch', fetcher);
    const client = new ApiClient();
    const pending = client.request('/accounts');
    await client.refresh();
    resolve(json({}, 401));
    expect(await pending).toEqual({ items: [] });
    expect(fetcher).toHaveBeenCalledTimes(3);
    expect(fetcher.mock.calls[2][1].headers.get('Authorization')).toBe('Bearer test-token');
  });

  it('coalesces refresh and keeps credentials out of browser storage', async () => {
    const fetcher = vi.fn().mockResolvedValue(json(credentials));
    vi.stubGlobal('fetch', fetcher);
    const client = new ApiClient();
    expect(await Promise.all([client.refresh(), client.refresh()])).toEqual([true, true]);
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
    fetcher.mockResolvedValue(json({ items: [] }));
    await client.request('/accounts');
    const init = fetcher.mock.calls[1][1];
    expect(init.headers.get('Authorization')).toBe('Bearer test-token');
    expect(init.credentials).toBe('include');
    expect(init.cache).toBe('no-store');
  });

  it('retries only once after authentication expiry', async () => {
    const fetcher = vi.fn().mockResolvedValueOnce(json({}, 401)).mockResolvedValueOnce(json(credentials)).mockResolvedValueOnce(json({}, 401));
    vi.stubGlobal('fetch', fetcher);
    const ended = vi.fn();
    const client = new ApiClient();
    client.setSessionEndHandler(ended);
    await expect(client.request('/accounts')).rejects.toBeInstanceOf(ApiError);
    expect(fetcher).toHaveBeenCalledTimes(3);
    expect(ended).toHaveBeenCalledTimes(1);
  });

  it.each([429, 500, 503])('does not replay writes on %s', async status => {
    const fetcher = vi.fn().mockResolvedValue(json({ secret: 'never echoed' }, status));
    vi.stubGlobal('fetch', fetcher);
    await expect(new ApiClient().request('/budgets', { method: 'POST', body: '{}' })).rejects.toMatchObject({ status });
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it('does not restore a token after session clearing', async () => {
    let resolve!: (value: Response) => void;
    const fetcher = vi.fn().mockImplementation(() => new Promise<Response>(r => { resolve = r; }));
    vi.stubGlobal('fetch', fetcher);
    const client = new ApiClient();
    const pending = client.refresh();
    client.clearSession();
    resolve(json(credentials));
    expect(await pending).toBe(false);
    fetcher.mockResolvedValue(json({}));
    await client.request('/accounts');
    expect(fetcher.mock.calls[1][1].headers.has('Authorization')).toBe(false);
  });

  it('clears caches on logout even if revocation fails', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('offline')));
    const ended = vi.fn();
    const client = new ApiClient();
    client.setSessionEndHandler(ended);
    await expect(client.logout()).rejects.toThrow('offline');
    expect(ended).toHaveBeenCalledOnce();
  });

  it.each(['https://evil.test', '//evil.test', '/../secrets', '/accounts\\evil'])('rejects unsafe URL %s', async path => {
    const fetcher = vi.fn();
    vi.stubGlobal('fetch', fetcher);
    await expect(new ApiClient().request(path)).rejects.toThrow('Invalid API path');
    expect(fetcher).not.toHaveBeenCalled();
  });

  it('handles no-content responses', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(null, { status: 204 })));
    expect(await new ApiClient().request('/budgets/test', { method: 'DELETE' })).toBeUndefined();
  });
});
