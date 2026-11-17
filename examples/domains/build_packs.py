"""Writes the two synthetic domain packs of the cross-domain validation (examples/domains/*).

A domain pack is **configuration**: a blank model, the sandbox architect, and a folder of blueprints (a template with
its questions, its simulated tools and invented records). Nothing here is part of the engine, and the engine holds
no code for either domain. Everything is fictional: places, organisations, people, accounts, amounts.

A blueprint is written by an engineer. A proposal made from it is "an approved template adjusted by your answers",
never a reading of the brief and never a language model's output: the sandbox architect says so on every proposal.

    python examples/domains/build_packs.py     # rewrites the JSON files beside this script
"""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def ent(name, why, description, states, attributes):
    return {"kind": "entity", "name": name, "rationale": why,
            "value": {"description": description, "states": states, "attributes": attributes}}


def rel(a, kind, b, why):
    return {"kind": "relationship", "rationale": why, "value": {"from": a, "to": b, "type": kind, "cardinality": "1..*"}}


def act(name, description, capability, requires, effects, side="none"):
    return {"kind": "action", "name": name, "rationale": description,
            "value": {"description": description, "capability": capability, "requires": requires, "effects": effects,
                      "side_effect": side}}


def rule(rid, kind, description, uses=(), **params):
    return {"kind": "rule", "rationale": description, "uses": list(uses),
            "value": {"id": rid, "type": kind, **params, "description": description}}


def param(pid, kind, default, question, why):
    return {"id": pid, "type": kind, "default": default, "question": question, "why": why}


def tool(action, message, **extra):
    return {"action": action, "tool": "simulated.succeed", "message": message + " (simulated: nothing left Autology)", **extra}


def pack(folder, model_name, blueprint):
    home = HERE / folder
    (home / "blueprints").mkdir(parents=True, exist_ok=True)
    (home / "ontology.json").write_text(json.dumps({"name": model_name, "version": "0.1.0"}, indent=1) + "\n")
    (home / "server.json").write_text(json.dumps({
        "ontology": "ontology.json", "store": "autology.db", "users": [], "ai": {"provider": "sandbox"},
        "blueprints": "blueprints"}, indent=1) + "\n")
    (home / "blueprints" / f"{blueprint['id']}.json").write_text(json.dumps(blueprint, indent=1) + "\n")


# ---------------------------------------------------------------------------------------------------------------
# A. Crisis management: a regional coordination centre and a fictional flood
# ---------------------------------------------------------------------------------------------------------------
def incident(n, area, **facts):
    base = {"type": "IncidentReport", "id": f"INC-{n}", "status": "received", "reference": f"INC-{n}",
            "reported_by": "municipal duty officer (fictional)", "source_verified": True,
            "information_basis": "observed", "people_at_risk": 10, "update_note": "", "simulate_outage": False}
    rows = [{**base, **facts},
            {"type": "Assignment", "id": f"ASG-{n}", "status": "proposed", "task": "pumping and sandbagging",
             "basis": "recommendation"},
            {"type": "ResponseTeam", "id": f"TEAM-{n}", "status": "available", "name": f"Response team {n} (fictional)",
             "speciality": "flood response"},
            {"type": "Resource", "id": f"RES-{n}", "status": "available", "name": f"Mobile pump set {n} (fictional)",
             "kind": "equipment", "quantity": 2}]
    links = [[area, "incidents", f"INC-{n}"], [f"INC-{n}", "assignments", f"ASG-{n}"], [f"ASG-{n}", "team", f"TEAM-{n}"],
             [f"ASG-{n}", "equipment", f"RES-{n}"], ["ORG-1", "teams", f"TEAM-{n}"], ["ORG-1", "resources", f"RES-{n}"]]
    return rows, links


crisis_rows = [
    {"type": "Organization", "id": "ORG-1", "status": "active", "name": "Riverbend Civil Protection (fictional)",
     "kind": "regional coordination centre"},
    {"type": "HazardEvent", "id": "HZ-1", "status": "active", "name": "Alder River flood (fictional exercise)",
     "hazard_type": "river flood", "severity": 3},
    {"type": "AffectedArea", "id": "AREA-NORTHMERE", "status": "affected", "name": "Northmere (fictional municipality)",
     "municipality": "Northmere", "population": 8400},
    {"type": "AffectedArea", "id": "AREA-EASTWICK", "status": "affected", "name": "Eastwick (fictional municipality)",
     "municipality": "Eastwick", "population": 3100},
    {"type": "AffectedArea", "id": "AREA-SOUTHHOLM", "status": "monitored", "name": "Southholm (fictional municipality)",
     "municipality": "Southholm", "population": 5200},
    {"type": "Infrastructure", "id": "INF-PUMP-1", "status": "impaired", "name": "Northmere pumping station (fictional)",
     "kind": "water"},
    {"type": "Infrastructure", "id": "INF-BRIDGE-1", "status": "operational", "name": "Eastwick road bridge (fictional)",
     "kind": "road"},
    {"type": "Shelter", "id": "SH-1", "status": "open", "name": "Northmere sports hall (fictional)", "capacity": 300,
     "occupancy": 40},
    {"type": "SupplyRequirement", "id": "SUP-1", "status": "open", "item": "sandbags", "quantity": 2000}]
