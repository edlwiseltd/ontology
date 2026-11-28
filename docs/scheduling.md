# Ontology + dual-agent manufacturing scheduling

This guide implements the *Palantir Ontology + AIP manufacturing scheduling* pattern on the Autology framework, for complex multi-process structural parts. It covers an ontology layer, an **ImpactAgent** for change impact, a **ScheduleAgent** for optimisation, ontology validation of the result, and MES feedback. Everything is generic and driven by the ontology. The aerospace plant in `examples/scheduling/` is one configuration of it.

```bash
python examples/scheduling/run.py                       # ECN-7, narrated 6-step cycle
python examples/scheduling/run.py ALERT-11              # furnace breakdown: jobs on hold, planner declines
python examples/scheduling/run.py QR-1 --solver cp-sat  # rework order, exact solver (pip install ortools)
python -m autology run examples/scheduling/ontology.json replan_after_event examples/scheduling/cases.json \
    --tools examples/scheduling/tools.json --name scheduler-agent --roles scheduler \
    --approver examples/scheduling/approvals.json --out runs.jsonl
```

## 1. The seven pain points, and what addresses each

| Pain point | Mechanism |
|---|---|
| Multi-layer BOM and process coupling | `WorkOrder -hasProcess-> Process` ordered by `seq`; `WorkOrder -feeds-> WorkOrder` for sub-assemblies (`job_precedence`) |
| Frequent order changes | Every event is a governed `Replan` case: impact → schedule → validate → publish |
| Process drift and yield variability | ECN `duration_factor` / `effective_at` adjust affected operations; durations are data, not code |
| Cross-plant coordination | Resources are ontology instances; plants are modules (`imports`) sharing one core |
| Cost / delivery / utilisation trade-offs | Lexicographic objective: minimum makespan first, then minimum total lateness against due dates at that makespan. Validation reports any remaining lateness |
| Rework disruption | `QualityReturn` creates a rework order with `clone_job`, inheriting the returned order's routing and resource links from the failed step on |
| Hard-coded constraints | Resources, alternatives, availability and post-solve checks are declared in the ontology's `scheduling` section |

## 2. Ontology layer

`examples/scheduling/modules/plant.json` defines the plant:

- **Classes** (entities): `Order`, `WorkOrder`, `Part`, `Process`, `Machine`, `Mold`, `Operator`, `Material`, `ECN`, `QualityReturn` and `MachineAlert`. Statuses that MES, ERP or WMS set are declared as `external_states`.
- **Object properties** (relationships): `produces`, `fulfils`, `hasProcess`, `feeds`, `reworks`, `requiresMachine`, `requiresMold`, `operatedBy`, `consumes`, `changes`, `returnOf` and `affects`.
- **Rules:**
  - **Scheduling rules** (`scheduling`): "a process can start only if a machine, its mold and an operator are available". `requiresMachine` and `operatedBy` are *one-of* alternatives; `requiresMold` is *required*. Availability conditions are declared per resource type.
  - **Impact rules** (`impact_rules`): how events propagate (§3).
  - **Governance rules** (`modules/replanning.json`): what agents may publish (§5).

**Inference instead of a static schema.** "If this mold breaks, which work orders are affected?" is answered by following declared relationship paths over the knowledge graph. `graph_to_turtle()` exports the instance data as RDF, so the same questions can run as SPARQL in a triple store. A test checks that the SPARQL property path `:changes/^:produces` returns exactly the work orders ImpactAgent finds.

## 3. ImpactAgent: who and what is affected?

`ImpactAgent(ontology, graph).analyze(event_id)` (`autology/impact.py`):

1. **Applies the event.** A rule's `apply` sets state, e.g. an MES alert takes its machine `down` and an ECN puts its parts `under_change`.
2. **Traces impact.** It walks the rule's relationship `paths`. For example, IMP-ECN follows `changes`, then `changes.^produces` to the work orders, then `….hasProcess` to their operations, then `….requiresMachine` / `requiresMold` / `operatedBy` / `consumes` to their resources. It also follows `….feeds` (downstream assemblies) and `….fulfils` (customer orders).
3. **Explains every finding with a reasoning chain**, e.g. `ECN-7 -changes-> PT-02 <-produces- WO-02 -hasProcess-> WO-02/20 -requiresMachine-> EQ_05`.
4. **Finds unavailable resources and risks.** A *warning* means some alternatives are lost ("WO-02/30 loses OP_07; 1 alternative left"). *Critical* means none are left ("WO-04/20 cannot run: EQ_11 unavailable and no alternative").
5. **Emits adjustments** for the solver: duration factor and requalification release time.

On the example plant, ECN-7 affects 4 parts, 13 work orders, 36 operations, 10 machines, 8 operators, 2 materials and 6 customer orders, with 10 risks. These are measured on the generated data and will differ from the video's own figures.

## 4. ScheduleAgent: optimise

`build_problem()` turns the graph plus the impact report into a solver-neutral **flexible job-shop** problem:

