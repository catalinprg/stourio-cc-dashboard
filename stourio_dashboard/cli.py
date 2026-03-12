from __future__ import annotations
import webbrowser
import click
import uvicorn


@click.command()
@click.option("-p", "--port", default=3000, type=int, help="Port to listen on")
@click.option("--host", default="127.0.0.1", help="Host to bind to")
@click.option("-o", "--open", "open_browser", is_flag=True, help="Open browser after starting")
@click.version_option(version="0.1.0", prog_name="stourio-dashboard")
def main(port: int, host: str, open_browser: bool):
    """Stourio CC Dashboard - Local observability for Claude Code sessions."""
    url = f"http://{host}:{port}"
    click.echo(f"\n  Stourio CC Dashboard")
    click.echo(f"  {url}\n")

    if open_browser:
        webbrowser.open(url)

    uvicorn.run(
        "stourio_dashboard.app:app",
        host=host,
        port=port,
        log_level="warning",
    )


if __name__ == "__main__":
    main()
