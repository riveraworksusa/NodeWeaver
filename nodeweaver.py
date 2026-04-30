#!/usr/bin/env python3
"""
NodeWeaver — AI-powered Obsidian graph optimizer.
Drop any .md file into this folder. NodeWeaver transforms it
into a connected network of nodes optimized for Obsidian graph view.
"""

import json
import itertools
import logging
import threading
import time
from pathlib import Path

import ollama
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# ── Config ────────────────────────────────────────────────────────────────────
WATCH_DIR     = Path(__file__).parent
PROCESSED_DIR = WATCH_DIR / "PROCESSED"
READY_DIR     = WATCH_DIR / "READY"
MODEL         = "llama3.1"
CHUNK_CHARS   = 12000   # safe context size for llama3.1 on CPU
CHUNK_TIMEOUT = 600     # seconds before a hung chunk is abandoned

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("NodeWeaver")

# ── System prompt ─────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """\
You are NodeWeaver — an AI that transforms raw Markdown files into optimized,
interconnected Obsidian knowledge-graph nodes.

Analyze the input file and restructure it into one or more connected .md files
that produce a rich, visually compelling graph in Obsidian.

━━━ OUTPUT FORMAT ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Always return ONLY a valid JSON object — no prose before or after:

{
  "strategy": "single | hub-and-nodes",
  "reason": "one sentence explaining the split decision",
  "files": [
    {
      "filename": "Exact File Name.md",
      "content": "full markdown content"
    }
  ]
}

━━━ SPLIT DECISION ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
• Use "single"        → file has one focused concept, fewer than 3 major sections
• Use "hub-and-nodes" → file has 3+ major sections that could stand as independent nodes

━━━ FILE STRUCTURE RULES ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Every file must have:
  1. YAML frontmatter (tags in snake_case, type field)
  2. H1 title
  3. At least 2 wikilinks [[Like This]] pointing to real sibling files

Hub file (first file when splitting):
  • Tags include the topic domain
  • Lists every child node as [[wikilinks]]
  • Gives the overview/premise — does NOT duplicate node content

Node files (subsequent files):
  • Top line: **Hub:** [[Hub File Name]]
  • **Related:** [[Node A]] · [[Node B]] (cross-links to siblings)
  • **Prev:** [[...]] · **Next:** [[...]] (sequential navigation where applicable)
  • Core content of that one concept

YAML frontmatter template:
---
tags: [tag-one, tag-two]
type: hub | note | law | chapter | concept | reference | tool
---

━━━ WIKILINK RULES ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
• [[Filename]] must exactly match another file's filename (no anchors for graph edges)
• Every node links back to hub AND to 2+ siblings
• The hub links to every node

