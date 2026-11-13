"""Open HTML reports in headless Chromium; fail on any console message or page error.

    python scripts/check_html.py examples/reports/*.html [--screenshots DIR]

Needs Playwright (``pip install playwright && playwright install chromium``).
A Content-Security-Policy violation shows up as a console error, so this also
checks that the report's stylesheet hash matches.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from playwright.sync_api import ConsoleMessage, sync_playwright


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("reports", nargs="+", type=Path)
    parser.add_argument("--screenshots", type=Path, help="save a full-page PNG of each report here")
    parser.add_argument("--executable", help="browser binary to use instead of Playwright's")
    args = parser.parse_args(argv)

    failures = 0
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=args.executable)
        for scheme, width in (("light", 1100), ("dark", 1100), ("light", 390)):
            page = browser.new_page(viewport={"width": width, "height": 900}, color_scheme=scheme)
            label = f"{scheme}-{width}"
            for report in args.reports:
                messages: list[str] = []

                def on_console(message: ConsoleMessage, sink: list[str] = messages) -> None:
                    sink.append(f"console {message.type}: {message.text}")

                page.on("console", on_console)
                page.on("pageerror", lambda error, sink=messages: sink.append(f"error: {error}"))
                page.goto(report.resolve().as_uri())
                page.wait_for_load_state("load")
                styled = page.evaluate(
                    "getComputedStyle(document.querySelector('.grade')).borderTopStyle"
                )
                if styled != "solid":
                    messages.append("stylesheet not applied (CSP hash mismatch?)")
                if args.screenshots:
                    args.screenshots.mkdir(parents=True, exist_ok=True)
                    page.screenshot(
                        path=str(args.screenshots / f"{report.stem}-{label}.png"), full_page=True
                    )
                status = "ok" if not messages else "FAIL"
                print(f"{status:4}  {label:10}  {report}")
                for message in messages:
                    print(f"      {message}")
                failures += bool(messages)
                page.remove_listener("console", on_console)
            page.close()
        browser.close()
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
