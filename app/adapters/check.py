"""CLI self-check for a configured scheduler adapter."""

from __future__ import annotations

import argparse
import json

from app.adapters.contract import check_adapter_contract
from app.adapters.factory import get_adapter
from app.models import AsOf, AsOfKind, ComparisonContext, SchedulerType


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a scheduler adapter contract")
    parser.add_argument("--environment", required=True)
    parser.add_argument("--scheduler", required=True, choices=[item.value for item in SchedulerType])
    parser.add_argument("--as-of", default="")
    parser.add_argument(
        "--as-of-kind",
        default=AsOfKind.BUSINESS_DATE.value,
        choices=[item.value for item in AsOfKind],
    )
    args = parser.parse_args()

    context = ComparisonContext(
        environment_id=args.environment,
        scheduler=SchedulerType(args.scheduler),
        as_of=AsOf(kind=AsOfKind(args.as_of_kind), value=args.as_of),
    )
    adapter = get_adapter(context.scheduler, context.environment_id)
    report = check_adapter_contract(adapter, context)
    payload = report.model_dump(mode="json")
    payload["passed"] = report.passed
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
