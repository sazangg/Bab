import { MutationCache, QueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { getProblemDetail } from "@/shared/api/problem-detail";

export const queryClient = new QueryClient({
  mutationCache: new MutationCache({
    onError: (error, _variables, _context, mutation) => {
      if (mutation.options.onError) return;
      toast.error(getProblemDetail(error, "The action could not be completed."));
    },
  }),
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      retry: 1,
      staleTime: 30_000,
    },
  },
});
