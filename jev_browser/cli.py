"""Command-line entry point; task results are JSON on stdout."""
import argparse
import json
import sys

from .client import Browser, error
from .doctor import diagnose


def main(argv=None):
    parser = argparse.ArgumentParser(prog="jev-browser", description="Jev decisions driving your Camofox browser")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="Run one task and close its isolated browser session")
    run.add_argument("url")
    run.add_argument("goal")
    run.add_argument("--max-steps", type=int, default=25)
    run.add_argument("--max-model-calls", type=int, default=100)
    run.add_argument("--timeout", type=float, default=300)
    run.add_argument("--vision", choices=("off", "auto", "always"))
    run.add_argument("--require-visual", action=argparse.BooleanOptionalAction, default=None)
    doctor = sub.add_parser("doctor", help="Check configuration and browser health without a paid model call")
    doctor.add_argument("--probe", action="store_true", help="Also open and close an example.com tab to check /evaluate")
    doctor.add_argument("--vision", action="store_true", help="Check masked capture without uploading an image")
    doctor.add_argument("--vision-model-probe", action="store_true", help="Explicitly make a paid image request on a throwaway example.com tab")
    sub.add_parser("mcp", help="Serve tools over stdio (install the mcp extra)")
    args = parser.parse_args(argv)
    try:
        if args.command == "mcp":
            try:
                from .mcp_server import serve
            except ImportError:
                print("MCP requires the optional SDK. From your source checkout run: python -m pip install '.[mcp]'", file=sys.stderr)
                return 2
            serve()
            return 0
        if args.command == "doctor":
            options = {}
            if args.vision or args.vision_model_probe:
                options = {"vision": args.vision, "vision_model_probe": args.vision_model_probe}
            result = diagnose(probe=args.probe, **options)
            code = 0 if result["ok"] else 1
        else:
            with Browser() as browser:
                options = {}
                if args.vision is not None or args.require_visual is not None:
                    options = {"vision": args.vision, "require_visual": args.require_visual}
                result = browser.start(args.url, args.goal, max_steps=args.max_steps,
                                       max_model_calls=args.max_model_calls, timeout=args.timeout, **options)
            if warnings := getattr(browser, "cleanup_warnings", []):
                result["warnings"] = list(warnings)
            code = {"done": 0, "paused": 3}.get(result["status"], 1)
    except ValueError as e:
        result, code = error(str(e)), 2
    except KeyboardInterrupt:
        result, code = {"status": "paused", "reason": "cancelled"}, 130
    print(json.dumps(result, ensure_ascii=False))
    return code
