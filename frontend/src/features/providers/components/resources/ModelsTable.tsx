import { zodResolver } from "@hookform/resolvers/zod";
import { Activity, ChevronDown, Pencil, Power, RotateCcw } from "lucide-react";
import { useEffect, useState } from "react";
import { useForm, useWatch } from "react-hook-form";
import { Link } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { DataTable, type DataTableColumn } from "@/components/ui/data-table";
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Sheet,
  SheetClose,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Label } from "@/components/ui/label";
import type { ModelOfferingResponse } from "@/shared/api/generated/schemas";
import { FilterToolbar, type FilterChip } from "@/shared/components/FilterToolbar";
import { StatusBadge } from "@/shared/components/StatusBadge";

import {
  capabilityRecordToList,
  centsToDollars,
  formatModalities,
  formatPricingSource,
  formatRelativeFromNow,
  formatTokenPrice,
} from "../../lib/format";
import { formatMetadataSource } from "../../lib/resources-helpers";
import {
  modelModalities,
  modelOfferingSchema,
  type ModelOfferingFormInput,
  type ModelOfferingValues,
} from "../../lib/schemas";
import {
  CapabilityCheckboxGroup,
  ModalityCheckboxGroup,
  PricingFields,
  PricingSnapshot,
} from "./ModelFormFields";