crisis_links = [["HZ-1", "affects", "AREA-NORTHMERE"], ["HZ-1", "affects", "AREA-EASTWICK"], ["HZ-1", "affects", "AREA-SOUTHHOLM"],
                ["AREA-NORTHMERE", "infrastructure", "INF-PUMP-1"], ["AREA-EASTWICK", "infrastructure", "INF-BRIDGE-1"],
                ["AREA-NORTHMERE", "shelters", "SH-1"], ["INC-2001", "requirements", "SUP-1"]]
for number, area, facts in (
        (2001, "AREA-NORTHMERE", {"description": "Water entering the basement of a care home; 12 residents", "people_at_risk": 12}),
        (2002, "AREA-NORTHMERE", {"description": "Embankment overtopping near a housing estate", "people_at_risk": 180}),
        (2003, "AREA-SOUTHHOLM", {"description": "A model run suggests the lower quarter may flood tomorrow",
                                  "information_basis": "predicted", "people_at_risk": 60}),
        (2004, "AREA-EASTWICK", {"description": "Anonymous message: bridge reported damaged", "source_verified": False,
                                 "reported_by": "anonymous message (unverified)", "people_at_risk": 5})):
    rows, links = incident(number, area, **facts)
    crisis_rows += rows
    crisis_links += links

