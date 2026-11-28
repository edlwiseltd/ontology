"use client";

// Synthetic sample records of the active release. A release never loads data by itself: a workspace administrator
// asks, with a reason, and the platform decides (an approved release must be active and be what runs; never in
// Pilot) and records it. Existing records are never overwritten.

import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import type { SampleData } from "@/lib/types";

export default function SampleRecords({ workspace, useCaseId, onLoaded }: { workspace: string; useCaseId: string; onLoaded?: () => void }) {
  const [state, setState] = useState<SampleData | null>(null);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  const load = useCallback(async () => {
    try { setState(await api.sampleData(workspace, useCaseId)); } catch (e) { setError((e as Error).message); }
  }, [workspace, useCaseId]);
  useEffect(() => { void load(); }, [load]);

  async function provision() {
    setBusy(true); setError(""); setMessage("");
    try {
      const out = await api.loadSampleData(workspace, useCaseId, reason);
      setState(out); setReason("");
      setMessage(`${out.just_loaded?.length ?? 0} sample record(s) loaded and marked as samples; ${out.skipped?.length ?? 0} already there were left as they are.`);
      onLoaded?.();
    } catch (e) { setError(e instanceof ApiError ? e.message : (e as Error).message); }
    finally { setBusy(false); }
  }

  if (!state || state.available === 0) return null;
  const done = state.loaded.length + state.already_present.length;
  return (
    <div className="card" data-testid="sample-records">
      <div className="row spread">
        <h3>Sample records</h3>
        <button type="button" className="small" onClick={() => void load()}>Refresh</button>
      </div>
      <p className="small" data-testid="sample-status">
        The active release names {state.available} synthetic sample record(s); {done} are in the use case
        {state.loaded.length ? ` (${state.loaded.length} loaded as samples)` : ""}. A release never loads data by itself.</p>
      {state.refusal && done < state.available && <p className="warn-text small" role="status" data-testid="sample-refusal">{state.refusal}.</p>}
      {state.may_load && state.loadable && (
        <div className="row">
          <label className="sr-only" htmlFor={`sample-reason-${useCaseId}`}>Reason for loading the sample records</label>
          <input id={`sample-reason-${useCaseId}`} value={reason} onChange={(e) => setReason(e.target.value)} maxLength={500}
                 placeholder="reason (recorded with your name)" />
          <button type="button" className="primary" disabled={busy || !reason.trim()} onClick={provision} data-testid="load-samples">
            Load the sample records</button>
        </div>
      )}
      {!state.may_load && state.loadable && <p className="muted small">A workspace administrator loads them, with a reason.</p>}
      {message && <p className="ok small" role="status" data-testid="sample-message">{message}</p>}
      {error && <p className="error" role="alert">{error}</p>}
    </div>
  );
}
