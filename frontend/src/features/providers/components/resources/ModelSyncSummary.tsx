import type { SyncProviderModelOfferingsResponse } from "@/shared/api/generated/schemas";

import { formatRelativeFromNow } from "../../lib/format";

export function ModelSyncSummary({ result }: { result: SyncProviderModelOfferingsResponse }) {
  const summary = result.summary;
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 rounded-md border bg-muted/30 px-3 py-2 text-xs">
      <span className="font-medium">Last sync {formatRelativeFromNow(result.synced_at)}</span>
      <span>{summary?.added ?? 0} added</span>
      <span>{summary?.updated ?? 0} updated</span>
      <span>{summary?.reactivated ?? 0} reactivated</span>
      <span>{summary?.disabled ?? 0} disabled</span>
      <span>{summary?.unchanged ?? 0} unchanged</span>
      {(summary?.failed ?? 0) > 0 ? (
        <span className="text-destructive">{summary?.failed} failed</span>
      ) : null}
    </div>
  );
}