pack("crisis_management", "crisis-management", {
    "id": "flood_response", "name": "Regional flood response coordination (synthetic template)",
    "description": "Take a reported incident through validation, a proposed allocation of equipment and the "
                   "assignment of a response team, with a person deciding above a limit, and publish an update. "
                   "A training template on invented data: it dispatches nobody and warns nobody.",
    "keywords": ["flood", "incident", "emergency", "shelter", "municipalit", "hazard", "response team", "evacuat", "crisis"],
    "parameters": [
        param("approval_people_threshold", "number", 50,
              "From how many people at risk must a person approve the assignment of a response team?",
              "Below it the assignment may be made within the policy; from it on, a named person decides"),
        param("coordinator_role", "name", "duty_coordinator", "Which role approves assignments above that limit?",
              "The review is addressed to a role that a named member must hold"),
        param("operations_role", "name", "operations_officer", "Which role handles incidents day to day?",
              "Only this role may assign a team or publish an update; the agent acts with it"),
        param("dispatch_system", "text", "", "Which system records assignments (for example a dispatch system)?",
              "Assigning a team acts outside Autology: it needs a tool, first simulated, then a sandbox of that system")],
    "items": [
        ent("HazardEvent", "The brief speaks of a hazard affecting several municipalities", "A hazard event",
            ["active", "closed"], {"name": "string", "hazard_type": "string", "severity": "number"}),
        ent("AffectedArea", "Incidents happen in areas the hazard affects", "A geographic area under the hazard",
            ["monitored", "affected", "access_restricted"], {"name": "string", "municipality": "string", "population": "number"}),
        ent("Infrastructure", "The brief asks which infrastructure is impaired", "An item of infrastructure in an area",
            ["operational", "impaired", "out_of_service"], {"name": "string", "kind": "string"}),
        ent("IncidentReport", "The work starts from an incident report", "A report of an incident, with what is known and how",
            ["received", "validated", "resources_identified", "allocation_proposed", "response_assigned", "updated"],
            {"reference": "string", "description": "string", "reported_by": "string", "source_verified": "boolean",
             "information_basis": "string", "people_at_risk": "number", "update_note": "string", "simulate_outage": "boolean"}),
        ent("Resource", "Equipment and vehicles are allocated to incidents", "A vehicle or an item of equipment",
            ["available", "reserved", "deployed"], {"name": "string", "kind": "string", "quantity": "number"}),
        ent("ResponseTeam", "Teams are assigned to incidents", "An emergency response team",
            ["available", "assigned", "resting"], {"name": "string", "speciality": "string"}),
        ent("Shelter", "People may need shelter", "A shelter and its capacity", ["open", "full", "closed"],
            {"name": "string", "capacity": "number", "occupancy": "number"}),
        ent("SupplyRequirement", "Incidents create supply needs", "Something an incident needs", ["open", "met"],
            {"item": "string", "quantity": "number"}),
        ent("Assignment", "An allocation is first proposed, then decided", "A proposed or decided operational assignment",
            ["proposed", "approved", "active", "completed"], {"task": "string", "basis": "string"}),
        ent("Organization", "Teams and equipment belong to responding organisations", "A responding organisation",
            ["active"], {"name": "string", "kind": "string"}),
        rel("HazardEvent", "affects", "AffectedArea", "A hazard affects areas"),
        rel("AffectedArea", "incidents", "IncidentReport", "An incident is located in an area"),
        rel("AffectedArea", "infrastructure", "Infrastructure", "Infrastructure lies in an area"),
        rel("AffectedArea", "shelters", "Shelter", "Shelters serve an area"),
        rel("IncidentReport", "requirements", "SupplyRequirement", "An incident has supply needs"),
        rel("IncidentReport", "assignments", "Assignment", "An incident receives assignments"),
        rel("Assignment", "team", "ResponseTeam", "An assignment names a team"),
        rel("Assignment", "equipment", "Resource", "An assignment names equipment"),
        rel("Organization", "teams", "ResponseTeam", "Teams belong to an organisation"),
        rel("Organization", "resources", "Resource", "Equipment belongs to an organisation"),
        act("validate_report", "Check that the report comes from a verified source", "intelligence.validate",
            ["IncidentReport.status == 'received'", "IncidentReport.source_verified == True"],
            {"IncidentReport": {"status": "validated"}}),
        act("identify_resources", "List the teams and equipment that could serve the incident", "resources.identify",
            ["IncidentReport.status == 'validated'"], {"IncidentReport": {"status": "resources_identified"}}),
        act("propose_allocation", "Propose an allocation of equipment (a recommendation, not a decision)", "logistics.plan",
            ["IncidentReport.status == 'resources_identified'", "Resource.status == 'available'"],
            {"IncidentReport": {"status": "allocation_proposed"}, "Resource": {"status": "reserved"}}),
        act("assign_response_team", "Assign the proposed team to the incident", "dispatch.assign",
            ["IncidentReport.status == 'allocation_proposed'", "ResponseTeam.status == 'available'"],
            {"IncidentReport": {"status": "response_assigned"}, "ResponseTeam": {"status": "assigned"},
             "Assignment": {"status": "approved"}}, side="non_idempotent"),
        act("publish_update", "Publish an update of the incident for the coordination centre", "reporting.update",
            ["IncidentReport.status == 'response_assigned'"], {"IncidentReport": {"status": "updated"}}, side="idempotent"),
        rule("R-ASSIGN-APPROVAL", "human_review", "A {coordinator_role} approves assigning a team when "
             "{approval_people_threshold} people or more are at risk", ["coordinator_role", "approval_people_threshold"],
             action="assign_response_team", reviewer="{coordinator_role}",
             when="IncidentReport.people_at_risk >= {approval_people_threshold}"),
        rule("R-NO-PREDICTION", "prohibition", "A team is never assigned on a prediction alone: a prediction is not "
             "an observed fact", action="assign_response_team", when="IncidentReport.information_basis == 'predicted'"),
        rule("R-VALIDATE-FIRST", "mandatory_step", "A report is validated before any team is assigned",
             step="validate_report", before="assign_response_team"),
        rule("R-ASSIGN-ROLE", "action_access", "Only a {operations_role} assigns a team", ["operations_role"],
             action="assign_response_team", roles=["{operations_role}"]),
        rule("R-UPDATE-ROLE", "action_access", "Only a {operations_role} publishes an update", ["operations_role"],
             action="publish_update", roles=["{operations_role}"]),
        rule("R-RISK-FIGURE", "write_access", "Only a {coordinator_role} changes the number of people at risk",
             ["coordinator_role"], field="IncidentReport.people_at_risk", roles=["{coordinator_role}"]),
        {"kind": "goal", "name": "incident_handled", "rationale": "The outcome asked for",
         "value": {"description": "The incident has an assigned response and a published update",
                   "target": "IncidentReport.status == 'updated'"}},
        {"kind": "case_template", "name": "incident_case", "rationale": "A run starts from one incident report",
         "value": {"description": "An incident with its area, its proposed assignment, the team and the equipment",
                   "root": "IncidentReport", "entities": {"IncidentReport": "self", "AffectedArea": "^incidents",
                                                         "Assignment": "assignments", "ResponseTeam": "assignments.team",
                                                         "Resource": "assignments.equipment"}}}],
    "roles": [{"name": "{operations_role}", "description": "Handles incidents; the agent acts with this role"},
              {"name": "{coordinator_role}", "description": "Reviewer role: approves assignments when "
                                                            "{approval_people_threshold} people or more are at risk"}],
    "agents": [
        {"name": "incident_intelligence_agent", "description": "Proposed responsibility: validates incoming reports and "
                                                               "keeps facts apart from predictions", "actions": ["validate_report"]},
        {"name": "resource_coordination_agent", "description": "Proposed responsibility: identifies usable teams and "
                                                               "equipment and proposes an allocation",
         "actions": ["identify_resources", "propose_allocation"]},
        {"name": "infrastructure_impact_agent", "description": "Proposed responsibility: relates incidents to impaired "
                                                               "infrastructure (no action of its own in this template)", "actions": []},
        {"name": "logistics_planning_agent", "description": "Proposed responsibility: prepares the assignment of a team, "
                                                            "which a person approves above the limit", "actions": ["assign_response_team"]},
        {"name": "situation_reporting_agent", "description": "Proposed responsibility: publishes incident updates",
         "actions": ["publish_update"]}],
    "integrations": [{"capability": "dispatch.assign", "system": "{dispatch_system}",
                      "description": "Records an assignment; simulated here: nobody is dispatched"}],
    "assumptions": ["One incident has one proposed assignment under evaluation at a time",
                    "A report's basis is recorded as observed, reported or predicted by whoever enters it"],
    "unknowns": ["Evacuation authority and its legal basis", "Validated hazard models (none is used: nothing is forecast)"],
    "sample_case": {"IncidentReport": {"status": "received", "reference": "sample", "description": "sample incident",
                                       "reported_by": "sample", "source_verified": True, "information_basis": "observed",
                                       "people_at_risk": 10, "update_note": "", "simulate_outage": False},
                    "AffectedArea": {"status": "affected", "name": "Sample area", "municipality": "Sample", "population": 1000},
                    "Assignment": {"status": "proposed", "task": "sample", "basis": "recommendation"},
                    "ResponseTeam": {"status": "available", "name": "Sample team", "speciality": "flood response"},
                    "Resource": {"status": "available", "name": "Sample pump", "kind": "equipment", "quantity": 1}},
    "solution": {
        "agents": {"response_coordinator": {
            "purpose": "Takes an incident report to an assigned response and a published update, within the policy",
            "responsibilities": ["Validate the report", "Identify usable teams and equipment", "Propose an allocation",
                                 "Assign a team, or ask the person the policy names", "Publish an update"],
            "roles": ["{operations_role}"], "goals": ["incident_handled"], "autonomy": {"mode": "policy"},
            "tools": [tool("validate_report", "report checked against its source"),
                      {"action": "identify_resources", "tool": "simulated.fail", "when": "IncidentReport.simulate_outage == True",
                       "error": "the resource register is not reachable (simulated outage)"},
                      tool("propose_allocation", "allocation proposed as a recommendation"),
                      tool("assign_response_team", "assignment recorded; nobody was dispatched"),
                      tool("publish_update", "update published to the coordination centre only")]}},
        "sample_data": {"instances": crisis_rows, "links": crisis_links}}})

