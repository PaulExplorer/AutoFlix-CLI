"""Non-interactive CLI mode: ``autoflix`` with command line flags.

Exposes the content API (search, content, stream extraction) without any
menus. With no flags at all, the classic interactive interface runs instead
(:func:`autoflix_cli.main._run`).
"""

import argparse
import importlib.metadata
import json
import sys

from . import api
from .cli_utils import console, print_error

try:
    _VERSION = importlib.metadata.version("autoflix-cli")
except importlib.metadata.PackageNotFoundError:
    _VERSION = "dev"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="autoflix",
        description="Watch movies, series and anime from the terminal "
        "(no flags = interactive mode).",
    )
    parser.add_argument(
        "--version", action="version", version=f"autoflix {_VERSION}"
    )

    # Commands
    parser.add_argument(
        "--search", metavar="QUERY", help="search content on the providers"
    )
    parser.add_argument(
        "--url", metavar="URL",
        help="show content details for a provider URL (movie, series...)",
    )
    parser.add_argument(
        "--index", type=int, metavar="N",
        help="with --search: show the details of result N instead of the list",
    )
    parser.add_argument(
        "--extract", metavar="PLAYER_URL",
        help="resolve an embed player URL into a direct stream URL",
    )
    parser.add_argument(
        "--providers", action="store_true",
        help="list the available providers",
    )

    # Options
    parser.add_argument(
        "--provider", metavar="NAME", help="restrict to one provider "
        "(coflix, anime-sama, french-stream, arkanime); auto-detected "
        "from --url/--extract when the URL speaks for itself"
    )
    parser.add_argument(
        "--json", action="store_true",
        help="machine-readable JSON output instead of a table",
    )
    return parser



def _emit(data) -> None:
    """Print any API object as indented JSON."""
    print(json.dumps(api.to_dict(data), indent=2, ensure_ascii=False))


def _print_results(results) -> None:
    from rich.table import Table
    table = Table(title=f"{len(results)} result(s)")
    table.add_column("#", justify="right", style="cyan")
    table.add_column("Provider", style="magenta")
    table.add_column("Title", style="white")
    table.add_column("URL", style="dim")
    for i, r in enumerate(results):
        table.add_row(str(i), r.provider, r.title, r.url)
    console.print(table)


def _print_content(obj) -> None:
    if isinstance(obj, api.Episode):
        console.print(f"[bold cyan]{obj.title}[/bold cyan] "
                      f"([magenta]{obj.provider}[/magenta], episode)")
        console.print("  players:")
        for p in obj.players or []:
            console.print(f"    [cyan]-[/cyan] {p.name}: {p.url}")
        return
    content = obj
    console.print(f"[bold cyan]{content.title}[/bold cyan] "
                  f"([magenta]{content.provider}[/magenta], {content.kind})")
    if content.genres:
        console.print(f"  genres: {', '.join(str(g).strip() for g in content.genres)}")
    if content.players is not None:
        console.print("  players:")
        for p in content.players:
            console.print(f"    [cyan]-[/cyan] {p.name}: {p.url}")
    if content.episodes is not None:
        console.print("  episodes:")
        for e in content.episodes:
            console.print(f"    [cyan]-[/cyan] {e.title}: {e.url or '(built-in players)'}")
    if content.seasons is not None:
        console.print("  seasons:")
        for s in content.seasons:
            if s.url and not s.episodes:
                console.print(f"    [cyan]-[/cyan] {s.title} -> {s.url}")
                continue
            console.print(f"    [cyan]-[/cyan] {s.title}")
            for e in s.episodes or []:
                console.print(f"      [dim]-[/dim] {e.title}: {e.url}")


def run_cli(argv: list[str]) -> int:
    """Run one non-interactive command. Returns the process exit code."""
    args = _build_parser().parse_args(argv)
    if not (args.search or args.url or args.index is not None
            or args.extract or args.providers):
        _build_parser().print_help()
        return 0

    try:
        if args.index is not None and not args.search:
            print_error("--index requires --search")
            return 1

        if args.extract:
            stream = api.extract(args.extract, provider=args.provider)
            if stream is None:
                print_error("could not extract a stream from this URL")
                return 1
            print(stream if args.json is False else json.dumps({"stream": stream}))
            return 0

        results = None
        if args.search:
            results = api.search(args.search, provider=args.provider)

        if args.url or (results and args.index is not None):
            if args.index is not None and results is not None:
                if not 0 <= args.index < len(results):
                    print_error(f"index {args.index} out of range ({len(results)} results)")
                    return 1
                provider, url = results[args.index].provider, results[args.index].url
            else:
                provider, url = args.provider, args.url
            content = api.get(provider, url)
            if args.json:
                _emit(content)
            else:
                if results is not None:
                    _print_results(results)
                _print_content(content)
            return 0

        if results is not None:
            if args.json:
                _emit(results)
            else:
                _print_results(results)
            return 0

        if args.providers:
            if args.json:
                print(json.dumps(api.PROVIDERS, indent=2))
            else:
                for name, desc in api.PROVIDERS.items():
                    console.print(f"  [magenta]{name:<14}[/magenta] {desc}")
            return 0
    except KeyboardInterrupt:
        print("\nInterrupted.")
        return 130
    except Exception as e:
        print_error(str(e))
        return 1
