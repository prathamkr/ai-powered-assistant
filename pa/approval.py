"""Approval gate, separate from Android permission. Approval is bound to the exact payload
(sha256) and each action can execute at most once."""
import copy
import hashlib
import json
import threading
import uuid
from dataclasses import dataclass

from .adapters.base import Result


def payload_hash(payload):
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"),
                                     default=str).encode()).hexdigest()


class Unsupported(Exception):
    pass


@dataclass
class Action:
    id: str
    type: str
    payload: dict
    hash: str
    state: str = "pending"  # pending|executing|done|handed_off|failed|denied|rejected|invalidated|unsupported


class ApprovalEngine:
    def __init__(self, store, adapters):
        self.store = store
        self.adapters = adapters
        self.actions = {}
        self._lock = threading.Lock()

    def propose(self, action_type, payload):
        ad = self.adapters.get(action_type)
        if ad is None or not ad.capability_check():
            raise Unsupported(action_type)
        payload = copy.deepcopy(payload)
        errs = ad.validate(payload)
        if errs:
            raise ValueError("; ".join(errs))
        a = Action(uuid.uuid4().hex[:12], action_type, payload, payload_hash(payload))
        self.actions[a.id] = a
        self.store.audit(a.id, a.type, "proposed", "not_run")
        return a, ad.preview(payload)

    def run_direct(self, action_type, payload, reason):
        """Execute without an approval tap, for actions the USER chose to allow that way.
        Still validated and audited; reason is recorded as the approval state."""
        ad = self.adapters.get(action_type)
        if ad is None or not ad.capability_check():
            raise Unsupported(action_type)
        payload = copy.deepcopy(payload)
        errs = ad.validate(payload)
        if errs:
            raise ValueError("; ".join(errs))
        a = Action(uuid.uuid4().hex[:12], action_type, payload, payload_hash(payload), state="executing")
        self.actions[a.id] = a
        self.store.audit(a.id, a.type, "not_required:" + reason, "executing")
        try:
            res = ad.execute(copy.deepcopy(payload))
        except Exception as ex:
            res = Result("failed", type(ex).__name__)
        a.state = res.status
        self.store.audit(a.id, a.type, "not_required:" + reason, res.status)
        return res

    def reject(self, action_id):
        with self._lock:
            a = self.actions.get(action_id)
            if not a or a.state != "pending":
                return False
            a.state = "rejected"
        self.store.audit(a.id, a.type, "rejected", "not_run")
        return True

    def approve(self, action_id, shown_hash):
        """shown_hash = hash of the payload the user actually saw."""
        with self._lock:
            a = self.actions.get(action_id)
            if a is None:
                return Result("failed", "unknown action")
            if a.state != "pending":
                return Result("duplicate", "already " + a.state)  # repeated tap / retry: do nothing
            if payload_hash(a.payload) != a.hash or shown_hash != a.hash:
                a.state = "invalidated"
                self.store.audit(a.id, a.type, "invalidated", "not_run")
                return Result("invalidated", "payload changed after it was shown")
            ad = self.adapters[a.type]
            if ad.permission_check() == "denied":
                a.state = "denied"
                self.store.audit(a.id, a.type, "approved", "permission_denied")
                return Result("denied", "Android permission denied")
            a.state = "executing"
            payload = copy.deepcopy(a.payload)
        self.store.audit(a.id, a.type, "approved", "executing")
        try:
            res = ad.execute(payload)
        except Exception as ex:
            res = Result("failed", type(ex).__name__)
        with self._lock:
            a.state = res.status
        self.store.audit(a.id, a.type, "approved", res.status)
        return res