- tasks with durations and release times;
- per-requirement alternative resources, with unavailable ones excluded;
- operation sequence within each job;
- job precedence along `feeds`.

Jobs with no feasible resource left go **on hold**, and holds cascade to the assemblies they feed. They are reported, never silently dropped.

| Solver | When | Guarantee |
|---|---|---|
| `CpSatSolver` (OR-Tools CP-SAT) | `pip install ortools`; `solver="auto"` picks it | Exact model: interval variables, one optional interval per alternative with exactly-one presence, `NoOverlap` per resource, sequence and precedence constraints. Phase 1 minimises makespan. Phase 2 fixes that makespan and minimises total lateness, warm-started from phase 1. Reports **optimal only when proven** within the time limit; otherwise feasible plus the solver's bound |
| `ListScheduler` (built in) | always available | Seeded multi-start schedule generation (most work remaining / earliest due / shortest processing time, with perturbation). Keeps the lowest makespan, then the lowest lateness. Computes a lower bound and reports optimal only if the makespan meets it |

Measured on the example plant (40 work orders, 101 operations; OR-Tools 9.15, laptop-class CPU):

| Scenario | CP-SAT | Late orders (makespan only → lexicographic) | Built-in |
|---|---|---|---|
| Baseline | **78 h, proven optimal, 0.1 s** | 4 → **0** | 78 h (bound 74, so "feasible"), 2 late, 0.8 s |
| ECN-7 | **92 h, proven optimal, 0.3 s** | 10 (134 h total) → **0** | 93 h, 3 late, 0.8 s |
| EQ_05 breakdown (one of four mills) | 78 h, proven optimal | n/a | 78 h |
| QR-1 rework order | 83 h, proven optimal | n/a | 83 h |
| EQ_11 breakdown (only furnace) | 38 h for the 26 schedulable orders; 14 on hold | n/a | 39 h |

Minimising makespan alone left 10 orders late after ECN-7. Adding the second objective cleared all of them at the same proven-optimal makespan. That is the cost-versus-delivery trade-off handled explicitly instead of by chance.

## 5. Ontology validation and MES feedback, governed

`validate_schedule()` runs two layers of checks:

- **Solver invariants** (defence in depth): no overlaps per resource, operation sequence, job precedence, availability of assigned resources, no missing tasks.
- **Semantic checks declared in the ontology**, which the solver does not model:

| Check | Detects |
|---|---|
| `CHK-MOLD-LIFE` | Mold has fewer shots left than the operation needs |
| `CHK-CALIBRATION` | Operation ends after the machine's calibration expires |
| `CHK-CERTIFICATION` | Operator's certification expires before the operation ends (critical) |
| `CHK-MATERIAL` | Not enough material lot on hand (critical) |
| `CHK-PART-CHANGE` | Part still under engineering change at an early start |
| `DUE-DATE` | Order lateness against its due date |
| `ON-HOLD` | Jobs that could not be scheduled |

The whole cycle runs as a governed `Replan` case (`modules/replanning.json`). The step order comes from the ontology, not from a script:

| Rule | Meaning |
|---|---|
| R-SCH-002 | Impact analysis must precede optimisation |
| R-SCH-001 | Validation must precede publishing, and re-optimising voids an earlier validation |
| R-SCH-003 | A production planner approves schedules that have critical warnings, jobs on hold or more than 8 h delay |
| R-SCH-004 | Never publish an infeasible schedule |
| R-SCH-008 | More than 10 critical findings blocks publishing until master data is fixed |
| R-SCH-005 / 006 / 007 | Which roles may analyse, optimise and publish |
| R-DATA-001 / 002 | Operator employee IDs and customer identities are not readable by the scheduling agent |

Publishing writes the schedule as JSON plus a self-contained HTML Gantt chart for shop-floor dashboards (`scheduling.publish`). In production, put an `http` tool for the MES API in front of it: the pilot configuration does exactly that, and falls back to the file drop when the MES API is unreachable.

## 6. Notes, limits and honest differences from the video

- **"OR-Tools guarantees global optimality."** It does when CP-SAT *proves* optimality within its time limit. On larger or harder instances it returns the best schedule found plus a bound, and this implementation reports exactly that.
- **Stability.** Each replan re-optimises the whole horizon for minimum makespan, so unaffected orders can move. The example reports `jobs_delayed` for this reason. Freezing started or near-term operations, or adding a minimal-change term, is a natural next step.
- **Objective.** Makespan, then lateness. Machine cost rates, overtime or set-up times would be further objective terms or constraints in the CP-SAT model.
- **Downtime windows and calendars.** Resources are modelled as available or not for the whole horizon. Partial windows (maintenance from 10 to 14 h) and shift calendars need fixed intervals in `NoOverlap`. That is a straightforward extension.
- **Scale and real-time use.** The built-in solver and the in-memory graph suit pilots of hundreds of operations. High event rates need incremental impact analysis and a persistent graph store, as the video notes.
- **Data quality.** Wrong MES statuses produce wrong inferences. The invariant checks catch inconsistent solver output, not wrong input data.
