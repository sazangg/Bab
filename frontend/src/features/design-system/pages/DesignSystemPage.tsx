import { useEffect, useState } from "react";

import { PageHeader } from "@/shared/components/PageHeader";
import { cn } from "@/lib/utils";

import { FoundationsSection } from "../sections/FoundationsSection";
import { FoundationV2Section } from "../sections/FoundationV2Section";
import { PrimitivesSection } from "../sections/PrimitivesSection";
import { OverlaysFeedbackSection } from "../sections/OverlaysFeedbackSection";
import { DataDisplaySection } from "../sections/DataDisplaySection";
import { PatternsSection } from "../sections/PatternsSection";

const sections = [
  { id: "foundations", label: "Foundations" },
  { id: "foundation-v2", label: "Foundation v2 (new)" },
  { id: "primitives", label: "Primitives" },
  { id: "overlays-feedback", label: "Overlays & feedback" },
  { id: "data-display", label: "Data display & navigation" },
  { id: "patterns", label: "Patterns" },
] as const;

export function DesignSystemPage() {
  const [activeId, setActiveId] = useState<string>(sections[0].id);

  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((entry) => entry.isIntersecting)
          .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)[0];
        if (visible) setActiveId(visible.target.id);
      },
      { rootMargin: "-20% 0px -60% 0px", threshold: 0 },
    );
    for (const section of sections) {
      const node = document.getElementById(section.id);
      if (node) observer.observe(node);
    }
    return () => observer.disconnect();
  }, []);

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Design system"
        description="A live catalog of the primitives, patterns, and tokens this app is built on. Use it as the source of truth when shipping new surfaces."
      />

      <div className="grid grid-cols-[180px_minmax(0,1fr)] gap-8">
        <aside className="sticky top-4 self-start">
          <nav className="space-y-1" aria-label="Design system sections">
            {sections.map((section) => (
              <a
                key={section.id}
                href={`#${section.id}`}
                className={cn(
                  "block rounded-md px-2.5 py-1.5 text-sm transition-colors",
                  activeId === section.id
                    ? "bg-muted text-foreground"
                    : "text-muted-foreground hover:bg-muted/50 hover:text-foreground",
                )}
              >
                {section.label}
              </a>
            ))}
          </nav>
        </aside>
        <div className="space-y-12">
          <FoundationsSection />
          <FoundationV2Section />
          <PrimitivesSection />
          <OverlaysFeedbackSection />
          <DataDisplaySection />
          <PatternsSection />
        </div>
      </div>
    </div>
  );
}
