import { QueryClient } from '@tanstack/react-query';

export function createQueryClient() {
  return new QueryClient({ defaultOptions: {
    queries: { staleTime: 30_000, gcTime: 300_000, retry: false, refetchOnWindowFocus: false },
    mutations: { retry: false },
  } });
}
export const queryClient = createQueryClient();