# ---------------------------------------------------------------------------------------------------------------
# B. Network intelligence: a corporate compliance team and a fictional network of companies
# ---------------------------------------------------------------------------------------------------------------
net_rows = [
    {"type": "Organization", "id": "ORG-1", "status": "active", "name": "Brightwater Supplies Ltd (fictional)",
     "registration_id": "FICT-REG-1001", "jurisdiction": "Fictland", "kind": "customer of the group"},
    {"type": "Organization", "id": "ORG-2", "status": "active", "name": "Calder & Finch Trading (fictional)",
     "registration_id": "FICT-REG-1002", "jurisdiction": "Fictland", "kind": "supplier"},
    {"type": "Organization", "id": "ORG-3", "status": "active", "name": "Dunmore Logistics (fictional)",
     "registration_id": "FICT-REG-1003", "jurisdiction": "Fictland", "kind": "supplier"},
    {"type": "Organization", "id": "ORG-4", "status": "active", "name": "Calder and Finch Trading Limited (fictional)",
     "registration_id": "", "jurisdiction": "Fictland", "kind": "supplier (possibly the same as ORG-2)"},
    {"type": "Organization", "id": "ORG-5", "status": "active", "name": "Eastbrook Agency (fictional)",
     "registration_id": "FICT-REG-1005", "jurisdiction": "Fictland", "kind": "commercial intermediary"},
    {"type": "Person", "id": "PER-1", "status": "active", "name": "A. Example (fictional)", "business_role": "director"},
    {"type": "Person", "id": "PER-2", "status": "active", "name": "B. Sample (fictional)", "business_role": "procurement manager"},
    {"type": "Contract", "id": "CON-1", "status": "active", "reference": "FICT-CON-501", "value": 120000, "signed_on": "2026-02-01"},
    {"type": "Contract", "id": "CON-2", "status": "active", "reference": "FICT-CON-502", "value": 48000, "signed_on": "2026-03-15"},
    {"type": "Invoice", "id": "INV-1", "status": "paid", "reference": "FICT-INV-9001", "amount": 24000, "issued_on": "2026-04-02"},
    {"type": "Invoice", "id": "INV-2", "status": "paid", "reference": "FICT-INV-9002", "amount": 24000, "issued_on": "2026-04-03"},
    {"type": "Invoice", "id": "INV-3", "status": "issued", "reference": "FICT-INV-9003", "amount": 9000, "issued_on": "2026-05-10"},
    {"type": "Payment", "id": "PAY-1", "status": "executed", "reference": "FICT-PAY-7001", "amount": 24000, "paid_on": "2026-04-20"},
    {"type": "Payment", "id": "PAY-2", "status": "executed", "reference": "FICT-PAY-7002", "amount": 24000, "paid_on": "2026-04-21"},
    {"type": "BankAccount", "id": "ACC-1", "status": "active", "identifier": "FICT-ACC-0001", "declared_holder": "ORG-1"},
    {"type": "BankAccount", "id": "ACC-2", "status": "active", "identifier": "FICT-ACC-0002", "declared_holder": "ORG-5"},
    {"type": "BankAccount", "id": "ACC-3", "status": "active", "identifier": "FICT-ACC-0003", "declared_holder": "ORG-3"},
    {"type": "OwnershipDeclaration", "id": "OWN-1", "status": "declared", "share_percent": 40, "valid_from": "2025-01-01",
     "valid_to": "", "source": "annual declaration 2025 (fictional)"},
    {"type": "Evidence", "id": "EV-1", "status": "verified", "title": "Registry extract of directors (fictional)",
     "source": "company registry (fictional)", "quality": "primary", "obtained_on": "2026-06-01"},
    {"type": "Evidence", "id": "EV-2", "status": "received", "title": "Payment ledger export (fictional)",
     "source": "group finance (fictional)", "quality": "primary", "obtained_on": "2026-06-02"},
    {"type": "Evidence", "id": "EV-3", "status": "received", "title": "Unsigned note received by post (fictional)",
     "source": "anonymous", "quality": "unverified", "obtained_on": "2026-06-05"},
    {"type": "Association", "id": "ASC-1", "status": "observed_fact", "kind": "shares_director",
     "note": "PER-1 is listed as a director of both companies", "valid_from": "2025-01-01", "valid_to": "",
     "evidence_quality": "primary", "source_reference": "EV-1"},
    {"type": "Association", "id": "ASC-2", "status": "unresolved_hypothesis", "kind": "same_entity",
     "note": "Similar names; one has no registration identifier. Could be one company, a trading name, or two companies",
     "valid_from": "", "valid_to": "", "evidence_quality": "unverified", "source_reference": ""},
    {"type": "Association", "id": "ASC-3", "status": "inference", "kind": "payments_through_intermediary",
     "note": "Two payments of the same amount on consecutive days pass through the intermediary's account",
     "valid_from": "2026-04-20", "valid_to": "2026-04-21", "evidence_quality": "primary", "source_reference": "EV-2"},
    {"type": "Association", "id": "ASC-4", "status": "confirmed_assertion", "kind": "declared_ownership",
     "note": "PER-1 declared a 40 % holding; confirmed by the company secretary (fictional)", "valid_from": "2025-01-01",
     "valid_to": "", "evidence_quality": "primary", "source_reference": "OWN-1"},
    {"type": "Hypothesis", "id": "HYP-1", "status": "open",
     "statement": "Payments to the intermediary may return value to a company that shares a director with the payer",
     "alternative_explanation": "The intermediary is a freight agent paid by both companies for separate shipments; the "
                                "shared directorship was declared in 2025 and the two invoices match two deliveries",
     "basis": "inference from ASC-1 and ASC-3: an association is not proof of wrongdoing"},
    {"type": "Hypothesis", "id": "HYP-2", "status": "open",
     "statement": "The unsigned note alleges an undisclosed link between two suppliers",
     "alternative_explanation": "The note is anonymous and unverified; the similar names may be one company's trading name",
     "basis": "unverified allegation"},
    {"type": "Hypothesis", "id": "HYP-0", "status": "open", "statement": "Routine review: no pattern expected",
     "alternative_explanation": "None needed: nothing unusual was found", "basis": "routine sampling"},
    {"type": "CaseFile", "id": "CASE-3001", "status": "opened", "reference": "CASE-3001", "subject": "Routine review of ORG-2",
     "unusual_links": 0, "unusual_amount": 0, "evidence_quality": "primary", "alternative_recorded": False, "summary_note": ""},
    {"type": "CaseFile", "id": "CASE-3002", "status": "opened", "reference": "CASE-3002",
     "subject": "Payments from ORG-1 through ORG-5 to ORG-3", "unusual_links": 2, "unusual_amount": 48000,
     "evidence_quality": "primary", "alternative_recorded": False, "summary_note": ""},
    {"type": "CaseFile", "id": "CASE-3003", "status": "opened", "reference": "CASE-3003",
     "subject": "Anonymous allegation about ORG-2 and ORG-4", "unusual_links": 1, "unusual_amount": 33000,
     "evidence_quality": "unverified", "alternative_recorded": False, "summary_note": ""}]
