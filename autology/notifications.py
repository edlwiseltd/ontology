"""Notifications of one engine (ARC-0: taken out of ``AutologyService``; SEC-A, GAP-035 for the rules).

Creating a notification, rendering it for each reader, telling reviewers that facts changed, and handing the
audience-safe copy to webhooks. This service decides nothing by itself: who may read a field or see a record is
asked of the engine it belongs to (``field_hidden``, ``visible``, ``views``), which remains the only authority.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from .graph import Instance
from .server import User, log

if TYPE_CHECKING:
    from .server import AutologyService


class NotificationService:
    def __init__(self, engine: "AutologyService"):
        self.engine = engine

    def _not_for_notifications(self, inst: Instance, attr: str, user: User) -> bool:
        """A field this reader may not be shown in a notification: one a data_access rule hides from them, or
        one that needs a written justification to read (a notification cannot ask for one)."""
        e = self.engine
        return e.field_hidden(inst, attr, user) or f"{inst.type}.{attr}" in e.views.gated

    def _hidden_from_roles(self, inst: Instance, attr: str, roles) -> bool:
        """Whether some role a notification is addressed to may not be shown this field of this record."""
        e = self.engine
        return f"{inst.type}.{attr}" in e.views.gated or any(
            e.field_hidden(inst, attr, User("-", "", frozenset({"read"}), frozenset({role}))) for role in roles)

    def _notify_record(self, kind: str, roles, template: str, inst: Instance, ref: Dict[str, Any]) -> Dict[str, Any]:
        """A notification about one record, from a template with ``{attribute}`` placeholders (GAP-035). The text
        that is stored and sent to webhooks is the one every addressed role may read; each reader later gets
        the text rendered for them (:meth:`list_notifications`)."""
        e = self.engine
        from .integrity import PRIVATE_REF, placeholders, render

        values = {name: (inst.id if name == "id" else inst.get(name)) for name in placeholders(template)}
        message = render(template, values, lambda attr: e._hidden_from_roles(inst, attr, roles))
        return e._notify(kind, roles, message, {**ref, PRIVATE_REF: {"template": template, "values": values}})

    def _evidence_changed(self, changes: Dict[str, List[str]], by: str) -> List[str]:
        """Tell the people who have a decision pending on a record that facts it rests on were changed (GAP-037).
        ``changes`` maps a record id to its decision-critical attributes that changed. The approval itself is
        never used on the new facts: the run re-reads its records when it resumes and asks again (ACT-6).
        Returns the runs concerned."""
        e = self.engine
        if not changes:
            return []
        runs = []
        for review in e.store.list_reviews("pending", limit=10 ** 6):
            linked = e.store.run_sources(review["run_id"]) or {}
            ids = set()
            for src in (linked.get("sources") or {}).values():
                ids.update(src if isinstance(src, list) else [src])
            for iid in sorted(ids & set(changes)):
                with e.graph_lock:
                    inst = e.graph._instances.get(iid)
                etype = inst.type if inst is not None else "record"
                e._notify("evidence_changed", review["request"].get("reviewers") or [],
                             f"Facts behind a pending decision changed: {etype} {iid} ({', '.join(changes[iid])}), "
                             f"changed by {by}. Run {review['run_id']} will ask for approval again on the current "
                             "facts; an approval given on the earlier ones is not used.",
                             {"instance": iid, "run_id": review["run_id"], "review_id": review["review_id"],
                              "attributes": list(changes[iid])})
                if review["run_id"] not in runs:
                    runs.append(review["run_id"])
        return runs

    def _notify(self, kind: str, roles, message: str, ref: Dict[str, Any]) -> Dict[str, Any]:
        e = self.engine
        from .integrity import public_note

        note = e.store.add_notification(kind, roles, message, ref)
        outgoing = public_note(note)  # never the private rendering data: only what every addressed role may read
        for hook in e.webhooks:
            if not hook["kinds"] or kind in hook["kinds"]:
                refused = e._environment_refused(hook["environment"], "a webhook")
                if refused:  # the notification stays in the inbox; nothing leaves the platform
                    log.info("webhook not delivered: %s", refused)
                    continue
                t = threading.Thread(target=e._deliver, args=(hook["url"], outgoing), daemon=True)
                t.start()
                e.deliveries.append(t)
        e.deliveries = [t for t in e.deliveries if t.is_alive()]
        return note

    def list_notifications(self, user: User, since: Optional[str], limit: int) -> Dict[str, Any]:
        e = self.engine
        e.require(user, "read")
        from .integrity import PRIVATE_REF, public_note, render

        unrestricted = "admin" in user.permissions
        roles = None if unrestricted else user.roles | user.reviewer_roles
        items = []
        runs: Dict[str, bool] = {}
        for note in e.store.list_notifications(roles, since, limit=10 ** 9):
            if len(items) >= limit:
                break
            iid = note["ref"].get("instance")
            with e.graph_lock:
                inst = e.graph._instances.get(iid) if iid else None
            if inst is not None and not e.visible(inst, user):
                continue  # don't leak hidden rows through notification text
            run_id = note["ref"].get("run_id")
            if run_id and not unrestricted:  # a notification about a run the reader may not see (GAP-035)
                if run_id not in runs:
                    try:
                        runs[run_id] = e.views.can_see_run(user, e.store.load_run(run_id))
                    except KeyError:
                        runs[run_id] = True  # no such run any more: nothing of it can be shown
                if not runs[run_id]:
                    continue
            private = note["ref"].get(PRIVATE_REF)
            out = public_note(note)
            if private and inst is not None:  # the text for this reader: fields they may not read are not shown
                def not_shown(attr: str, record: Instance = inst) -> bool:
                    return e._not_for_notifications(record, attr, user)

                out["message"] = render(private["template"], private["values"], not_shown)
            items.append(out)
        return {"items": items}
