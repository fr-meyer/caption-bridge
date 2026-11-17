"""Fail-closed account catalogue reconciliation, independent lifecycle evidence."""
from __future__ import annotations

import asyncio
import time


class ModelCatalogue:
    def __init__(self, ttl=300, timeout=5, clock=time.monotonic):
        self.ttl, self.timeout, self.clock = ttl, timeout, clock
        self.verified_at = self.attempted_at = None
        self.error = None
        self.entries = []
        self._lock = asyncio.Lock()

    @property
    def fresh(self):
        return self.verified_at is not None and self.clock() - self.verified_at < self.ttl

    async def refresh(self, loader, lifecycle, policies):
        async with self._lock:
            if self.attempted_at is not None and self.clock() - self.attempted_at < self.ttl:
                return
            self.attempted_at = self.clock()
            try:
                rows = await asyncio.wait_for(loader(), self.timeout)
                if not isinstance(rows, list) or len(rows) > 2000:
                    raise ValueError("invalid catalogue")
                entries = reconcile(rows, lifecycle, policies)
            except asyncio.CancelledError:
                raise
            except Exception:
                self.error = "catalogue_refresh_failed"
                return
            self.entries, self.verified_at, self.error = entries, self.clock(), None

    def snapshot(self):
        fresh = self.fresh and self.error is None
        return {"fresh": fresh, "last_verified": self.verified_at, "error": self.error,
                "models": [dict(row, enabled=row["enabled"] and fresh) for row in self.entries]}


def reconcile(rows, lifecycle, policies):
    """Never infer lifecycle, family, alias or execution contract from an ID."""
    expanded = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        expanded.append(row)
        aliases = row.get("aliases", [])
        if isinstance(aliases, list):
            for alias in aliases[:100]:
                if isinstance(alias, str) and lifecycle.get(alias, {}).get("alias") == alias:
                    expanded.append(dict(row, id=alias, catalogue_target=row.get("id")))
    by_id = {}
    for row in expanded:
        if isinstance(row, dict) and isinstance(row.get("id"), str):
            by_id.setdefault(row["id"], []).append(row)
    selected, disabled = {}, []
    for model, duplicates in by_id.items():
        row, evidence = duplicates[0], lifecycle.get(model, {})
        reason = None
        if any(item != row for item in duplicates):
            reason = "conflicting_account_metadata"
        elif row.get("capabilities", {}).get("completion_chat") is not True:
            reason = "text_chat_not_supported"
        elif evidence.get("status") != "active":
            reason = "lifecycle_" + evidence.get("status", "unknown")
        elif row.get("catalogue_target") and lifecycle.get(row["catalogue_target"], {}).get("status") != "active":
            reason = "alias_target_unverified"
        elif model not in policies:
            reason = "execution_policy_unverified"
        item = {"id": model, "label": row.get("name") or model,
                "enabled": reason is None, "reason": reason,
                "qualification": "source_only_not_live_qualified",
                "catalogue_target": row.get("catalogue_target"),
                "version_policy": "official_alias" if evidence.get("alias") == model else "versioned",
                "efforts": policies.get(model, {}).get("efforts", ["default"])}
        if reason:
            disabled.append(item)
            continue
        family = evidence.get("family", model)
        rank = (item["version_policy"] == "official_alias", evidence.get("release", 0))
        if family not in selected or rank > selected[family][0]:
            selected[family] = (rank, item)
    return [item for _, item in selected.values()] + disabled
