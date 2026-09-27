import { z } from 'zod';
import type { components } from './generated';

export type CurrentUser = components['schemas']['CurrentUserResponse'];
const credentialSchema = z.object({
  access_token: z.string().min(1), token_type: z.literal('bearer'),
  expires_at: z.string().datetime({ offset: true }),
});
const userSchema = z.object({
  id: z.string().uuid(), email: z.string(), display_name: z.string().nullable(),
  timezone: z.string(), default_currency: z.string(), email_verified: z.boolean(),
});

export class ApiError extends Error {
  constructor(public status: number, public requestId: string | null) {
    super(status === 401 ? 'Sign-in failed or your session expired. Check your credentials and sign in again.' : status === 403 ? 'Verify your email before accessing financial data.' : status === 409 ? 'This conflicts with an existing record. Refresh and review before retrying.' : status === 422 ? 'Check the entered values, dates and category compatibility.' : status === 413 ? 'The file exceeds the supported upload size.' : status === 415 ? 'This file format is not supported.' : status === 429 ? 'Too many requests. Please try again shortly.' : 'The request could not be completed.');
  }
}

// Same-origin requests only: no configurable URL can receive bearer credentials.
export class ApiClient {
  private token: string | null = null;
  private generation = 0;
  private refreshing: Promise<boolean> | null = null;
  private onSessionEnd: () => void = () => {};

  setSessionEndHandler(handler: () => void) { this.onSessionEnd = handler; }
  async login(email: string, password: string): Promise<CurrentUser> {
    this.clearSession();
    // Finish any previous rotation before issuing a new login cookie.
    try { await this.refreshing; } catch { /* Login can recover a failed restore. */ }
    const generation = this.generation;
    const result = await this.request('/auth/login', { method: 'POST', body: JSON.stringify({ email, password }) }, false);
    if (generation !== this.generation) throw new ApiError(401, null);
    this.token = credentialSchema.parse(result).access_token;
    return this.currentUser();
  }
  clearSession() {
    this.generation += 1;
    this.token = null;
    this.onSessionEnd();
  }

  async refresh(): Promise<boolean> {
    if (this.refreshing) return this.refreshing;
    const generation = this.generation;
    const refresh = (async () => {
      const response = await fetch('/api/v1/auth/refresh', {
        method: 'POST', credentials: 'include', cache: 'no-store',
        headers: { 'X-Request-ID': crypto.randomUUID() },
      });
      if (generation !== this.generation) return false;
      if (response.status === 401) { this.clearSession(); return false; }
      if (!response.ok) throw new ApiError(response.status, response.headers.get('X-Request-ID'));
      const credentials = credentialSchema.parse(await response.json());
      if (generation !== this.generation) return false;
      this.token = credentials.access_token;
      return true;
    })();
    this.refreshing = refresh;
    try { return await refresh; }
    finally { if (this.refreshing === refresh) this.refreshing = null; }
  }

  async request<T>(path: string, init: RequestInit = {}, retry = true): Promise<T> {
    if (!/^\/[a-zA-Z0-9]/.test(path) || path.includes('\\') || path.includes('..')) throw new Error('Invalid API path');
    const generation = this.generation;
    const headers = new Headers(init.headers);
    const token = this.token;
    headers.delete('Authorization');
    if (this.token) headers.set('Authorization', `Bearer ${this.token}`);
    headers.set('X-Request-ID', crypto.randomUUID());
    if (init.body && !(init.body instanceof FormData)) headers.set('Content-Type', 'application/json');
    const response = await fetch(`/api/v1${path}`, { ...init, headers, credentials: 'include', cache: 'no-store' });
    if (generation !== this.generation) throw new ApiError(401, null);
    if (response.status === 401 && retry && (this.token !== token || await this.refresh())) return this.request<T>(path, init, false);
    if (!response.ok) {
      if (response.status === 401) this.clearSession();
      throw new ApiError(response.status, response.headers.get('X-Request-ID'));
    }
    const result = response.status === 204 ? undefined as T : await response.json() as T;
    if (generation !== this.generation) throw new ApiError(401, null);
    return result;
  }

  async currentUser(): Promise<CurrentUser> {
    return userSchema.parse(await this.request('/auth/me'));
  }

  async logout() {
    const pendingRefresh = this.refreshing;
    this.clearSession();
    // Let an in-flight cookie rotation finish before revoking that cookie.
    try { await pendingRefresh; } catch { /* Still attempt server revocation. */ }
    const response = await fetch('/api/v1/auth/logout', { method: 'POST', credentials: 'include', cache: 'no-store' });
    if (!response.ok) throw new ApiError(response.status, response.headers.get('X-Request-ID'));
  }
}

export const api = new ApiClient();
