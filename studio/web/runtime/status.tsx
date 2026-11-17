// What an application design is, in the six states the Engine computes (autology/applications.py, "governance").
// This file draws them. It decides none of them, and it never calls a design a release.
import type { Governance, GovernanceState } from "./types";

export const DESIGN_STATES: [GovernanceState, string][] = [
  ["design_draft", "Design draft"], ["validated_design", "Validated design"], ["configuration_bound", "Configuration-bound design"],
  ["approved_release_artifact", "Approved release artifact"], ["simulation_ready", "Simulation-ready"],
  ["production_authorized", "Production authorized"]];

/** One word per state: "yes", "no", or "not supported" when the Engine has no such state at all. */
export function stateWord(state: { supported: boolean; value: boolean }): "yes" | "no" | "not supported" {
  return !state.supported ? "not supported" : state.value ? "yes" : "no";
}

export default function DesignStatus({ governance, testid }: { governance: Governance; testid: string }) {
  return (
    <div className="rt-status" data-testid={testid}>
      <ul aria-label="Status of this application design, as the Engine reports it">
        {DESIGN_STATES.map(([key, label]) => {
          const word = stateWord(governance[key]);
          return (
            <li key={key} data-state={key} data-value={word} className={word === "yes" ? "rt-ok" : word === "no" ? "rt-bad" : "rt-none"}>
              <span>{label}:</span> <strong>{word}</strong>
              <span className="rt-status-detail"> ({governance[key].detail})</span>
            </li>);
        })}
      </ul>
    </div>
  );
}
