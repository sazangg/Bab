import {
  siDeepseek,
  siGoogle,
  siHuggingface,
  siMistralai,
  siOllama,
  siOpenrouter,
  siPerplexity,
  type SimpleIcon,
} from "simple-icons";

import { cn } from "@/lib/utils";

const iconBySlug: Record<string, SimpleIcon> = {
  deepseek: siDeepseek,
  google: siGoogle,
  huggingface: siHuggingface,
  mistralai: siMistralai,
  ollama: siOllama,
  openrouter: siOpenrouter,
  perplexity: siPerplexity,
};

export function ProviderLogo({
  iconSlug,
  name,
  className,
}: {
  iconSlug?: string;
  name: string;
  className?: string;
}) {
  const icon = iconSlug ? iconBySlug[iconSlug] : undefined;

  if (icon) {
    return (
      <div
        className={cn(
          "flex size-10 shrink-0 items-center justify-center rounded-md border bg-background",
          className,
        )}
      >
        <svg
          role="img"
          viewBox="0 0 24 24"
          aria-hidden="true"
          className="size-5"
          style={{ color: `#${icon.hex}` }}
          fill="currentColor"
        >
          <path d={icon.path} />
        </svg>
      </div>
    );
  }

  return (
    <div
      className={cn(
        "flex size-10 shrink-0 items-center justify-center rounded-md border bg-background text-sm font-semibold",
        className,
      )}
      aria-hidden="true"
    >
      {name.slice(0, 2).toUpperCase()}
    </div>
  );
}
