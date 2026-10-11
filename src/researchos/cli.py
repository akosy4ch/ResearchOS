import argparse
import asyncio
import json
import os

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(prog="researchos")
    subparsers = parser.add_subparsers(dest="command", required=True)
    serve = subparsers.add_parser("serve", help="Start the local API")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    maintain = subparsers.add_parser("maintain", help="Check ResearchOS and repair validated source issues")
    maintain.add_argument("--startup", action="store_true", help="Run a preflight check before serving")
    args = parser.parse_args()

    if args.command == "serve":
        from researchos.config import settings
        from researchos.system_care import run_system_care

        def preflight(label: str) -> dict:
            report = asyncio.run(run_system_care(label, allow_repairs=True, ask_for_improvements=False))
            print(json.dumps({"status": report["status"], "diagnosis": report["diagnosis"],
                              "repairs": report["repairs"], "report_id": report["id"]}, ensure_ascii=False))
            return report

        preflight("startup preflight")
        os.environ["RESEARCHOS_SUPERVISED"] = "1"
        restart_marker = settings.data_dir / "system-care" / "restart-required"
        while True:
            uvicorn.run("researchos.main:app", host=args.host, port=args.port, reload=False)
            if not restart_marker.is_file():
                break
            restart_marker.unlink(missing_ok=True)
            os.environ.pop("RESEARCHOS_SUPERVISED", None)
            preflight("supervisor restart preflight")
            os.environ["RESEARCHOS_SUPERVISED"] = "1"
    elif args.command == "maintain":
        from researchos.system_care import run_system_care
        report = asyncio.run(run_system_care("startup preflight" if args.startup else "manual CLI check",
                                             allow_repairs=True, ask_for_improvements=False))
        print(json.dumps({"status": report["status"], "diagnosis": report["diagnosis"],
                          "repairs": report["repairs"], "report_id": report["id"]}, ensure_ascii=False, indent=2))
