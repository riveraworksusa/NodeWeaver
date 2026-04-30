# NodeWeaver 🕸️
> AI-powered Obsidian graph optimizer. Drop a Markdown file in. Get a fully connected knowledge graph out.

NodeWeaver watches a folder. When you drop any `.md` file in, it sends the content to Claude AI, which intelligently restructures it into interconnected Obsidian nodes — complete with YAML frontmatter, tags, wikilinks, and navigation — ready for Obsidian's graph view.

---

## What It Does

**Before NodeWeaver** — a flat Markdown file with sections:
```
my-notes.md  (one big file, invisible in graph view)
```

**After NodeWeaver** — a connected node network:
```
READY/
├── My Notes.md              ← hub (center of the graph)
├── Chapter 1 — Origin.md   ← node (linked to hub + siblings)
├── Chapter 2 — Build.md    ← node
└── Chapter 3 — The Cave.md ← node
```

Every node links back to the hub. Every node links to its siblings. Obsidian's graph view shows the full web automatically.

---

## Requirements

- Python 3.8+
- An [Anthropic API key](https://platform.anthropic.com) (you pay for your own usage — typically $0.01–$0.05 per file)

---

## Setup

**1. Clone the repo**
```bash
git clone https://github.com/yourusername/nodeweaver.git
cd nodeweaver
```

**2. Run the setup script**
```bash
bash setup.sh
```

Or manually:
```bash
pip install -r requirements.txt
```

**3. Set your API key**
```bash
export ANTHROPIC_API_KEY="your-key-here"
```

To make it permanent (Linux/Mac):
```bash
echo 'export ANTHROPIC_API_KEY="your-key-here"' >> ~/.bashrc && source ~/.bashrc
```

---

## Usage

**Start NodeWeaver:**
```bash
python3 nodeweaver.py
```

**Drop any `.md` file into the `NODEWEAVER/` folder.**

NodeWeaver will:
1. Detect the file automatically
2. Send it to Claude for analysis
3. Write optimized node files to `NODEWEAVER/READY/`
4. Move your original to `NODEWEAVER/PROCESSED/`

**Move the output files** from `READY/` to wherever they live in your Obsidian vault.

---

## Folder Structure

```
NODEWEAVER/
├── nodeweaver.py       ← the script
├── requirements.txt    ← dependencies
├── setup.sh            ← quick setup
├── READY/              ← output lands here (auto-created)
└── PROCESSED/          ← originals move here (auto-created)
```

---

## How Claude Decides the Structure

| Input | Output |
|-------|--------|
| Single focused concept (< 3 major sections) | One enhanced node with frontmatter + tags |
| Multi-section file (3+ major sections) | Hub node + individual nodes, all wired together |

Every output file gets:
- YAML frontmatter with relevant tags
- H1 title
- `[[Wikilinks]]` to connected files
- Hub / Prev / Next / Related navigation

---

## Cost

Uses `claude-sonnet-4-6`. A typical file costs **$0.01–$0.05** to process.
You use your own API key — no shared cost, no subscription.
Prompt caching is enabled so repeated runs cost significantly less.

---

## License

MIT — use it, fork it, build on it.
