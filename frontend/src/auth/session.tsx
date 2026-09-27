import { createContext, useContext, useEffect, useState, type ReactNode } from 'react';
import { api, type CurrentUser } from '../api/client';
import { queryClient } from '../api/query';
import { Alert, Button } from '@mui/material';

type Session = { status: 'loading' | 'anonymous' | 'authenticated' | 'error'; user: CurrentUser | null };
type SessionActions = { logout: () => Promise<void>; login: (email: string, password: string) => Promise<CurrentUser>; reloadUser: () => Promise<CurrentUser> };
const SessionContext = createContext<Session & SessionActions>({ status: 'loading', user: null, logout: async () => {}, login: async () => { throw new Error('Session unavailable'); }, reloadUser: async () => { throw new Error('Session unavailable'); } });

export function SessionProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session>({ status: 'loading', user: null });
  const [logoutFailed, setLogoutFailed] = useState(false);
  const login = async (email: string, password: string) => {
    const user = await api.login(email, password);
    setSession({ status: 'authenticated', user });
    return user;
  };
  const reloadUser = async () => {
    const user = await api.currentUser();
    setSession({ status: 'authenticated', user });
    return user;
  };
  const logout = async () => {
    try { await api.logout(); setLogoutFailed(false); }
    catch { setLogoutFailed(true); }
  };
  useEffect(() => {
    let live = true;
    let ended = false;
    api.setSessionEndHandler(() => {
      ended = true;
      queryClient.clear();
      if (live) setSession({ status: 'anonymous', user: null });
    });
    void (async () => {
      try {
        const restored = await api.refresh();
        const user = restored ? await api.currentUser() : null;
        if (live && !ended) setSession({ status: user ? 'authenticated' : 'anonymous', user });
      } catch {
        if (live && !ended) setSession({ status: 'error', user: null });
      }
    })();
    return () => { live = false; };
  }, []);
  return <SessionContext.Provider value={{ ...session, logout, login, reloadUser }}>
    {logoutFailed && <Alert severity="warning" action={<Button onClick={() => { void logout(); }}>Retry sign out</Button>}>Local data was cleared, but server sign-out could not be confirmed. Retry when connected.</Alert>}
    {children}
  </SessionContext.Provider>;
}

export function useSession() { return useContext(SessionContext); }
