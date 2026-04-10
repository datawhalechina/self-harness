# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Chinese tutorial project about **Context Engineering (上下文工程)** - a methodology for managing AI system context in the LLM era. The project includes:

1. **Documentation** (`docs/`): VitePress-based tutorial site explaining context engineering concepts
2. **miniMaster** (`code/miniMaster2.0/`): A minimal implementation of Claude Code Skills demonstrating ReAct agent architecture

## Commands

### Documentation Development

```bash
# Install dependencies
npm install

# Start dev server
npm run docs:dev

# Build for production
npm run docs:build

# Preview production build
npm run docs:preview
```

The docs deploy automatically to GitHub Pages via `.github/workflows/deploy.yml` on pushes to `main`.

### miniMaster Agent

```bash
cd code/miniMaster2.0

# Install Python dependencies
pip install -r requirements.txt

# Configure environment
cp .env .env.local  # Then edit .env.local with your API keys

# Run the agent interactively
python main_agent.py
```

Required environment variables in `code/miniMaster2.0/.env`:
- `MODEL_NAME`: LLM model (e.g., `deepseek-chat`)
- `BASE_URL`: API endpoint (e.g., `https://api.deepseek.com`)
- `API_KEY`: Your API key

## Architecture

### miniMaster Agent Structure

The miniMaster implements a **ReAct (Reasoning + Acting)** loop in `main_agent.py`:

1. **Agent Loop**: Thought → Action (Tool Call) → Observation → ... → Final Answer
2. **Tool System**: Modular tools in `tools/` directory with standardized `prompt_block()` and `run()` interfaces
3. **Skills System**: Domain-specific capabilities in `.claude/skills/` (docx, pdf, pptx, xlsx)

### Key Components

```
code/miniMaster2.0/
├── main_agent.py           # ReAct agent implementation
├── tools/
│   ├── base_tool/          # Core tools: bash, read, edit, write
│   ├── search_tool/        # Search tools: grep, glob
│   ├── memory_tool/        # Memory management tools
│   └── skills_tool/        # Skills invocation tools
├── utils/get_tools.py      # Tool registry for prompt generation
├── memory/                 # Short-term and long-term memory storage
└── .claude/skills/         # Skill definitions (docx, pdf, pptx, xlsx)
```

### Tool Interface

All tools implement:
- `name`: Tool identifier
- `description`: Human-readable description
- `prompt_block()`: Returns JSON schema for LLM prompting
- `run(tool_input: dict) -> dict`: Executes tool, returns `{"success": bool, ...}`

### Skills System

Skills are domain-specific capabilities stored in `.claude/skills/<name>/`:
- `SKILL.md`: Documentation and usage guidelines
- `scripts/`: Helper scripts for the skill
- Loaded dynamically via `utils/get_tools.py:get_skills_tools()`

Current skills: `docx`, `pdf`, `pptx`, `xlsx`, `frontend-design`

### LLM Integration

The agent calls LLM APIs (OpenAI-compatible) with:
- Configurable `MODEL_NAME`, `BASE_URL`, `API_KEY` via environment
- Response parsed for `<think>`, `<tool>`, `<parameter>` XML tags
- Iterative execution up to `max_iterations` (default: 10)

## Working with the Codebase

### Adding a New Tool

1. Create tool class in appropriate `tools/<category>/` subdirectory
2. Implement `name`, `description`, `prompt_block()`, and `run()` methods
3. Export from `tools/<category>/__init__.py`
4. Tool automatically appears in agent's available tools

### Adding a New Skill

1. Create `.claude/skills/<skillname>/` directory
2. Add `SKILL.md` with frontmatter (`name`, `description`)
3. Add helper scripts in `scripts/` subdirectory
4. Skill automatically loaded by `get_skills_tools()`

### Documentation Structure

Docs use VitePress with configuration in `docs/.vitepress/config.mts`:
- Chinese language (`zh-CN`)
- Auto-deploys to GitHub Pages
- Math rendering enabled (`markdown.math: true`)
- Sidebar navigation in config defines chapter structure
