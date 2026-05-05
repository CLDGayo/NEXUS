"""
NEXUS RAG — Vault File Watcher

Watches the Obsidian vault for file changes and automatically
re-indexes modified notes into Qdrant.

Run in a terminal while working in Obsidian:
    python watcher.py
"""

import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from rich.console import Console
from watchdog.events import FileModifiedEvent, FileCreatedEvent, FileDeletedEvent, FileSystemEventHandler
from watchdog.observers import Observer

load_dotenv()

VAULT_PATH = Path(os.environ["VAULT_PATH"])
SKIP_FOLDERS = {"_publish", ".obsidian", ".git", "rag", "node_modules"}
DEBOUNCE_SECONDS = 3.0  # wait this long after last change before indexing

console = Console()


class VaultHandler(FileSystemEventHandler):
    def __init__(self):
        self._pending: dict[str, float] = {}

    def _should_process(self, path: str) -> bool:
        p = Path(path)
        if p.suffix != ".md":
            return False
        return not any(skip in p.parts for skip in SKIP_FOLDERS)

    def on_modified(self, event):
        if not event.is_directory and self._should_process(event.src_path):
            self._pending[event.src_path] = time.time()

    def on_created(self, event):
        if not event.is_directory and self._should_process(event.src_path):
            self._pending[event.src_path] = time.time()

    def on_deleted(self, event):
        if not event.is_directory and self._should_process(event.src_path):
            console.print(f"[yellow]Deleted:[/yellow] {Path(event.src_path).name} (manual Qdrant cleanup needed)")

    def drain(self) -> list[str]:
        """Return paths that have been stable for DEBOUNCE_SECONDS."""
        now = time.time()
        ready = [p for p, t in self._pending.items() if now - t >= DEBOUNCE_SECONDS]
        for p in ready:
            del self._pending[p]
        return ready


def reindex_file(rel_path: str) -> None:
    """Trigger ingest.py for a single file."""
    import subprocess
    result = subprocess.run(
        [sys.executable, str(Path(__file__).parent / "ingest.py"), "--file", rel_path],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        console.print(f"[green]Indexed:[/green] {rel_path}")
    else:
        console.print(f"[red]Index failed:[/red] {rel_path}\n{result.stderr}")


def main():
    console.rule("[bold blue]NEXUS Vault Watcher[/bold blue]")
    console.print(f"Watching: [cyan]{VAULT_PATH}[/cyan]")
    console.print("Edit any note in Obsidian — it will be re-indexed automatically.\n")

    handler = VaultHandler()
    observer = Observer()
    observer.schedule(handler, str(VAULT_PATH), recursive=True)
    observer.start()

    try:
        while True:
            time.sleep(1)
            ready = handler.drain()
            for abs_path in ready:
                rel_path = str(Path(abs_path).relative_to(VAULT_PATH))
                console.print(f"[dim]Change detected:[/dim] {rel_path}")
                reindex_file(rel_path)
    except KeyboardInterrupt:
        observer.stop()
        console.print("\n[dim]Watcher stopped.[/dim]")

    observer.join()


if __name__ == "__main__":
    main()
