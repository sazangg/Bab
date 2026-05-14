import { Layers3 } from "lucide-react";

import { EmptyState } from "@/shared/components/EmptyState";

export function ProjectAccessSection() {
  return (
    <EmptyState
      icon={Layers3}
      title="Allocations are not wired yet"
      description="Project access will be rebuilt around the allocation and pool model."
    />
  );
}
