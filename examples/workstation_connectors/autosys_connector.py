"""Bank-local AutoSys connector template for scheduler-bridge/v1.

Copy together with bridge_v1_runtime.py into workstation_connectors/ and edit only
this file. It must not import the web application's ``app`` package.
"""

from __future__ import annotations

from typing import Any

from bridge_v1_runtime import ConnectorError, run


class AutoSysProvider:
    scheduler = "autosys"

    def capabilities(self) -> dict[str, Any]:
        # Keep strict support enabled in production and explicitly declare every
        # comparison field once the source mapping is known.
        return {
            "topology": True,
            "dependencies": True,
            "runtime": True,
            "job_detail": True,
            "root_listing": True,
            "autosys_projection": True,
            "strict_parameter_support": False,
            "parameter_support": {},
        }

    def health(self, context: dict[str, Any]) -> dict[str, Any]:
        # BANK-LOCAL IMPLEMENTATION: call the existing AutoSys Python tool/API.
        return {"healthy": False, "message": "AutoSys connector is not wired yet"}

    def list_roots(self, context: dict[str, Any]) -> dict[str, Any]:
        # Return: {"roots": ["BOX_A", "BOX_B"]}
        raise ConnectorError("not_configured", "Implement AutoSys root listing on this workstation")

    def fetch_topology(self, context: dict[str, Any]) -> dict[str, Any]:
        # Return the frozen v1 shape documented in docs/workstation-connector-protocol-v1.md.
        # Do not infer dependency edges from box containment/order.
        raise ConnectorError("not_configured", "Implement AutoSys topology retrieval on this workstation")

    def fetch_job_detail(self, context: dict[str, Any], job_uid: str) -> dict[str, Any]:
        # Return: {"job": <v1 job object or null>}
        raise ConnectorError("not_configured", "Implement AutoSys job detail on this workstation")


if __name__ == "__main__":
    raise SystemExit(run(AutoSysProvider()))
