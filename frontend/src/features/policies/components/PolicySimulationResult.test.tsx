import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PolicySimulationResult } from "./PolicySimulationResult";

describe("PolicySimulationResult", () => {
  it("renders the empty state before a simulation is available", () => {
    render(<PolicySimulationResult result={null} />);

    expect(screen.getByText("No simulation yet")).toBeInTheDocument();
  });

  it("renders the simulation decision trace sections", () => {
    render(
      <PolicySimulationResult
        result={{
          subject: {
            org_id: "org-1",
            team_id: "team-1",
            project_id: "project-1",
            virtual_key_id: "key-1",
            virtual_key_name: "Production key",
            requested_model: "gpt-public",
            gateway_endpoint: "chat_completions",
            streaming: false,
          },
          final_decision: "would_deny",
          denied_stage: "limits",
          denied_reason: "Request limit would be exceeded.",
          requested_model: "gpt-public",
          public_model_name: "gpt-public",
          routing_mode: "ordered_fallback",
          warnings: [{ code: "draft", message: "Draft policy used." }],
          route_attempts: [
            {
              candidate_index: 0,
              selected: true,
              would_attempt: true,
              provider_name: "Primary AI",
              credential_pool_name: "Main pool",
              provider_model: "primary-model",
            },
          ],
          decisions: [
            {
              decision_type: "limit",
              stage: "request",
              outcome: "would_deny",
              enforced: true,
              policy_name: "Daily requests",
              rule_name: "Default rule",
              assignment_scope_label: "Production key",
              message: "Request limit would be exceeded.",
            },
          ],
          limit_results: [
            {
              policy_name: "Daily requests",
              rule_name: "Default rule",
              limit_type: "requests",
              limit_value: 100,
              interval_unit: "day",
              interval_count: 1,
              counting_unit: "logical_request",
              current_usage: 99,
              attempted_usage: 2,
              would_deny: true,
            },
          ],
          guardrail_results: [
            {
              policy_name: "Safety",
              rule_name: "Prompt terms",
              phase: "request",
              rule_type: "contains",
              effect: "deny",
              applicability_matched: true,
              detector_evaluated: true,
              matched_values: ["blocked"],
              decision: "blocked",
            },
          ],
        }}
      />,
    );

    expect(screen.getByText("Simulation result")).toBeInTheDocument();
    expect(screen.getByText("Production key requesting gpt-public")).toBeInTheDocument();
    expect(screen.getByText("Warnings")).toBeInTheDocument();
    expect(screen.getByText("Route attempts")).toBeInTheDocument();
    expect(screen.getByText("Policy decisions")).toBeInTheDocument();
    expect(screen.getByText("Limit checks")).toBeInTheDocument();
    expect(screen.getByText("Guardrail checks")).toBeInTheDocument();
    expect(screen.getByText("Primary AI")).toBeInTheDocument();
    expect(screen.getAllByText("Default rule").length).toBeGreaterThan(0);
    expect(screen.getAllByText("blocked").length).toBeGreaterThan(0);
  });
});
