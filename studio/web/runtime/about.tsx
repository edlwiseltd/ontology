// "About this application": what it is, what it runs on and what its user can do, as the Engine reports it.
// Every line is printed from the Engine's answer, except one, which is this screen's own clock and says so.
import { capabilities, RENDERS, short } from "./model";
import DesignStatus from "./status";
import type { Application } from "./types";

export default function About({ app, lastAnswer }: { app: Application; lastAnswer: Date | null }) {
  const { manifest, you, release } = app;
  const { can, cannot } = capabilities(you.may);
  const closed = manifest.views.filter((v) => v.available === false);
  return (
    <section aria-labelledby="rt-about-title" data-testid="rt-about">
      <h2 id="rt-about-title">About this application</h2>
      <p className="muted small">Reported by the Engine for you, {you.name}. A screen shows these facts; the Engine enforces them on every request.</p>
      <dl className="rt-fields rt-about">
        <div><dt>Application</dt><dd data-testid="rt-about-app">{manifest.title} <span className="muted">({manifest.id})</span></dd></div>
        <div><dt>Application version</dt>
          <dd data-testid="rt-about-version">Design revision {app.revision}, content {short(app.digest)}. A design draft: no release contains it.</dd></div>
        <div><dt>Bound configuration</dt>
          <dd data-testid="rt-about-bound">Model {manifest.binding.model}, configuration {short(manifest.binding.configuration)}</dd></div>
        <div><dt>Current release</dt>
          <dd data-testid="rt-about-release">{release
            ? `Release ${release.number} (${short(release.fingerprint)})${release.runs ? ": it is what runs" : ": what runs differs from it"}`
            : "None recorded: this engine is not hosted by a platform that governs releases"}</dd></div>
        <div><dt>Environment</dt>
          <dd data-testid="rt-about-stage">Stage: {app.stage ?? "none"}{app.runs_refused ? `. Runs are refused: ${app.runs_refused}` : ""}</dd></div>
        <div><dt>Renderer</dt><dd data-testid="rt-about-renderer">Draws manifest format {RENDERS.manifest_versions.join(", ")} for Engine API {RENDERS.engine_apis.join(", ")}; this design is format {manifest.manifest_version}, API {manifest.binding.engine_api}</dd></div>
        <div><dt>Mode</dt><dd data-testid="rt-about-mode">Simulation: tools are simulated. Production: unavailable.</dd></div>
        <div><dt>Last answer from the Engine</dt>
          <dd data-testid="rt-about-last">{lastAnswer
            ? `${lastAnswer.toLocaleTimeString()}, by this browser's clock. It says when this screen last heard from the Engine, not how recent any record is.`
            : "None yet on this screen."}</dd></div>
      </dl>
      <h3>Status of the design</h3>
      <DesignStatus governance={app.governance} testid="rt-about-status" />
      <h3>What you can do here</h3>
      {can.length === 0 ? <p className="muted">Nothing: you hold no permission on this use case.</p>
        : <ul className="rt-plain" data-testid="rt-about-can">{can.map((c) => <li key={c}>{c}</li>)}</ul>}
      <h3>Restricted by your permissions</h3>
      <p className="small muted">You are a {you.kind} holding: {you.permissions.join(", ") || "no permission"}.</p>
      {cannot.length === 0 ? <p className="muted">No restriction of this kind.</p>
        : <ul className="rt-plain" data-testid="rt-about-restricted">{cannot.map((c) => <li key={c.what}>{c.what} <span className="muted">— {c.why}</span></li>)}</ul>}
      {closed.length > 0 && (
        <ul className="rt-plain small" data-testid="rt-about-closed">{closed.map((v) => <li key={v.id}>{v.title} <span className="muted">— {v.unavailable_because}</span></li>)}</ul>)}
      <h3>Not available in any application yet</h3>
      <ul className="rt-plain small" data-testid="rt-about-unavailable">{manifest.unavailable.map((u) => <li key={u.feature}>{u.reason}</li>)}</ul>
    </section>
  );
}
