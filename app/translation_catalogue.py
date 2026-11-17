"""Fail-closed account catalogue reconciliation, independent lifecycle evidence."""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone


class ModelCatalogue:
    def __init__(self, ttl=300, timeout=5, clock=time.monotonic):
        self.ttl, self.timeout, self.clock = ttl, timeout, clock
        self.verified_at = self.attempted_at = None
        self.verified_at_utc = None
        self.public_verified_at = None
        self.error = None
        self.entries = []
        self._lock = asyncio.Lock()

    @property
    def fresh(self):
        return self.verified_at is not None and self.clock() - self.verified_at < self.ttl

    async def refresh(self, loader, lifecycle, policies, *, renew=False):
        async with self._lock:
            if self.attempted_at is not None and self.clock() - self.attempted_at < (min(30, self.ttl / 2) if renew else self.ttl):
                return
            previous_attempt = self.attempted_at
            self.attempted_at = self.clock()
            try:
                rows = await asyncio.wait_for(loader(), self.timeout)
                if not isinstance(rows, list) or len(rows) > 2000:
                    raise ValueError("invalid catalogue")
                entries = reconcile(rows, lifecycle, policies)
            except asyncio.CancelledError:
                self.attempted_at = previous_attempt
                raise
            except Exception:
                self.error = "catalogue_refresh_failed"
                return
            self.entries, self.verified_at, self.error = entries, self.clock(), None
            self.verified_at_utc = datetime.now(timezone.utc).isoformat()

    def snapshot(self):
        fresh = self.fresh and self.error is None
        models = []
        for row in self.entries:
            reason = row.get("reason")
            if not fresh:
                reason = reason or "account_catalogue_stale"
            deprecation = row.get("account_deprecation_at")
            if deprecation and deprecation <= time.time():
                reason = "account_deprecated"
            models.append(dict(row, enabled=row["enabled"] and fresh and reason is None,
                               reason=reason))
        return {"fresh": fresh, "last_verified": self.verified_at_utc,
                "error": self.error, "public_verified_at": self.public_verified_at, "models": models}


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
        targets = {item["catalogue_target"] for item in duplicates if item.get("catalogue_target")}
        if targets:
            row = dict(row, catalogue_target=sorted(targets)[0])
        conflicts = len(targets) > 1 or any(
            item.get("capabilities") != duplicates[0].get("capabilities") or
            item.get("deprecation") != duplicates[0].get("deprecation") for item in duplicates)
        reason = None
        deprecation = None
        if row.get("deprecation"):
            try:
                parsed = datetime.fromisoformat(str(row["deprecation"]).replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                deprecation = parsed.timestamp()
                if deprecation <= time.time():
                    reason = "account_deprecated"
            except (ValueError, TypeError, OverflowError):
                reason = "account_lifecycle_unverified"
        capabilities = row.get("capabilities") or {}
        if not isinstance(capabilities, dict):
            capabilities = {}
        if reason:
            pass
        elif conflicts:
            reason = "conflicting_account_metadata"
        elif capabilities.get("completion_chat") is not True:
            reason = "text_chat_not_supported"
        elif evidence.get("status") != "active":
            reason = "lifecycle_" + evidence.get("status", "unknown")
        elif row.get("catalogue_target") and lifecycle.get(row["catalogue_target"], {}).get("status") != "active":
            reason = "alias_target_unverified"
        elif evidence.get("alias") == model and not row.get("catalogue_target"):
            reason = "alias_target_unverified"
        elif row.get("catalogue_target") and (
            evidence.get("family") != lifecycle.get(row["catalogue_target"], {}).get("family") or
            evidence.get("variant") != lifecycle.get(row["catalogue_target"], {}).get("variant") or
            model not in policies or row["catalogue_target"] not in policies or
            policies[model] != policies[row["catalogue_target"]]
        ):
            reason = "alias_execution_contract_unverified"
        elif model not in policies:
            reason = "execution_policy_unverified"
        item = {"id": model, "label": row.get("name") or model,
                "enabled": reason is None, "reason": reason,
                "qualification": "source_only_not_live_qualified",
                "catalogue_target": row.get("catalogue_target"),
                "account_deprecation_at": deprecation,
                "public_status": evidence.get("status", "unknown"),
                "lifecycle_source": evidence.get("source"),
                "version_policy": "official_alias" if evidence.get("alias") == model else "versioned",
                "efforts": [effort for effort in policies.get(model, {}).get("efforts", ["default"])
                            if effort != "high" or capabilities.get("reasoning") is True]}
        if reason:
            disabled.append(item)
            continue
        family = evidence.get("family", model)
        rank = (item["version_policy"] == "official_alias", evidence.get("release", 0))
        if family not in selected or rank > selected[family][0]:
            selected[family] = (rank, item)
    return [item for _, item in selected.values()] + disabled
