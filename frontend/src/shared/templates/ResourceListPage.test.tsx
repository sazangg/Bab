import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ResourceListPage, type ResourceSegment } from "@/shared/templates/ResourceListPage";

vi.mock("@/hooks/use-mobile", () => ({
  useIsMobile: () => false,
}));

type TestItem = {
  id: string;
  name: string;
  active: boolean;
};

const items: TestItem[] = [
  { id: "active", name: "Active item", active: true },
  { id: "archived", name: "Archived item", active: false },
];

function renderList({
  search = "",
  segment = "active",
  onSearchChange = vi.fn(),
  onSegmentChange = vi.fn(),
}: {
  search?: string;
  segment?: ResourceSegment;
  onSearchChange?: (value: string) => void;
  onSegmentChange?: (segment: ResourceSegment) => void;
} = {}) {
  render(
    <ResourceListPage
      title="Resources"
      description="Resource list"
      items={items}
      isLoading={false}
      getIsActive={(item) => item.active}
      getRowKey={(item) => item.id}
      noun="resource"
      loadingLabel="Loading resources..."
      emptyTitle="No resources"
      emptyDescription="Create a resource."
      cardTitle="All resources"
      search={search}
      onSearchChange={onSearchChange}
      searchPlaceholder="Search resources..."
      matchesSearch={(item, term) => item.name.toLowerCase().includes(term)}
      segment={segment}
      onSegmentChange={onSegmentChange}
      columns={[{ key: "name", header: "Name", cell: (item) => item.name }]}
      renderCard={(item) => <div>{item.name}</div>}
      noMatchDescription="Try another search."
    />,
  );
}

describe("ResourceListPage", () => {
  it("gives search an accessible name from the placeholder copy", async () => {
    const user = userEvent.setup();
    const onSearchChange = vi.fn();

    renderList({ onSearchChange });

    await user.type(screen.getByRole("textbox", { name: "Search resources..." }), "abc");

    expect(onSearchChange).toHaveBeenCalledWith("a");
  });

  it("marks the selected segment as pressed", () => {
    renderList({ segment: "archived" });

    expect(screen.getByRole("button", { name: "Show archived resources" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByRole("button", { name: "Show active resources" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
  });
});
