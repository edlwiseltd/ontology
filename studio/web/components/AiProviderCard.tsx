"use client";

// The workspace's AI provider, as the platform reports it: read-only. A policy is proposed and approved through the
// platform's API by two people, and reaches a real provider only if the owner's authorisation (deployment
// configuration, decisions D7 and D10) covers it. No key is ever shown: only where it lives.

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { AiView } from "@/lib/types";

const STATE: Record<string, string> = {
  none: "No provider is configured for this workspace",
  sandbox: "Sandbox only: a test double answers; nothing leaves this platform",
  authorised: "A real provider is authorised",
  not_authorised: "A policy exists, but data transmission is not authorised",
  unavailable: "A provider is authorised but unavailable",
};

export default function AiProviderCard({ workspace }: { workspace: string }) {
  const [view, setView] = useState<AiView | null>(null);
  const [error, setError] = useState("");
  useEffect(() => { api.aiView(workspace).then(setView).catch((e) => setError((e as Error).message)); }, [workspace]);
  if (error) return null;  // not shown to people without authority: the platform refused the read
  if (!view) return null;
  const p = view.policy;
  return (
    <section className="card" aria-labelledby="ai-title" data-testid="ai-provider">
      <h3 id="ai-title">AI provider</h3>
      <p className="small"><span className={`pill ${view.state === "authorised" ? "okpill" : view.state === "not_authorised" || view.state === "unavailable" ? "warnpill" : ""}`}
        data-testid="ai-state" data-state={view.state}>{view.state.replace("_", " ")}</span>{" "}
        {STATE[view.state] ?? view.state}. {view.reason && view.state !== "authorised" && view.state !== "sandbox" ? view.reason : ""}</p>
      <p className="muted small" data-testid="ai-transmits">{view.transmits_externally
        ? "Descriptions typed in onboarding are sent to the provider, within the limits below."
        : "Nothing typed in this workspace is sent to any provider."}</p>
      {p && (
        <table className="small">
          <tbody>
            <tr><th scope="row">Provider and model</th><td>{p.provider} · {p.model}</td></tr>
            <tr><th scope="row">Data that may be sent</th><td>{p.data_classes.join(", ")}</td></tr>
            <tr><th scope="row">Budget</th><td>{p.budget.per_period} {p.budget.currency} per {p.budget.period}, {p.budget.per_request} per request
              {view.remaining_usd !== null && view.remaining_usd !== undefined ? ` · ${view.remaining_usd} left` : ""}</td></tr>
            <tr><th scope="row">Limits</th><td>{p.limits.concurrency} at a time · {p.limits.max_output_tokens} output tokens · {p.limits.timeout_seconds}s</td></tr>
            <tr><th scope="row">Key</th><td>{p.credential ? `kept at ${p.credential.ref}; never stored or shown here` : "none: the sandbox holds no key"}</td></tr>
            <tr><th scope="row">Approved by</th><td>{view.approved_by ?? "—"} (proposed by {view.proposed_by ?? "—"})</td></tr>
            <tr><th scope="row">Owner&apos;s authorisation</th><td>{view.owner_authorisation.present ? `${view.owner_authorisation.decision ?? "present"}` : "none"}</td></tr>
          </tbody>
        </table>
      )}
      {view.pending.length > 0 && <p className="warn-text small">{view.pending.length} proposed policy(ies) wait for another person&apos;s approval.</p>}
      <p className="muted small">A policy is proposed and approved by two people through the platform&apos;s API; the owner&apos;s authorisation
        is part of the deployment and cannot be set here.</p>
    </section>
  );
}
