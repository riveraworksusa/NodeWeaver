#!/usr/bin/env python3
"""
NodeWeaver — AI-powered Obsidian graph optimizer.
Drop any .md file into this folder. NodeWeaver transforms it
into a connected network of nodes optimized for Obsidian graph view.
"""

import os
import sys
import json
import time
import logging
import threading
from pathlib import Path

import anthropic
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# ── Config ────────────────────────────────────────────────────────────────────
WATCH_DIR     = Path(__file__).parent          # drop zone — watched for incoming .md files
PROCESSED_DIR = WATCH_DIR / "PROCESSED"       # originals move here after processing
READY_DIR     = WATCH_DIR / "READY"           # output nodes land here (not watched → no loop)
MODEL         = "claude-sonnet-4-6"
MAX_TOKENS    = 16000

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("NodeWeaver")

# ── System prompt (cached) ────────────────────────────────────────────────────
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


def extract_json(raw: str) -> dict:
    """Pull JSON from Claude's response, handling markdown code fences."""
    text = raw.strip()
    if "```json" in text:
        text = text.split("```json", 1)[1].split("```", 1)[0].strip()
    elif "```" in text:
        text = text.split("```", 1)[1].split("```", 1)[0].strip()
    return json.loads(text)


def process_file(filepath: Path, client: anthropic.Anthropic) -> None:
    """Send a .md file through Claude and write the optimized output."""
    log.info(f"┌ Processing: {filepath.name}")

    try:
        content = filepath.read_text(encoding="utf-8")
    except Exception as exc:
        log.error(f"  Cannot read file: {exc}")
        return

    if not content.strip():
        log.warning("  Empty file — skipping.")
        return

    log.info(f"│ Sending {len(content):,} chars to Claude…")

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=[
                {
                    "type": "text",
                    "text": SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},   # cache the system prompt
                }
            ],
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Transform this file into optimized Obsidian nodes.\n\n"
                        f"Original filename: {filepath.name}\n\n"
                        f"---\n\n{content}"
                    ),
                }
            ],
        )
    except anthropic.APIError as exc:
        log.error(f"  API error: {exc}")
        return

    # Extract text (skip any thinking blocks)
    raw = ""
    for block in response.content:
        if block.type == "text":
            raw = block.text
            break

    try:
        result = extract_json(raw)
        files  = result["files"]
        strategy = result.get("strategy", "?")
        reason   = result.get("reason", "")
    except (json.JSONDecodeError, KeyError) as exc:
        log.error(f"  Could not parse response: {exc}")
        log.debug(f"  Raw response (first 500): {raw[:500]}")
        return

    log.info(f"│ Strategy: {strategy} — {reason}")

    # Write output files into READY/ (not watched — prevents infinite loop)
    READY_DIR.mkdir(exist_ok=True)
    written = []
    for fd in files:
        out_path = READY_DIR / fd["filename"]
        out_path.write_text(fd["content"], encoding="utf-8")
        written.append(fd["filename"])
        log.info(f"│   ✓ {fd['filename']}")

    # Move original into PROCESSED/ — handle name collision with a timestamp suffix
    PROCESSED_DIR.mkdir(exist_ok=True)
    done_path = PROCESSED_DIR / filepath.name
    if done_path.exists():
        stamp = time.strftime("%H%M%S")
        done_path = PROCESSED_DIR / f"{filepath.stem}_{stamp}{filepath.suffix}"
    filepath.rename(done_path)

    # Log cache savings
    usage = response.usage
    cached = getattr(usage, "cache_read_input_tokens", 0) or 0
    if cached:
        log.info(f"│ Cache hit: {cached:,} tokens saved")

    log.info(f"└ Done → {len(written)} file(s) in READY/. Original moved to PROCESSED/")
    log.info(f"  Pick up your files from NODEWEAVER/READY/ and move them home.")


# ── File watcher ──────────────────────────────────────────────────────────────

class DropHandler(FileSystemEventHandler):
    def __init__(self, client: anthropic.Anthropic):
        self._client = client
        self._seen: set[str] = set()
        self._lock  = threading.Lock()          # Bug 2 fix: protect shared set

    def _trigger(self, path: Path):
        if path.suffix.lower() != ".md":
            return
        if path.name.startswith("."):
            return
        key = str(path)
        with self._lock:
            if key in self._seen:
                return
            self._seen.add(key)

        # Bug 3 fix: run in a thread so the watcher is never blocked
        def run():
            try:
                time.sleep(0.8)      # wait for file to finish writing
                if path.exists():
                    process_file(path, self._client)
            finally:
                with self._lock:
                    self._seen.discard(key)

        threading.Thread(target=run, daemon=True).start()

    def on_created(self, event):
        if not event.is_directory:
            self._trigger(Path(event.src_path))

    def on_moved(self, event):
        if not event.is_directory:
            self._trigger(Path(event.dest_path))


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        sys.exit("ERROR: ANTHROPIC_API_KEY environment variable is not set.")

    client = anthropic.Anthropic(api_key=api_key)

    PROCESSED_DIR.mkdir(exist_ok=True)
    READY_DIR.mkdir(exist_ok=True)

    log.info("━" * 52)
    log.info("  NodeWeaver — Obsidian Graph Optimizer")
    log.info(f"  Model    : {MODEL}")
    log.info(f"  Drop zone: {WATCH_DIR}")
    log.info(f"  Output   : {READY_DIR}")
    log.info("  Drop .md files here. Press Ctrl+C to stop.")
    log.info("━" * 52)

    # Process any .md files already in the drop zone (skip README and output files)
    skip = {"README.md"}
    existing = [f for f in WATCH_DIR.glob("*.md") if f.name not in skip]
    if existing:
        log.info(f"Found {len(existing)} existing file(s) — processing now…")
        for f in existing:
            process_file(f, client)

    handler  = DropHandler(client)
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
