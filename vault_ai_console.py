import os
import faiss
import numpy as np
import pickle
import json
import shutil
import pyperclip
import sys
from datetime import datetime

from sentence_transformers import SentenceTransformer
import ollama

# MULTILINE INPUT
from prompt_toolkit import PromptSession
from prompt_toolkit.key_binding import KeyBindings

sys.stdout.reconfigure(encoding='utf-8')

# ==========================
# CONFIG
# ==========================
NOTES_FOLDER = r"C:\Users\ASUS\Obsidian"
INDEX_FILE = "faiss_index.bin"
META_FILE = "metadata.pkl"
LOG_FILE = "chat_logs.json"

CHUNK_SIZE = 800
TOP_K = 5

MODEL = "llama3"
EMBED_MODEL = "all-MiniLM-L6-v2"

MAX_TOKENS = 2000

# ==========================
# MULTILINE INPUT
# ==========================
kb = KeyBindings()

@kb.add("enter")
def _(event):
    buf = event.app.current_buffer
    if buf.text.strip():
        event.app.exit(result=buf.text)
    else:
        buf.insert_text("\n")

@kb.add("c-j")
def _(event):
    event.current_buffer.insert_text("\n")

session = PromptSession(key_bindings=kb, multiline=True)

# ==========================
# UTILS
# ==========================
def clear():
    os.system("cls" if os.name == "nt" else "clear")

def term_height():
    try:
        return shutil.get_terminal_size().lines
    except:
        return 30

# ==========================
# LOGGING
# ==========================
def append_log(q, a):
    logs = []
    if os.path.exists(LOG_FILE):
        logs = json.load(open(LOG_FILE, "r", encoding="utf-8"))

    logs.append({
        "timestamp": datetime.now().isoformat(),
        "query": q,
        "answer": a
    })

    json.dump(logs, open(LOG_FILE, "w", encoding="utf-8"), indent=2)

# ==========================
# CHUNKING
# ==========================
def chunk_text(text, size):
    return [text[i:i+size] for i in range(0, len(text), size)]

# ==========================
# INDEX
# ==========================
embed_model = SentenceTransformer(EMBED_MODEL)

def build_or_load():
    if os.path.exists(INDEX_FILE) and os.path.exists(META_FILE):
        return faiss.read_index(INDEX_FILE), pickle.load(open(META_FILE, "rb"))

    docs, meta = [], []

    for root, _, files in os.walk(NOTES_FOLDER):
        for f in files:
            if f.endswith(".md"):
                path = os.path.join(root, f)
                try:
                    text = open(path, encoding="utf-8").read()
                    for c in chunk_text(text, CHUNK_SIZE):
                        docs.append(c)
                        meta.append({"text": c, "path": path})
                except:
                    pass

    emb = embed_model.encode(docs).astype("float32")
    idx = faiss.IndexFlatL2(emb.shape[1])
    idx.add(emb)

    faiss.write_index(idx, INDEX_FILE)
    pickle.dump(meta, open(META_FILE, "wb"))

    return idx, meta

index, metadata = build_or_load()

# ==========================
# RETRIEVE
# ==========================
def retrieve(query):
    q = embed_model.encode([query]).astype("float32")
    _, ids = index.search(q, TOP_K)
    return "\n\n".join(metadata[i]["text"] for i in ids[0])

# ==========================
# SMART TOPIC SPLITTING
# ==========================
def split_topics(query):
    lines = query.split("\n")
    topics = []

    for line in lines:
        line = line.strip("-• ")
        if line:
            topics.append(line)

    return topics if len(topics) > 1 else [query]

# ==========================
# STRUCTURED PROMPT
# ==========================
def build_prompt(context, topic):
    return [
        {
            "role": "system",
            "content": """You MUST answer fully.

For the given topic, provide:
1. Explanation
2. Step-by-step Algorithm
3. Pseudocode
4. C code

Do NOT skip anything.
Do NOT stop early.
"""
        },
        {
            "role": "user",
            "content": f"{context}\n\nTopic:\n{topic}"
        }
    ]

# ==========================
# STREAMING
# ==========================
def stream_generate(messages):
    stream = ollama.chat(
        model=MODEL,
        messages=messages,
        stream=True,
        options={"num_predict": MAX_TOKENS}
    )

    full = ""
    for chunk in stream:
        text = chunk["message"]["content"]
        print(text, end="", flush=True)
        full += text

    print()
    return full

# ==========================
# AUTO CONTINUE
# ==========================
def ensure_complete(answer):
    required = ["Pseudocode", "C code"]

    if not all(r.lower() in answer.lower() for r in required):
        print("\n[Auto-continue triggered]\n")

        follow = ollama.chat(
            model=MODEL,
            messages=[{
                "role": "user",
                "content": "Continue and COMPLETE missing sections (pseudocode and C code)."
            }],
            options={"num_predict": 1500}
        )

        answer += "\n" + follow["message"]["content"]

    return answer

# ==========================
# PAGINATION
# ==========================
def paginate(text):
    h = term_height() - 4
    lines = text.split("\n")

    for i in range(0, len(lines), h):
        clear()
        print("\n".join(lines[i:i+h]))
        if i + h < len(lines):
            input("\n--- Press Enter ---")

# ==========================
# MAIN LOOP
# ==========================
while True:
    clear()
    print("=== VAULT AI (SMART MODE) ===")
    print("Ctrl+J = newline | Enter = submit | exit = quit\n")

    try:
        query = session.prompt("> ")
    except KeyboardInterrupt:
        continue

    if query.strip().lower() == "exit":
        break

    if not query.strip():
        query = pyperclip.paste().strip()
        if not query:
            continue

    topics = split_topics(query)

    final_answer = ""

    for t in topics:
        print(f"\n=== {t.strip()} ===\n")

        context = retrieve(t)
        messages = build_prompt(context, t)

        ans = stream_generate(messages)
        ans = ensure_complete(ans)

        final_answer += f"\n\n=== {t} ===\n{ans}"

    append_log(query, final_answer)

    print("\n--- View Mode ---")
    print("1 = Scroll")
    print("2 = Raw")

    if input("> ").strip() == "1":
        paginate(final_answer)
    else:
        print(final_answer)

    input("\nPress Enter...")