net_links = [
    ["CASE-3001", "subjects", "ORG-2"], ["CASE-3001", "hypotheses", "HYP-0"], ["CASE-3001", "evidence", "EV-2"],
    ["CASE-3002", "subjects", "ORG-1"], ["CASE-3002", "subjects", "ORG-3"], ["CASE-3002", "subjects", "ORG-5"],
    ["CASE-3002", "hypotheses", "HYP-1"], ["CASE-3002", "evidence", "EV-1"],
    ["CASE-3003", "subjects", "ORG-2"], ["CASE-3003", "subjects", "ORG-4"], ["CASE-3003", "hypotheses", "HYP-2"],
    ["CASE-3003", "evidence", "EV-3"],
    ["ORG-1", "contracts", "CON-1"], ["ORG-5", "contracts", "CON-1"], ["ORG-3", "contracts", "CON-2"], ["ORG-5", "contracts", "CON-2"],
    ["CON-1", "invoices", "INV-1"], ["CON-2", "invoices", "INV-2"], ["CON-2", "invoices", "INV-3"],
    ["INV-1", "payments", "PAY-1"], ["INV-2", "payments", "PAY-2"],
    ["PAY-1", "paid_from", "ACC-1"], ["PAY-1", "paid_to", "ACC-2"], ["PAY-2", "paid_from", "ACC-2"], ["PAY-2", "paid_to", "ACC-3"],
    ["ORG-1", "accounts", "ACC-1"], ["ORG-5", "accounts", "ACC-2"], ["ORG-3", "accounts", "ACC-3"],
    ["PER-1", "mandates", "ORG-1"], ["PER-1", "mandates", "ORG-3"], ["PER-2", "mandates", "ORG-1"],
    ["ORG-3", "declared_owners", "OWN-1"], ["OWN-1", "owner", "PER-1"],
    ["ASC-1", "first_party", "ORG-1"], ["ASC-1", "second_party", "ORG-3"],
    ["ASC-2", "first_party", "ORG-2"], ["ASC-2", "second_party", "ORG-4"],
    ["ASC-3", "first_party", "ORG-1"], ["ASC-3", "second_party", "ORG-3"],
    ["ASC-4", "first_party", "ORG-3"], ["ASC-4", "second_party", "ORG-3"],
    ["HYP-1", "rests_on", "ASC-1"], ["HYP-1", "rests_on", "ASC-3"], ["HYP-2", "rests_on", "ASC-2"]]