━━━ QUALITY RULES ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
• Preserve ALL original content — do not summarize or cut
• Keep the author's voice intact
• Add structure (bullets, headers) only where it improves clarity
• Tags must be specific and useful, not generic (e.g. "law-1" not "content")
"""


# ── JSON helpers ──────────────────────────────────────────────────────────────

def repair_json(text: str) -> str:
    """Escape literal control characters inside JSON string values."""
    result = []
    in_string = False
    escape_next = False
    for char in text:
        if escape_next:
            result.append(char)
            escape_next = False
        elif char == "\\":
            result.append(char)
            escape_next = True
        elif char == '"':
            in_string = not in_string
            result.append(char)
        elif in_string and char == "\n":
            result.append("\\n")
        elif in_string and char == "\r":
            result.append("\\r")
        elif in_string and char == "\t":
            result.append("\\t")
        else:
            result.append(char)
    return "".join(result)


def extract_json(raw: str) -> dict:
    """Parse JSON from model response, handling code fences and unescaped control chars."""
    text = raw.strip()
    if "```json" in text:
        text = text.split("```json", 1)[1].split("```", 1)[0].strip()
    elif "```" in text:
        text = text.split("```", 1)[1].split("```", 1)[0].strip()
    return json.loads(repair_json(text))


# ── Text chunking ─────────────────────────────────────────────────────────────

def chunk_text(text: str, size: int) -> list[str]:
    """Split text on paragraph boundaries near each size limit."""
    chunks, current, count = [], [], 0
    for para in text.split("\n\n"):
        if count + len(para) > size and current:
            chunks.append("\n\n".join(current))
            current, count = [], 0
        current.append(para)
        count += len(para)
    if current:
        chunks.append("\n\n".join(current))
    return chunks


# ── Ollama call with progress display ────────────────────────────────────────

def call_ollama(prompt: str, chunk_num: int, total_chunks: int, chunk_times: list) -> str:
    result: dict = {}
    error:  dict = {}

    def _run() -> None:
        try:
            result["response"] = ollama.chat(
                model=MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user",   "content": prompt},
                ],
                options={"num_ctx": 8192},
            )
        except Exception as exc:
            error["exc"] = exc

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()

    spinner   = itertools.cycle("⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏")
    start     = time.time()
    bar_width = 20

    while thread.is_alive():
        elapsed      = time.time() - start
        filled       = int(bar_width * (chunk_num - 1) / total_chunks)
        bar          = "█" * filled + "░" * (bar_width - filled)
        pct          = int(100 * (chunk_num - 1) / total_chunks)
        e_min, e_sec = divmod(int(elapsed), 60)

        if chunk_times:
            avg       = sum(chunk_times) / len(chunk_times)
            remaining = max(0, avg * (total_chunks - chunk_num + 1) - elapsed)
            r_min, r_sec = divmod(int(remaining), 60)
            eta = f"~{r_min:02d}:{r_sec:02d} remaining"
        else:
            eta = "estimating…"

        print(
            f"\r  Chunk {chunk_num}/{total_chunks} [{bar}] {pct:3d}%"
            f"  {next(spinner)} {e_min:02d}:{e_sec:02d} elapsed  {eta}   ",
            end="", flush=True,
        )
        time.sleep(0.1)

        if elapsed > CHUNK_TIMEOUT:
            raise TimeoutError(f"Chunk {chunk_num} exceeded {CHUNK_TIMEOUT}s timeout.")

    elapsed = time.time() - start
    chunk_times.append(elapsed)
    filled  = int(bar_width * chunk_num / total_chunks)
    bar     = "█" * filled + "░" * (bar_width - filled)
    pct     = int(100 * chunk_num / total_chunks)
    print(
        f"\r  Chunk {chunk_num}/{total_chunks} [{bar}] {pct:3d}%"
        f"  ✓ {int(elapsed)}s{' ' * 30}"
    )

    if "exc" in error:
        raise error["exc"]
    return result["response"].message.content


# ── File processor ────────────────────────────────────────────────────────────

def process_file(filepath: Path) -> None:
    log.info(f"┌ Processing: {filepath.name}")

    try:
        content = filepath.read_text(encoding="utf-8")
    except Exception as exc:
        log.error(f"  Cannot read file: {exc}")
        return

    if not content.strip():
        log.warning("  Empty file — skipping.")
        return

    chunks = chunk_text(content, CHUNK_CHARS)
    log.info(f"│ {len(content):,} chars → {len(chunks)} chunk(s) → {MODEL}")

    all_files:   list = []
    chunk_times: list = []

    for i, chunk in enumerate(chunks, 1):
        log.info(f"│ Chunk {i}/{len(chunks)} ({len(chunk):,} chars)…")
        prompt = (
            f"Transform this file into optimized Obsidian nodes.\n\n"
            f"Original filename: {filepath.stem} Part {i}.md\n\n"
            f"---\n\n{chunk}"
        )
        try:
            raw = call_ollama(prompt, i, len(chunks), chunk_times)
        except Exception as exc:
            log.error(f"  Error on chunk {i}: {exc}")
            return

        try:
            result   = extract_json(raw)
            strategy = result.get("strategy", "?")
            reason   = result.get("reason", "")
            all_files.extend(result["files"])
            log.info(f"│ Chunk {i} → {strategy}: {reason}")
        except (json.JSONDecodeError, KeyError) as exc:
            log.error(f"  Could not parse chunk {i}: {exc}")
            log.error(f"  Raw (first 500):\n{raw[:500]}")
            return

    READY_DIR.mkdir(exist_ok=True)
    written = []
    for fd in all_files:
        out_path = READY_DIR / fd["filename"]
        out_path.write_text(fd["content"], encoding="utf-8")
        written.append(fd["filename"])
        log.info(f"│   ✓ {fd['filename']}")

    PROCESSED_DIR.mkdir(exist_ok=True)
    done_path = PROCESSED_DIR / filepath.name
    if done_path.exists():
        stamp     = int(time.time() * 1000)
        done_path = PROCESSED_DIR / f"{filepath.stem}_{stamp}{filepath.suffix}"
    filepath.rename(done_path)

    log.info(f"└ Done → {len(written)} file(s) written to {READY_DIR}")


# ── File watcher ──────────────────────────────────────────────────────────────

class DropHandler(FileSystemEventHandler):
    def __init__(self) -> None:
        self._seen: set[str] = set()
        self._lock = threading.Lock()

    def _trigger(self, path: Path) -> None:
        if path.suffix.lower() != ".md" or path.name.startswith("."):
            return
        key = str(path)
        with self._lock:
            if key in self._seen:
                return
            self._seen.add(key)

        def run() -> None:
            try:
                time.sleep(0.8)
                if path.exists():
                    process_file(path)
            finally:
                with self._lock:
                    self._seen.discard(key)

        threading.Thread(target=run, daemon=True).start()

    def on_created(self, event) -> None:
        if not event.is_directory:
            self._trigger(Path(event.src_path))

    def on_moved(self, event) -> None:
        if not event.is_directory:
            self._trigger(Path(event.dest_path))


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    PROCESSED_DIR.mkdir(exist_ok=True)
    READY_DIR.mkdir(exist_ok=True)

    log.info("━" * 52)
    log.info("  NodeWeaver — Obsidian Graph Optimizer")
    log.info(f"  Model    : {MODEL} (Ollama)")
    log.info(f"  Drop zone: {WATCH_DIR}")
    log.info(f"  Output   : {READY_DIR}")
    log.info("  Drop .md files here. Press Ctrl+C to stop.")
    log.info("━" * 52)

    skip     = {"README.md"}
    existing = [f for f in WATCH_DIR.glob("*.md") if f.name not in skip]
    if existing:
        log.info(f"Found {len(existing)} existing file(s) — processing now…")
        for f in existing:
            process_file(f)

    handler  = DropHandler()
    observer = Observer()
    observer.schedule(handler, str(WATCH_DIR), recursive=False)
    observer.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass

    observer.stop()
    observer.join()
    log.info("NodeWeaver stopped.")


if __name__ == "__main__":
    main()
