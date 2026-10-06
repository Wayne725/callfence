import argparse
from importlib.resources import files
import json
from pathlib import Path
import shutil
import sys

from .engine import check, compare, exit_code
from .report import export_report


def main(argv=None):
    parser = argparse.ArgumentParser(prog="callfence", description="Check offline consumer request samples against OpenAPI 3.1 JSON.")
    commands = parser.add_subparsers(dest="command", required=True)
    check_parser = commands.add_parser("check", help="Check one specification.")
    check_parser.add_argument("spec")
    check_parser.add_argument("cases")
    compare_parser = commands.add_parser("compare", help="Check both snapshots and label observed changes.")
    compare_parser.add_argument("baseline")
    compare_parser.add_argument("candidate")
    compare_parser.add_argument("cases")
    demo_parser = commands.add_parser("demo", help="Produce the synthetic comparison, including expected failures.")
    for command in (check_parser, compare_parser, demo_parser):
        command.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "demo":
            example_dir = files("callfence").joinpath("examples")
            report = compare(example_dir.joinpath("baseline.json"), example_dir.joinpath("candidate.json"), example_dir.joinpath("consumer.json"))
        elif args.command == "check":
            report = check(args.spec, args.cases)
        else:
            report = compare(args.baseline, args.candidate, args.cases)
        output = export_report(report, args.out)
        if args.command == "demo":
            (output / "inputs").mkdir()
            for name in ("baseline.json", "candidate.json", "consumer.json"):
                shutil.copyfile(example_dir.joinpath(name), output / "inputs" / name)
        summary = report["runs"][-1]["summary"]
        print(f"{report['consumer']}: {summary['passed']} passed, {summary['failed']} failed, {summary['blocked']} blocked")
        print(f"Report: {output / 'report.html'}")
        if report["mode"] == "compare":
            print(json.dumps(report["change_summary"], sort_keys=True))
        if args.command == "demo":
            print("Demo generated. Its candidate intentionally fails; check/compare enforce exit code 1.")
            return 0
        return exit_code(report)
    except (ValueError, OSError, UnicodeError, RecursionError) as error:
        print(f"Input/output error: {error}", file=sys.stderr)
        return 2