pack("network_intelligence", "network-intelligence", {
    "id": "network_investigation", "name": "Commercial network investigation (synthetic template)",
    "description": "Take a compliance case from the extraction of relationships to a reviewed, auditable summary: an "
                   "unusual pattern is flagged with its competing explanation, and a person decides every escalation. "
                   "A training template on invented companies: it accuses nobody and proves nothing.",
    "keywords": ["investigat", "compliance", "invoice", "payment", "intermediar", "ownership", "contract", "fraud",
                 "network of compan"],
    "parameters": [
        param("materiality_amount", "number", 10000, "From which amount is an unusual pattern worth a case review?",
              "Below it a pattern is noted, not flagged"),
        param("reviewer_role", "name", "compliance_officer", "Which role decides whether a case is escalated?",
              "Every escalation waits for a named person: an association is never treated as proof"),
        param("analyst_role", "name", "investigation_analyst", "Which role works on cases day to day?",
              "Only this role may prepare an escalation; the agent acts with it"),
        param("financial_role", "name", "financial_investigator", "Which role may see bank account records?",
              "Account records are restricted: other roles do not see them"),
        param("case_system", "text", "", "Which system holds the case files (for example a case management system)?",
              "Escalating a case acts outside Autology: it needs a tool, first simulated")],
    "items": [
        ent("Organization", "The brief speaks of a network of companies", "A company or other organisation",
            ["active", "dissolved"], {"name": "string", "registration_id": "string", "jurisdiction": "string", "kind": "string"}),
        ent("Person", "People act for companies in a business role", "An authorised person and a business role",
            ["active"], {"name": "string", "business_role": "string"}),
        ent("Contract", "Companies are bound by contracts", "A contract", ["active", "ended"],
            {"reference": "string", "value": "number", "signed_on": "date"}),
        ent("Invoice", "Contracts are billed", "An invoice", ["issued", "paid", "disputed"],
            {"reference": "string", "amount": "number", "issued_on": "date"}),
        ent("Payment", "Invoices are paid", "A payment", ["executed", "returned"],
            {"reference": "string", "amount": "number", "paid_on": "date"}),
        ent("BankAccount", "Payments move between accounts", "A bank account, by a fictitious identifier",
            ["active", "closed"], {"identifier": "string", "declared_holder": "string"}),
        ent("OwnershipDeclaration", "Beneficial ownership is declared", "A declaration of beneficial ownership, with its period",
            ["declared", "superseded"], {"share_percent": "number", "valid_from": "date", "valid_to": "date", "source": "string"}),
        ent("Association", "A link between two parties is itself a record, with how it is known",
            "A link between two organisations. Its state says how it is known: an observed fact, a confirmed "
            "assertion, an inference, or an unresolved hypothesis",
            ["observed_fact", "confirmed_assertion", "inference", "unresolved_hypothesis"],
            {"kind": "string", "note": "string", "valid_from": "date", "valid_to": "date", "evidence_quality": "string",
             "source_reference": "string"}),
        ent("Evidence", "Findings rest on documents", "A document, with its source and its quality",
            ["received", "verified", "challenged"], {"title": "string", "source": "string", "quality": "string", "obtained_on": "date"}),
        ent("Hypothesis", "An investigation works with hypotheses and their alternatives",
            "An investigative hypothesis with the competing explanation", ["open", "supported", "not_supported"],
            {"statement": "string", "alternative_explanation": "string", "basis": "string"}),
        ent("CaseFile", "The work is organised in case files", "A case file", ["opened", "relationships_extracted",
            "pattern_flagged", "alternatives_recorded", "escalated", "summarised"],
            {"reference": "string", "subject": "string", "unusual_links": "number", "unusual_amount": "number",
             "evidence_quality": "string", "alternative_recorded": "boolean", "summary_note": "string"}),
        ent("ReviewRecord", "A person's decision on a case is recorded", "The record of a person's review decision", ["recorded"],
            {"decided_by": "string", "outcome": "string", "reason": "string"}),
        rel("CaseFile", "subjects", "Organization", "A case examines organisations"),
        rel("CaseFile", "hypotheses", "Hypothesis", "A case holds hypotheses"),
        rel("CaseFile", "evidence", "Evidence", "A case cites evidence"),
        rel("CaseFile", "decisions", "ReviewRecord", "A case records review decisions"),
        rel("Organization", "contracts", "Contract", "An organisation is party to contracts"),
        rel("Contract", "invoices", "Invoice", "A contract is billed by invoices"),
        rel("Invoice", "payments", "Payment", "An invoice is settled by payments"),
        rel("Payment", "paid_from", "BankAccount", "A payment leaves an account"),
        rel("Payment", "paid_to", "BankAccount", "A payment reaches an account"),
        rel("Organization", "accounts", "BankAccount", "An organisation holds accounts"),
        rel("Person", "mandates", "Organization", "A person acts for an organisation"),
        rel("Organization", "declared_owners", "OwnershipDeclaration", "An organisation has declared owners"),
        rel("OwnershipDeclaration", "owner", "Person", "A declaration names an owner"),
        rel("Association", "first_party", "Organization", "A link has a first party"),
        rel("Association", "second_party", "Organization", "A link has a second party"),
        rel("Hypothesis", "rests_on", "Association", "A hypothesis rests on links"),
        act("extract_relationships", "Extract the relationships between the parties of the case", "analysis.extract",
            ["CaseFile.status == 'opened'"], {"CaseFile": {"status": "relationships_extracted"}}),
        act("close_without_finding", "Close the case: nothing unusual was found", "reporting.close",
            ["CaseFile.status == 'relationships_extracted'", "CaseFile.unusual_links == 0"],
            {"CaseFile": {"status": "summarised", "summary_note": "closed without finding"}}, side="idempotent"),
        act("flag_unusual_pattern", "Flag a pattern that merits examination (a flag is not a finding)", "analysis.flag",
            ["CaseFile.status == 'relationships_extracted'", "CaseFile.unusual_links > 0",
             "CaseFile.unusual_amount >= {materiality_amount}"], {"CaseFile": {"status": "pattern_flagged"}}),
        act("record_alternative_explanation", "Record the competing, innocent explanation beside the hypothesis",
            "analysis.alternatives", ["CaseFile.status == 'pattern_flagged'", "Hypothesis.status == 'open'"],
            {"CaseFile": {"status": "alternatives_recorded", "alternative_recorded": "True"}}),
        act("escalate_for_investigation", "Ask for the case to be escalated to a formal investigation", "cases.escalate",
            ["CaseFile.status == 'alternatives_recorded'"], {"CaseFile": {"status": "escalated"}}, side="non_idempotent"),
        act("write_summary", "Write the investigative summary: facts, inferences, alternatives, the decision",
            "reporting.summary", ["CaseFile.status == 'escalated'"],
            {"CaseFile": {"status": "summarised", "summary_note": "summary written after review"}}, side="idempotent"),
        rule("R-ESCALATION-REVIEW", "human_review", "A {reviewer_role} decides every escalation: no association is "
             "treated as proof", ["reviewer_role"], action="escalate_for_investigation", reviewer="{reviewer_role}"),
        rule("R-NO-UNVERIFIED", "prohibition", "A case that rests only on unverified evidence is never escalated",
             action="escalate_for_investigation", when="CaseFile.evidence_quality == 'unverified'"),
        rule("R-ALTERNATIVE-FIRST", "mandatory_step", "The competing explanation is recorded before any escalation",
             step="record_alternative_explanation", before="escalate_for_investigation"),
        rule("R-ESCALATE-ROLE", "action_access", "Only a {analyst_role} prepares an escalation", ["analyst_role"],
             action="escalate_for_investigation", roles=["{analyst_role}"]),
        rule("R-ACCOUNT-ROWS", "row_access", "Only a {financial_role} sees bank account records", ["financial_role"],
             entity="BankAccount", roles=["{financial_role}"]),
        rule("R-FLAG-FIGURES", "write_access", "Only a {analyst_role} changes the count of unusual links",
             ["analyst_role"], field="CaseFile.unusual_links", roles=["{analyst_role}"]),
        {"kind": "goal", "name": "case_summarised", "rationale": "The outcome asked for",
         "value": {"description": "The case has an auditable summary", "target": "CaseFile.status == 'summarised'"}},
        {"kind": "case_template", "name": "investigation_case", "rationale": "A run starts from one case file",
         "value": {"description": "A case file with its hypotheses and its evidence", "root": "CaseFile",
                   "entities": {"CaseFile": "self", "Hypothesis": "hypotheses", "Evidence": "evidence"}}}],
    "roles": [{"name": "{analyst_role}", "description": "Works on cases; the agent acts with this role"},
              {"name": "{reviewer_role}", "description": "Reviewer role: decides every escalation"},
              {"name": "{financial_role}", "description": "May see bank account records"}],
    "agents": [
        {"name": "entity_resolution_agent", "description": "Proposed responsibility: proposes when two records may be "
                                                           "the same party, as a hypothesis (no action of its own here)", "actions": []},
        {"name": "relationship_analysis_agent", "description": "Proposed responsibility: extracts relationships and "
                                                               "flags patterns that merit examination",
         "actions": ["extract_relationships", "flag_unusual_pattern"]},
        {"name": "evidence_review_agent", "description": "Proposed responsibility: records the competing explanation "
                                                         "and the quality of the evidence", "actions": ["record_alternative_explanation"]},
        {"name": "transaction_consistency_agent", "description": "Proposed responsibility: compares invoices, payments "
                                                                 "and contracts (no action of its own here)", "actions": []},
        {"name": "case_reporting_agent", "description": "Proposed responsibility: prepares escalations for a person's "
                                                        "decision and writes summaries",
         "actions": ["close_without_finding", "escalate_for_investigation", "write_summary"]}],
    "integrations": [{"capability": "cases.escalate", "system": "{case_system}",
                      "description": "Opens a formal investigation; simulated here: nothing is opened anywhere"}],
    "assumptions": ["A flag means that something merits examination: it is never a finding about a person or a company",
                    "Each link between parties is recorded with how it is known and the document it rests on"],
    "unknowns": ["Legal basis and retention rules for investigation records", "Which external sources may be consulted, if any"],
    "sample_case": {"CaseFile": {"status": "opened", "reference": "sample", "subject": "sample", "unusual_links": 1,
                                 "unusual_amount": 20000, "evidence_quality": "primary", "alternative_recorded": False,
                                 "summary_note": ""},
                    "Hypothesis": {"status": "open", "statement": "sample", "alternative_explanation": "sample", "basis": "sample"},
                    "Evidence": {"status": "verified", "title": "sample", "source": "sample", "quality": "primary",
                                 "obtained_on": "2026-01-01"}},
    "solution": {
        "agents": {"case_analyst": {
            "purpose": "Takes a case file from the extraction of relationships to a reviewed, auditable summary",
            "responsibilities": ["Extract relationships", "Flag a pattern that merits examination", "Record the competing "
                                 "explanation", "Prepare an escalation for the person the policy names", "Write the summary"],
            "roles": ["{analyst_role}"], "goals": ["case_summarised"], "autonomy": {"mode": "policy"},
            "tools": [tool("extract_relationships", "relationships listed from the case's records"),
                      tool("close_without_finding", "case closed without finding"),
                      tool("flag_unusual_pattern", "pattern flagged for examination; a flag is not a finding"),
                      tool("record_alternative_explanation", "competing explanation recorded beside the hypothesis"),
                      tool("escalate_for_investigation", "escalation recorded; no investigation was opened anywhere"),
                      tool("write_summary", "summary written from the case's records")]}},
        "sample_data": {"instances": net_rows, "links": net_links}}})

