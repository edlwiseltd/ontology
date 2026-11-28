# Autology — design note: several governed agents on one case

*17 November 2026. Status: **design only; nothing is implemented.** Decision asked of the owner: D32.
Trigger: the first model proposed by a language model (airport ground handling) described four agents; a stored
run has exactly one, so the demonstration used one agent holding all fourteen actions.*

## 1. What exists today

| | |
|---|---|
| Unit of execution | A **run**: one case (a root record and what its case template reaches), one goal, **one agent** |
| Authority | The run acts with the roles of the person who starts it, intersected with the agent's roles, inside the workspace (decision D4). Every action passes the engine's gate: preconditions, prohibitions, access rules, human review, decision-critical fields |
| Evidence | One signed audit chain per run; the run record is sealed and bound to the release it ran under |
| Configuration | Agents and their actions are part of the release (validated by the engine, approved by a second person). An action may be given to several agents today |

Nothing coordinates two agents. Nothing lets one agent call, instruct or wake another.

## 2. What is wanted, and what is not

Wanted: a case whose steps belong to different agents (a conflict-detection agent, a recovery-planning agent, a
dispatch agent), each acting only within what it was given, with one account of who did what.

Not wanted, and excluded by this design:

* an "orchestrator" agent that hands out work: it would be a second execution authority beside the engine;
* agents that message each other in free text: an instruction one agent writes would reach another as authority;
* an agent that starts runs, grants itself or another agent a role, or changes its own autonomy;
* unbounded chains of handoffs.

## 3. Design: the run stays the unit; each step has an owner

**The engine remains the only coordinator.** It already plans a path of actions to the goal. The change is that
the path may use the actions of several agents, and that each step is executed *as* the agent that owns its action.

| Aspect | Design |
|---|---|
| **Participants** | A run names the agents that take part (or a release names a *team*: an ordered set of agents for a case template). Bounded: at most 8 |
| **Task ownership** | In a team, **each action belongs to exactly one agent**. A configuration where two participating agents hold the same action is refused at validation (as two simulated tools with different behaviour under one capability are refused today). Ownership is therefore decided by the approved release, never at run time |
| **Shared case context** | The case's records, as today. There is no other shared memory. Each agent reads the case through *its own* roles: row and field rules apply per acting agent. A fact the owner of the next step may not read is unknown to that step, and the engine escalates rather than let another agent read it on its behalf |
| **Authority per step** | Requester ∩ **the owning agent's** roles ∩ workspace bounds ∩ policy, evaluated at each step. No agent ever acts with another's roles. Nothing is delegated between agents: all authority comes from the release |
| **Handoff** | The moment two consecutive steps have different owners. It carries no message and no instruction: only the case's records. The engine records it (`handoff`: from, to, the action that follows, why that agent owns it) |
| **Human review** | Unchanged: a review is asked by the engine for an action, decided by a person with the reviewer role. The request names the agent that would act |
| **Failure and recovery** | A step that fails, defers or ends uncertain pauses the run exactly as today; the paused step keeps its owner. On resumption the engine re-evaluates the owner's authority. If the plan can no longer continue (the owner lost a role, a prohibition now applies), the run escalates to a person: no other agent is substituted |
| **Release binding** | Unchanged: a run is bound to the release it started under. A release that changes the team does not change a run in progress |
| **Audit evidence** | One chain per run, as today. Each entry gains the acting agent. The verification, the seal and "who decided" are unchanged. A reader can list, per agent, what it did and under which rule |
| **Bounds** | Participants ≤ 8; handoffs counted against the planner's existing step budget; no nested runs; no parallel steps in a first version |

## 4. What stays impossible

An agent cannot: choose the next agent, widen a role, approve a review, start a run, change the plan's rules, or
pass an instruction. A hostile text in a record is read by an agent as data, as today, and by the next agent as
the same data: it gains nothing by crossing a handoff.

## 5. A minimal slice, if approved

1. Validation: within a team, one owner per action (engine; the release is refused otherwise).
2. A run started with a team: the planner uses the union of its actions; each step executes under its owner.
3. Audit entries carry the acting agent; a `handoff` entry between owners.
4. Studio: the runs screen offers a team; the run's steps show their owner.

Tests it would need: a step never uses another agent's role; an action two agents hold is refused; a fact hidden
from the owner is unknown to its step; a revoked role stops the run at that step; the chain verifies and names
every acting agent; a single-agent run behaves, and is recorded, exactly as today.

## 6. Why it is not in this sprint

It changes the sealed run record and the audit entry (a migration and a format version), the planner's input and
the meaning of decision D4 for a run ("the agent's permissions" becomes "the permissions of the agent that owns
the step"). Each of these is a governing change that deserves its own review, and none is needed to stabilise the
architect. A single agent holding all the actions remains a correct, if coarse, way to simulate such a case today.

## 7. Decision asked (D32)

| Question | If yes | If no |
|---|---|---|
| May a run involve several agents, with one owner per action and authority evaluated per step as described? | The minimal slice of §5 is planned as its own increment, with a migration and its tests | Runs stay single-agent; a solution with several described agents is simulated with one |