export function ModelsTable({
  providerId,
  models,
  total,
  limit,
  offset,
  search,
  modality,
  status,
  page,
  isLoading,
  isError,
  hasActiveCredential,
  supportsModelTest,
  isTesting,
  onSearchChange,
  onModalityChange,
  onStatusChange,
  onPageChange,
  onUpdate,
  onDeactivate,
  onReactivate,
  onTest,
  canManage,
}: {
  providerId: string;
  models: ModelOfferingResponse[];
  total: number;
  limit: number;
  offset: number;
  search: string;
  modality: string;
  status: string;
  page: number;
  isLoading: boolean;
  isError: boolean;
  hasActiveCredential: boolean;
  supportsModelTest: boolean;
  isTesting: boolean;
  onSearchChange: (value: string) => void;
  onModalityChange: (value: string) => void;
  onStatusChange: (value: string) => void;
  onPageChange: (page: number) => void;
  onUpdate: (model: ModelOfferingResponse, values: ModelOfferingValues) => void;
  onDeactivate: (model: ModelOfferingResponse) => void;
  onReactivate: (model: ModelOfferingResponse) => void;
  onTest: (model: ModelOfferingResponse) => void;
  canManage: boolean;
}) {
  const [editModel, setEditModel] = useState<ModelOfferingResponse | null>(null);
  const editForm = useForm<ModelOfferingFormInput, unknown, ModelOfferingValues>({
    resolver: zodResolver(modelOfferingSchema),
    defaultValues: {
      provider_model_name: "",
      alias: "",
      version: "",
      input_modalities: ["text"],
      output_modalities: ["text"],
      context_window: undefined,
      input_price_per_million_tokens: undefined,
      output_price_per_million_tokens: undefined,
      cached_input_price_per_million_tokens: undefined,
      capabilities: [],
    },
  });
  const editInputModalities = useWatch({ control: editForm.control, name: "input_modalities" });
  const editOutputModalities = useWatch({ control: editForm.control, name: "output_modalities" });
  const editCapabilities = useWatch({ control: editForm.control, name: "capabilities" });
  const selectedModalities = modality === "all" ? [] : modality.split(",").filter(Boolean);
  const pageCount = Math.max(Math.ceil(total / limit), 1);
  const safePage = Math.min(page, pageCount);
  const hasFilters = Boolean(search.trim()) || modality !== "all" || status !== "all";

  useEffect(() => {
    if (!editModel) return;
    editForm.reset({
      provider_model_name: editModel.provider_model_name,
      alias: editModel.alias ?? "",
      version: editModel.version ?? "",
      input_modalities: editModel.input_modalities?.length
        ? editModel.input_modalities
        : editModel.modality.split("+"),
      output_modalities: editModel.output_modalities?.length ? editModel.output_modalities : ["text"],
      context_window: editModel.context_window ?? undefined,
      input_price_per_million_tokens: centsToDollars(editModel.input_price_per_million_tokens),
      output_price_per_million_tokens: centsToDollars(editModel.output_price_per_million_tokens),
      cached_input_price_per_million_tokens: centsToDollars(
        editModel.cached_input_price_per_million_tokens,
      ),
      capabilities: capabilityRecordToList(editModel.capabilities),
    });
  }, [editModel, editForm]);

  const chips: FilterChip[] = [];
  if (search.trim()) {
    chips.push({ key: "search", label: `Search: ${search.trim()}`, onRemove: () => onSearchChange("") });
  }
  selectedModalities.forEach((item) => {
    chips.push({
      key: `modality-${item}`,
      label: `Modality: ${item}`,
      onRemove: () => {
        const next = selectedModalities.filter((value) => value !== item);
        onModalityChange(next.length ? next.join(",") : "all");
      },
    });
  });
  if (status !== "all") {
    chips.push({ key: "status", label: `Status: ${status}`, onRemove: () => onStatusChange("all") });
  }
  const clearAll = () => {
    onSearchChange("");
    onModalityChange("all");
    onStatusChange("all");
  };

  const columns: DataTableColumn<ModelOfferingResponse>[] = [
    {
      key: "model",
      header: "Model",
      cell: (model) => {
        const activeCapabilities = capabilityRecordToList(model.capabilities);
        return (
          <div className="flex flex-col gap-1">
            <span className="font-mono text-sm font-medium">{model.provider_model_name}</span>
            {model.is_active ? (
              <Link
                className="w-fit text-xs text-primary hover:underline"
                to={`/playground?model=${encodeURIComponent(model.alias || model.provider_model_name)}`}
              >
                Test in playground
              </Link>
            ) : null}
            <div className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
              {model.alias ? <span>alias: {model.alias}</span> : null}
              {model.version ? <span>v{model.version}</span> : null}
              {activeCapabilities.length > 0 ? (
                <div className="flex flex-wrap gap-1">
                  {activeCapabilities.map((capability) => (
                    <span
                      key={capability}
                      className="rounded border bg-muted/40 px-1.5 py-0.5 text-[10px]"
                    >
                      {capability}
                    </span>
                  ))}
                </div>
              ) : null}
            </div>
          </div>
        );
      },
    },
    {
      key: "modalities",
      header: "Modalities",
      className: "text-xs",
      cell: (model) => (
        <div className="flex items-center gap-1.5 text-muted-foreground">
          <span>{formatModalities(model.input_modalities)}</span>
          <span aria-hidden>→</span>
          <span>{formatModalities(model.output_modalities)}</span>
        </div>
      ),
    },
    {
      key: "context",
      header: "Context",
      align: "right",
      className: "font-mono text-xs",
      cell: (model) => (model.context_window ? model.context_window.toLocaleString() : "—"),
    },
    {
      key: "price",
      header: "Price (in/out)",
      align: "right",
      className: "font-mono text-xs",
      cell: (model) => (
        <div className="flex flex-col">
          <span>
            {formatTokenPrice(model.effective_input_price_per_million_tokens)} /{" "}
            {formatTokenPrice(model.effective_output_price_per_million_tokens)}
          </span>
          <span className="font-sans text-[11px] text-muted-foreground">
            {formatPricingSource(model.pricing_source)}
          </span>
        </div>
      ),
    },
    {
      key: "source",
      header: "Source",
      className: "text-xs text-muted-foreground",
      cell: (model) => (
        <div className="flex flex-col">
          <span>
            {model.metadata_source}
            {model.pricing_catalog_version ? ` · pricing ${model.pricing_catalog_version}` : ""}
          </span>
          {model.metadata_last_synced_at ? (
            <span className="text-[11px]">{formatRelativeFromNow(model.metadata_last_synced_at)}</span>
          ) : null}
          {model.pricing_last_refreshed_at ? (
            <span className="text-[11px]">
              price {formatRelativeFromNow(model.pricing_last_refreshed_at)}
            </span>
          ) : null}
        </div>
      ),
    },
    {
      key: "status",
      header: "Status",
      cell: (model) => (
        <StatusBadge variant={model.is_active ? "active" : "inactive"}>
          {model.is_active ? "Active" : "Disabled"}
        </StatusBadge>
      ),
    },
    ...(canManage
      ? [
          {
            key: "actions",
            header: <span className="sr-only">Actions</span>,
            headClassName: "w-[1%]",
            className: "flex justify-end gap-1",
            cell: (model: ModelOfferingResponse) => (
              <>
                <Button
                  size="icon-sm"
                  variant="ghost"
                  disabled={
                    !providerId ||
                    !model.is_active ||
                    !hasActiveCredential ||
                    !supportsModelTest ||
                    isTesting
                  }
                  onClick={() => onTest(model)}
                  title={
                    !hasActiveCredential
                      ? "Add an active credential before testing models."
                      : !supportsModelTest
                        ? "Model testing is unavailable for this provider integration."
                        : "Test model"
                  }
                  aria-label="Test model"
                >
                  <Activity />
                </Button>
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button
                      size="icon-sm"
                      variant="ghost"
                      aria-label={`${model.provider_model_name} actions`}
                    >
                      <ChevronDown />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end">
                    <DropdownMenuItem onSelect={() => setEditModel(model)}>
                      <Pencil />
                      Edit metadata
                    </DropdownMenuItem>
                    <DropdownMenuItem asChild>
                      <Link
                        to={`/playground?model=${encodeURIComponent(model.alias || model.provider_model_name)}`}
                      >
                        Test in playground
                      </Link>
                    </DropdownMenuItem>
                    <DropdownMenuSeparator />
                    {model.is_active ? (
                      <DropdownMenuItem variant="destructive" onSelect={() => onDeactivate(model)}>
                        <Power />
                        Disable
                      </DropdownMenuItem>
                    ) : (
                      <DropdownMenuItem onSelect={() => onReactivate(model)}>
                        <RotateCcw />
                        Reactivate
                      </DropdownMenuItem>
                    )}
                  </DropdownMenuContent>
                </DropdownMenu>
              </>
            ),
          },
        ]
      : []),
  ];

  const pagination =
    total > limit ? (
      <>
        <p>
          Page {safePage} of {pageCount} · showing {offset + 1}-
          {Math.min(offset + models.length, total)} of {total}
        </p>
        <div className="flex gap-2">
          <Button
            size="sm"
            variant="outline"
            disabled={safePage <= 1}
            onClick={() => onPageChange(safePage - 1)}
          >
            Previous
          </Button>
          <Button
            size="sm"
            variant="outline"
            disabled={safePage >= pageCount}
            onClick={() => onPageChange(safePage + 1)}
          >
            Next
          </Button>
        </div>
      </>
    ) : undefined;

  return (
    <div className="flex flex-col gap-4">
      <FilterToolbar chips={chips} onClearAll={chips.length > 0 ? clearAll : undefined}>
        <Input
          value={search}
          onChange={(event) => onSearchChange(event.target.value)}
          placeholder="Search models or aliases..."
          className="w-full sm:w-72"
        />
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="outline">
              {selectedModalities.length
                ? `Modalities: ${selectedModalities.join(", ")}`
                : "All modalities"}
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-56">
            <DropdownMenuLabel>Required modalities</DropdownMenuLabel>
            <DropdownMenuSeparator />
            <DropdownMenuCheckboxItem
              checked={selectedModalities.length === 0}
              onCheckedChange={() => onModalityChange("all")}
            >
              All modalities
            </DropdownMenuCheckboxItem>
            {modelModalities.map((item) => {
              const next = selectedModalities.includes(item)
                ? selectedModalities.filter((value) => value !== item)
                : [...selectedModalities, item];
              return (
                <DropdownMenuCheckboxItem
                  key={item}
                  checked={selectedModalities.includes(item)}
                  onCheckedChange={() => onModalityChange(next.length ? next.join(",") : "all")}
                >
                  {item}
                </DropdownMenuCheckboxItem>
              );
            })}
          </DropdownMenuContent>
        </DropdownMenu>
        <Select value={status} onValueChange={onStatusChange}>
          <SelectTrigger className="w-40">
            <SelectValue placeholder="Filter by status" />
          </SelectTrigger>
          <SelectContent>
            <SelectGroup>
              <SelectItem value="all">All statuses</SelectItem>
              <SelectItem value="active">Active</SelectItem>
              <SelectItem value="disabled">Disabled</SelectItem>
            </SelectGroup>
          </SelectContent>
        </Select>
      </FilterToolbar>

      <DataTable
        columns={columns}
        data={models}
        loading={isLoading}
        error={isError ? "Models could not be loaded." : undefined}
        getRowKey={(model) => model.id}
        rowClassName={(model) => (!model.is_active ? "opacity-60" : undefined)}
        empty={{
          title: hasFilters ? "No models match these filters." : "No models added yet.",
        }}
        footer={pagination}
      />

      <Sheet open={Boolean(editModel)} onOpenChange={(open) => !open && setEditModel(null)}>
        <SheetContent>
          <SheetHeader>
            <SheetTitle>Edit model</SheetTitle>
            <SheetDescription>
              Update the model metadata Bab uses for display, filtering, routing, and spend
              estimates.
            </SheetDescription>
          </SheetHeader>
          <form
            className="grid gap-4 overflow-y-auto px-6 py-5"
            onSubmit={editForm.handleSubmit((values) => {
              if (editModel) onUpdate(editModel, values);
              setEditModel(null);
            })}
          >
            {editModel ? (
              <div className="rounded-md border bg-muted/20 p-3 text-sm">
                <div className="font-medium">Metadata source</div>
                <div className="mt-1 text-muted-foreground">
                  {formatMetadataSource(editModel.metadata_source)}
                  {editModel.metadata_last_synced_at
                    ? ` · synced ${formatRelativeFromNow(editModel.metadata_last_synced_at)}`
                    : ""}
                </div>
                <p className="mt-2 text-xs text-muted-foreground">
                  Saving here marks this model as manually managed. Catalog sync will preserve these
                  values unless overwrite mode is selected.
                </p>
              </div>
            ) : null}
            {editModel ? <PricingSnapshot model={editModel} /> : null}
            <div className="space-y-1.5">
              <Label htmlFor="edit-provider-model-name">Provider model name</Label>
              <Input id="edit-provider-model-name" {...editForm.register("provider_model_name")} />
              {editForm.formState.errors.provider_model_name ? (
                <p className="text-xs text-destructive">
                  {editForm.formState.errors.provider_model_name.message}
                </p>
              ) : null}
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="edit-provider-model-alias">Alias</Label>
              <Input id="edit-provider-model-alias" {...editForm.register("alias")} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="edit-provider-model-version">Version</Label>
              <Input id="edit-provider-model-version" {...editForm.register("version")} />
            </div>
            <ModalityCheckboxGroup
              label="Input modalities"
              values={editInputModalities ?? []}
              onChange={(values) => editForm.setValue("input_modalities", values)}
            />
            <ModalityCheckboxGroup
              label="Output modalities"
              values={editOutputModalities ?? []}
              onChange={(values) => editForm.setValue("output_modalities", values)}
            />
            <div className="space-y-1.5">
              <Label htmlFor="edit-provider-model-context">Context window</Label>
              <Input
                id="edit-provider-model-context"
                type="number"
                min={1}
                {...editForm.register("context_window")}
              />
              {editForm.formState.errors.context_window ? (
                <p className="text-xs text-destructive">
                  {editForm.formState.errors.context_window.message}
                </p>
              ) : null}
            </div>
            <PricingFields register={editForm.register} prefix="edit" />
            <CapabilityCheckboxGroup
              values={editCapabilities ?? []}
              onChange={(values) => editForm.setValue("capabilities", values)}
            />
          </form>
          <SheetFooter>
            <Button
              disabled={!editModel}
              onClick={editForm.handleSubmit((values) => {
                if (editModel) onUpdate(editModel, values);
                setEditModel(null);
              })}
            >
              Save
            </Button>
            <SheetClose asChild>
              <Button variant="outline">Cancel</Button>
            </SheetClose>
          </SheetFooter>
        </SheetContent>
      </Sheet>
    </div>
  );
}
