import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiDocsPage } from "./ApiDocsPage";

const useGatewayMetadataMock = vi.hoisted(() => vi.fn());

vi.mock("@/shared/api/gateway-metadata", () => ({
  useGatewayMetadata: useGatewayMetadataMock,
  resolveGatewayBaseUrl: (value?: string | null) => value?.replace(/\/+$/, "") ?? null,
}));

describe("ApiDocsPage", () => {
  beforeEach(() => {
    useGatewayMetadataMock.mockReset();
  });

  it("shows configuration guidance without rendering invalid examples", () => {
    useGatewayMetadataMock.mockReturnValue({
      data: { status: 200, data: { public_base_url: null } },
    });

    render(<ApiDocsPage />);

    expect(screen.getByText(/Public gateway URL is not configured/)).toBeInTheDocument();
    expect(screen.queryByText("Postman setup")).not.toBeInTheDocument();
    expect(screen.queryByText(/null\/v1\/chat\/completions/)).not.toBeInTheDocument();
  });

  it("documents native Anthropic Messages integrations", () => {
    useGatewayMetadataMock.mockReturnValue({
      data: { status: 200, data: { public_base_url: "https://gateway.example.com/" } },
    });

    render(<ApiDocsPage />);

    expect(screen.getByText("Anthropic Messages cURL")).toBeInTheDocument();
    expect(screen.getByText("Anthropic SDK JS/TS")).toBeInTheDocument();
    expect(screen.getByText("Anthropic SDK Python")).toBeInTheDocument();
    expect(screen.getByText(/native Anthropic Messages passthrough/)).toBeInTheDocument();
  });
});
