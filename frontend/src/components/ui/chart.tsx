import * as React from "react";
import { ResponsiveContainer } from "recharts";

import { cn } from "@/lib/utils";

export type ChartConfig = Record<
  string,
  { label?: React.ReactNode; color?: string }
>;

const ChartContext = React.createContext<ChartConfig>({});

export function useChartConfig() {
  return React.useContext(ChartContext);
}

/**
 * Themed recharts wrapper. Series colors are exposed as `--color-<key>` CSS custom
 * properties (set inline, no dangerouslySetInnerHTML) so chart elements reference
 * `var(--color-<key>)` and inherit the design-system `--chart-*` tokens + dark mode.
 */
export function ChartContainer({
  config,
  className,
  children,
  ...props
}: React.ComponentProps<"div"> & {
  config: ChartConfig;
  children: React.ComponentProps<typeof ResponsiveContainer>["children"];
}) {
  const style = Object.fromEntries(
    Object.entries(config)
      .filter(([, item]) => item.color)
      .map(([key, item]) => [`--color-${key}`, item.color]),
  ) as React.CSSProperties;

  return (
    <ChartContext.Provider value={config}>
      <div
        data-slot="chart"
        style={style}
        className={cn(
          "h-full w-full text-xs [&_.recharts-cartesian-grid_line]:stroke-border/60",
          "[&_.recharts-cartesian-axis-tick_text]:fill-muted-foreground",
          "[&_.recharts-cartesian-axis-line]:stroke-border [&_.recharts-tooltip-cursor]:fill-muted/40",
          className,
        )}
        {...props}
      >
        <ResponsiveContainer>{children}</ResponsiveContainer>
      </div>
    </ChartContext.Provider>
  );
}

type TooltipEntry = {
  name?: string;
  dataKey?: string | number;
  value?: number | string;
  color?: string;
};

/**
 * Themed tooltip body. Pass as recharts `<Tooltip content={<ChartTooltipContent />} />`.
 */
export function ChartTooltipContent({
  active,
  payload,
  label,
  valueFormatter,
}: {
  active?: boolean;
  payload?: TooltipEntry[];
  label?: React.ReactNode;
  valueFormatter?: (value: number | string | undefined, key: string) => React.ReactNode;
}) {
  const config = useChartConfig();
  if (!active || !payload?.length) return null;
  return (
    <div className="min-w-32 rounded-lg border border-border bg-popover px-2.5 py-1.5 text-xs shadow-md">
      {label != null && <div className="mb-1 font-medium text-popover-foreground">{label}</div>}
      <div className="grid gap-1">
        {payload.map((entry, index) => {
          const key = String(entry.dataKey ?? entry.name ?? index);
          const labelText = config[key]?.label ?? entry.name ?? key;
          return (
            <div key={key} className="flex items-center justify-between gap-3">
              <span className="flex items-center gap-1.5 text-muted-foreground">
                <span
                  className="size-2 shrink-0 rounded-[2px]"
                  style={{ background: entry.color ?? `var(--color-${key})` }}
                />
                {labelText}
              </span>
              <span className="font-medium tabular-nums text-foreground">
                {valueFormatter ? valueFormatter(entry.value, key) : entry.value}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
