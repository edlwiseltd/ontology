"use client";

import { useMemo } from "react";
import { Background, Controls, MiniMap, ReactFlow, type Edge, type Node } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { ontologyToGraph, relationsOf } from "@/lib/graph";
import type { OntologySummary } from "@/lib/types";

export default function OntologyView({ ontology, selected, onSelect }: {
  ontology: OntologySummary; selected: string | null; onSelect: (name: string) => void;
}) {
  const graph = useMemo(() => ontologyToGraph(ontology), [ontology]);
  const nodes: Node[] = graph.nodes.map((n) => ({
    id: n.id, position: n.position, selected: n.id === selected,
    data: { label: `${n.data.label}${n.data.multiple ? " [*]" : ""} · ${n.data.attributes} attr.` },
    ariaLabel: `Entity ${n.data.label}`,
  }));
  const edges: Edge[] = graph.edges.map((e) => ({ ...e, labelStyle: { fontSize: 11 } }));
  const names = Object.keys(ontology.entities).sort();
  const sel = selected && ontology.entities[selected] ? selected : null;
  const rel = sel ? relationsOf(ontology, sel) : null;

  return (
    <div className="model">
      <div className="model-head">
        <h2>Ontology</h2>
        <span className="badge" title="Editing the model needs a model-edit API in the engine (planned)">
          read-only view · from the engine
        </span>
      </div>
      <div className="model-body">
        <nav className="entity-list" aria-label="Entities (list view of the same model)">
          <ul>
            {names.map((n) => (
              <li key={n}>
                <button type="button" aria-current={n === sel ? "true" : undefined} onClick={() => onSelect(n)}>{n}</button>
              </li>
            ))}
          </ul>
        </nav>
        <div className="canvas" data-testid="canvas" aria-label="Ontology graph">
          <ReactFlow nodes={nodes} edges={edges} fitView minZoom={0.2} nodesConnectable={false} edgesFocusable
                     onNodeClick={(_, node) => onSelect(node.id)} proOptions={{ hideAttribution: false }}>
            <Background />
            <MiniMap pannable zoomable />
            <Controls showInteractive={false} />
          </ReactFlow>
        </div>
        <aside className="inspector" aria-label="Inspector">
          {sel && rel ? (
            <>
              <h3>{sel}</h3>
              <p className="muted small">{ontology.entities[sel].multiple ? "Many per case" : "One per case"}
                {ontology.entities[sel].states.length ? ` · states: ${ontology.entities[sel].states.join(", ")}` : ""}</p>
              <h4>Attributes</h4>
              <table>
                <tbody>
                  {Object.entries(ontology.entities[sel].attributes).map(([a, t]) => (
                    <tr key={a}><th scope="row">{a}</th><td>{t}</td></tr>
                  ))}
                </tbody>
              </table>
              <h4>Relationships</h4>
              <ul className="small">
                {rel.outgoing.map((r) => <li key={`o${r.kind}${r.target}`}>{r.kind} → {r.target} ({r.cardinality})</li>)}
                {rel.incoming.map((r) => <li key={`i${r.kind}${r.source}`}>{r.source} → {r.kind} ({r.cardinality})</li>)}
                {!rel.outgoing.length && !rel.incoming.length && <li className="muted">none</li>}
              </ul>
            </>
          ) : <p className="muted small">Select an entity in the graph or the list.</p>}
        </aside>
      </div>
    </div>
  );
}
