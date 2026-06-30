import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { ModelsTable } from "./ModelsTable";

function renderModelsTable() {
  render(
    <MemoryRouter>
      <ModelsTable
        providerId="provider-1"
        models={[]}
        total={0}
        limit={25}
        offset={0}
        search=""
        modality="all"
        status="all"
        page={1}
        isLoading={false}
        isError={false}
        hasActiveCredential
        supportsModelTest
        isTesting={false}
        onSearchChange={vi.fn()}
        onModalityChange={vi.fn()}
        onStatusChange={vi.fn()}
        onPageChange={vi.fn()}
        onUpdate={vi.fn()}
        onDeactivate={vi.fn()}
        onReactivate={vi.fn()}
        onTest={vi.fn()}
        canManage
      />
    </MemoryRouter>,
  );
}

describe("ModelsTable", () => {
  it("gives model filters accessible names", () => {
    renderModelsTable();

    expect(screen.getByRole("textbox", { name: "Search provider models" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Filter models by modality" })).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Filter models by status" })).toBeInTheDocument();
  });

  it("explains the empty model state", () => {
    renderModelsTable();

    expect(screen.getByText("No models added yet.")).toBeInTheDocument();
    expect(
      screen.getByText("Add a model manually or sync models from the provider catalog when supported."),
    ).toBeInTheDocument();
  });
});
