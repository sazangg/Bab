import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PolicySimulationPanel } from "./PolicySimulationPanel";

const simulateHook = vi.hoisted(() => vi.fn());

vi.mock("@/shared/api/generated/policies/policies", () => ({
  useSimulatePoliciesApiV1PoliciesSimulationsPost: simulateHook,
}));

describe("PolicySimulationPanel", () => {
  const mutate = vi.fn();

  beforeEach(() => {
    mutate.mockReset();
    simulateHook.mockImplementation((options) => ({
      isPending: false,
      mutate: (payload: unknown) => {
        mutate(payload);
        options.mutation.onSuccess({
          status: 200,
          data: {
            subject: {
              org_id: "org-1",
              team_id: "team-1",
              project_id: "project-1",
              virtual_key_id: "key-1",
              requested_model: "gpt-public",
              gateway_endpoint: "chat_completions",
              streaming: false,
            },
            final_decision: "allow",
            requested_model: "gpt-public",
          },
        });
      },
    }));
  });

  it("submits a simulation request with optional guardrail text and drafts", async () => {
    const user = userEvent.setup();
    const onResult = vi.fn();
    const drafts = [
      {
        kind: "limit" as const,
        operation: "add_policy" as const,
        limit_policy: {
          name: "Draft limit",
          rules: [],
        },
      },
    ];

    render(<PolicySimulationPanel drafts={drafts} onResult={onResult} />);

    await user.type(screen.getByLabelText("Virtual key ID"), "key-1");
    await user.type(screen.getByLabelText("Requested model"), "gpt-public");
    await user.type(screen.getByLabelText("Estimated input tokens"), "42");
    await user.type(screen.getByLabelText("Requested output tokens"), "128");
    await user.type(screen.getByLabelText("Prompt text"), "hello");
    await user.click(screen.getByRole("button", { name: "Run simulation" }));

    expect(mutate).toHaveBeenCalledWith({
      data: expect.objectContaining({
        target: { virtual_key_id: "key-1" },
        requested_model: "gpt-public",
        gateway_endpoint: "chat_completions",
        estimated_input_tokens: 42,
        requested_output_tokens: 128,
        guardrail_input: {
          prompt_text: "hello",
          response_text: null,
        },
        drafts,
      }),
    });
    expect(onResult).toHaveBeenCalledWith(expect.objectContaining({ final_decision: "allow" }));
    expect(screen.getByText("1 draft change(s)")).toBeInTheDocument();
    expect(screen.getByText("allow")).toBeInTheDocument();
  });
});
