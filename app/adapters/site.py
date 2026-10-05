"""Registration hook for bank-specific adapters.

This module is intentionally dependency-free in the distributable package. Inside the
bank, implement adapter classes in ``app/adapters/`` (or an internal package) and call
``register_adapter`` here. Avoid dynamic import paths controlled by YAML/environment
values; registration remains explicit and reviewable.

Example::

    from app.adapters.registry import register_adapter
    from app.adapters.bank_autosys import BankAutoSysAdapter
    from app.adapters.bank_process_scheduler import BankProcessSchedulerAdapter

    register_adapter("autosys_prod", lambda env: BankAutoSysAdapter(env))
    register_adapter("process_scheduler_prod", lambda env: BankProcessSchedulerAdapter(env))
"""
