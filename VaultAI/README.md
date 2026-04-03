# VaultAI

Obsidian-aware RAG assistant.

## External requirements

| App      | Required | Link                        | Purpose             |
|----------|----------|-----------------------------|---------------------|
| Ollama   | Yes      | https://ollama.com/download | Local LLM server    |
| Obsidian | Optional | https://obsidian.md         | Vault note indexing |

After installing Ollama:

    ollama pull llama3

## Quick start

    pip install -e .
    vaultai

## Build installer

    pip install pyinstaller build
    python build_installer.py