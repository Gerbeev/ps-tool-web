# Workstation Connectors

This directory is the **bank-local integration boundary**. The web application invokes two fixed filenames when `USE_MOCK_ADAPTERS=false`:

- `autosys_connector.py`
- `process_scheduler_connector.py`

Those implementation files are intentionally git-ignored. Copy the frozen v1 templates from `examples/workstation_connectors/` on the workstation and wire only the source-specific calls to the existing internal Python tool.

The scripts must not import `app` or any web-project module. They communicate only through `scheduler-bridge/v1`: one JSON request on `stdin`, one JSON response on `stdout`, diagnostics on `stderr`.

See `docs/workstation-connector-protocol-v1.md`.
