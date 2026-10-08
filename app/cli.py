"""Veloxi Engine command-line interface."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


def _cmd_init_db(_args) -> None:
    from .db import init_db

    init_db()
    print("Database initialized.")


def _cmd_seed(_args) -> None:
    from .db import SessionLocal, init_db
    from .seed import load_seed

    init_db()
    with SessionLocal() as session:
        result = load_seed(session)
    print(
        f"Seed complete: {result['opportunities_created']} new opportunities, "
        f"{result['sources_created']} new sources, {result['skills_linked']} skill links."
    )


def _cmd_ingest(args) -> None:
    from .db import SessionLocal, init_db
    from .ingest.runner import ingest_all, ingest_source
    from .models import Source

    init_db()
    with SessionLocal() as session:
        if args.source is not None:
            source = session.get(Source, args.source)
            if source is None:
                print(f"No source with id {args.source}")
                return
            log = ingest_source(session, source)
            logs = [log]
        else:
            logs = ingest_all(session)
        for log in logs:
            print(
                f"source={log.source_id} ok={log.ok} seen={log.items_seen} "
                f"new={log.items_new} promoted={log.items_promoted}"
                + (f" msg={log.message}" if log.message else "")
            )


def _cmd_validate(args) -> None:
    from .config import settings
    from .db import SessionLocal, init_db
    from .daemon.validation import validate_cycle

    init_db()

    def _once() -> None:
        with SessionLocal() as session:
            print("validate:", validate_cycle(session))

    if args.loop:
        interval = settings.validate_interval_minutes * 60
        print(f"Looping validate every {settings.validate_interval_minutes} min (Ctrl-C to stop).")
        while True:
            _once()
            time.sleep(interval)
    else:
        _once()


def _cmd_career(args) -> None:
    from .db import SessionLocal, init_db
    from .services import career, cv_extract

    path = Path(args.cv)
    data = sys.stdin.buffer.read() if args.cv == "-" else path.read_bytes()
    text = cv_extract.extract_text("cv.txt" if args.cv == "-" else path.name, data)
    if len((text or "").strip()) < 20:
        sys.exit("Could not extract text from the CV. If it's a scanned PDF, pass a text file instead.")

    init_db()
    with SessionLocal() as session:
        result = career.analyze(session, cv_text=text, goal=args.goal, category=args.category)

    if args.json:
        print(json.dumps(result, indent=2, default=str))
        return
    print(f"Goal: {result['goal'] or '(none given)'}")
    print(f"You have: {', '.join(result['haveSkills']) or '-'}")
    print(f"Gap:      {', '.join(result['gapSkills']) or '-'}")
    if not result["roadmap"]:
        print("No matching courses. Run `seed` first, or try a broader --goal.")
    for step in result["roadmap"]:
        print(f"  {step['step']}. {step['title']} ({step['provider']}, {step['difficulty']})")
        print(f"     covers: {', '.join(step['skills'])}")
        print(f"     {step['url']}")


def _cmd_serve(args) -> None:
    import uvicorn

    uvicorn.run("app.main:app", host=args.host, port=args.port, reload=args.reload)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="veloxi", description="Veloxi Engine: opportunity pipeline + API")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init-db", help="Create database tables").set_defaults(func=_cmd_init_db)
    sub.add_parser("seed", help="Load real seed sources + opportunities").set_defaults(func=_cmd_seed)

    p_ing = sub.add_parser("ingest", help="Run ingestion (all enabled sources, or one)")
    p_ing.add_argument("--source", type=int, default=None, help="Ingest only this source id")
    p_ing.set_defaults(func=_cmd_ingest)

    p_val = sub.add_parser("validate", help="Run the validation daemon cycle")
    p_val.add_argument("--loop", action="store_true", help="Run continuously on the configured interval")
    p_val.set_defaults(func=_cmd_validate)

    p_car = sub.add_parser("career", help="Run the Career Agent on a CV (PDF, DOCX or text; '-' for stdin)")
    p_car.add_argument("cv", help="Path to the CV file, or '-' to read text from stdin")
    p_car.add_argument("--goal", default=None, help='Target role, e.g. "data analyst"')
    p_car.add_argument("--category", default=None, help="Restrict to one category")
    p_car.add_argument("--json", action="store_true", help="Print the full result as JSON")
    p_car.set_defaults(func=_cmd_career)

    p_srv = sub.add_parser("serve", help="Run the API with uvicorn")
    p_srv.add_argument("--host", default="0.0.0.0")
    p_srv.add_argument("--port", type=int, default=8000)
    p_srv.add_argument("--reload", action="store_true")
    p_srv.set_defaults(func=_cmd_serve)

    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
