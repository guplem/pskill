"""Command-line interface of the runner."""

import argparse

from pskill_runner import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pskill", description="Run programmatic skills one block at a time.")
    parser.add_argument("--version", action="version", version=f"pskill {__version__}")
    return parser


def main(arguments: list[str] | None = None) -> int:
    build_parser().parse_args(arguments)
    return 0
