import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export type ModelMultiselectOption = {
  id: string;
  provider_model_name: string;
  alias?: string | null;
};

/**
 * Searchable, multi-select list of provider model offerings used by the access-policy route
 * builders (create-policy sheet and the route configuration sheet). Owns its own search
 * state and the select-all-visible / clear-visible affordance; the caller owns the selected
 * ids and supplies the model list plus loading/error state.
 */
export function ModelMultiselect({
  models,
  selected,
  onChange,
  disabled = false,
  isLoading = false,
  isError = false,
  label = "Model offerings",
  hint = "Select at least one active model this route can serve.",
  placeholderHint = "Choose a provider to load model offerings.",
  emptyHint = "No active model offerings are available for this provider.",
}: {
  models: ModelMultiselectOption[];
  selected: string[];
  onChange: (ids: string[]) => void;
  disabled?: boolean;
  isLoading?: boolean;
  isError?: boolean;
  label?: string;
  hint?: string;
  placeholderHint?: string;
  emptyHint?: string;
}) {
  const [search, setSearch] = useState("");
  const term = search.trim().toLowerCase();
  const filtered = models.filter((model) =>
    !term
      ? true
      : [model.provider_model_name, model.alias]
          .filter(Boolean)
          .some((value) => value?.toLowerCase().includes(term)),
  );
  const filteredIds = filtered.map((model) => model.id);
  const selectedVisible = selected.filter((id) => filteredIds.includes(id));
  const allVisibleSelected =
    filteredIds.length > 0 && selectedVisible.length === filteredIds.length;

  const selectVisible = () => onChange(Array.from(new Set([...selected, ...filteredIds])));
  const clearVisible = () => onChange(selected.filter((id) => !filteredIds.includes(id)));
  const toggle = (id: string, checked: boolean) =>
    onChange(checked ? Array.from(new Set([...selected, id])) : selected.filter((m) => m !== id));

  return (
    <div className="grid gap-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <Label>{label}</Label>
          <p className="text-xs text-muted-foreground">{hint}</p>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-muted-foreground">{selected.length} selected</span>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={allVisibleSelected ? clearVisible : selectVisible}
            disabled={disabled || filteredIds.length === 0 || isLoading}
          >
            {allVisibleSelected ? "Clear visible" : "Select all visible"}
          </Button>
        </div>
      </div>
      <Input
        value={search}
        onChange={(event) => setSearch(event.target.value)}
        placeholder="Search model offerings"
        disabled={disabled}
      />
      <div className="max-h-64 overflow-y-auto rounded-md border bg-background">
        {disabled ? (
          <div className="px-3 py-6 text-sm text-muted-foreground">{placeholderHint}</div>
        ) : isLoading ? (
          <div className="px-3 py-6 text-sm text-muted-foreground">Loading model offerings...</div>
        ) : isError ? (
          <div className="px-3 py-6 text-sm text-destructive">
            Model offerings could not be loaded.
          </div>
        ) : filtered.length === 0 ? (
          <div className="px-3 py-6 text-sm text-muted-foreground">
            {term ? "No model offerings match this search." : emptyHint}
          </div>
        ) : (
          filtered.map((model) => (
            <label
              key={model.id}
              className="flex cursor-pointer items-start gap-2 border-b px-3 py-2 text-sm last:border-b-0 hover:bg-muted/50"
            >
              <Checkbox
                checked={selected.includes(model.id)}
                onCheckedChange={(checked) => toggle(model.id, checked === true)}
              />
              <span className="min-w-0">
                <span className="block break-all font-mono leading-5">
                  {model.provider_model_name}
                </span>
                {model.alias ? (
                  <span className="block break-all text-xs text-muted-foreground">
                    {model.alias}
                  </span>
                ) : null}
              </span>
            </label>
          ))
        )}
      </div>
    </div>
  );
}