# the platform that hosts both applications: two workspaces, separate people, templates offered to one workspace each
(HERE / "platform.json").write_text(json.dumps({
    "data_dir": "data",
    "templates": {
        "crisis-blank": {"name": "Blank solution (crisis management pack)", "workspaces": ["crisis"],
                         "description": "An empty model with the sandbox architect and the crisis management templates "
                                        "(synthetic; no language model)", "config": "crisis_management/server.json"},
        "netintel-blank": {"name": "Blank solution (network intelligence pack)", "workspaces": ["netintel"],
                           "description": "An empty model with the sandbox architect and the network investigation "
                                          "templates (synthetic; no language model)", "config": "network_intelligence/server.json"}},
    "workspaces": {
        "crisis": {"name": "Autology Crisis Management (synthetic)", "release_approvers": ["rosa"],
                   "members": [{"name": "carla", "token_env": "CRISIS_TOKEN_CARLA", "workspace_admin": True},
                               {"name": "rosa", "token_env": "CRISIS_TOKEN_ROSA"},
                               {"name": "omar", "token_env": "CRISIS_TOKEN_OMAR"},
                               {"name": "dana", "token_env": "CRISIS_TOKEN_DANA"},
                               {"name": "alex", "token_env": "CRISIS_TOKEN_ALEX"}],
                   "use_cases": {}},
        "netintel": {"name": "Autology Network Intelligence (synthetic)", "release_approvers": ["ravi"],
                     "members": [{"name": "nora", "token_env": "NETINTEL_TOKEN_NORA", "workspace_admin": True},
                                 {"name": "ravi", "token_env": "NETINTEL_TOKEN_RAVI"},
                                 {"name": "alan", "token_env": "NETINTEL_TOKEN_ALAN"},
                                 {"name": "cleo", "token_env": "NETINTEL_TOKEN_CLEO"},
                                 {"name": "alex", "token_env": "NETINTEL_TOKEN_ALEX"}],
                     "use_cases": {}}}}, indent=1) + "\n")
print("written:", sorted(str(p.relative_to(HERE)) for p in HERE.rglob("*.json")))
