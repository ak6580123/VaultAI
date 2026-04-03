from dotenv import load_dotenv
load_dotenv()

import os
import faiss
import numpy as np
import pickle
import requests
import time
import threading
import sys

from tqdm import tqdm
from sentence_transformers import SentenceTransformer
import ollama

# ==========================
# CONFIG
# ==========================
NOTES_FOLDER = r"C:\Users\ASUS\Obsidian"
INDEX_FILE = "faiss_index.bin"
META_FILE = "metadata.pkl"

CHUNK_SIZE = 800
TOP_K = 5
USE_WEB = True

CURRENT_LLM_MODEL = "llama3"
CURRENT_EMBED_MODEL = "all-MiniLM-L6-v2"

TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")

print("\n[INIT] Tavily Key Detected:", bool(TAVILY_API_KEY))

# ==========================
# Spinner (thread-safe)
# ==========================
done_flag = threading.Event()

def spinner():
    while not done_flag.is_set():
        for c in "|/-\\":
            if done_flag.is_set():
                break
            sys.stdout.write(f'\r[LLM] Thinking... {c}')
            sys.stdout.flush()
            time.sleep(0.1)

# ==========================
# Load Embedding Model
# ==========================
def load_embedding_model(name):
    print(f"\n[MODEL] Loading embedding model: {name}...")
    start = time.time()
    model = SentenceTransformer(name, local_files_only=True)
    print(f"[MODEL] Loaded in {time.time() - start:.2f}s")
    return model

embed_model = load_embedding_model(CURRENT_EMBED_MODEL)

# ==========================
# Chunking
# ==========================
def chunk_text(text, size):
    return [text[i:i+size] for i in range(0, len(text), size)]

# ==========================
# Tavily Search
# ==========================
def tavily_search(query, max_results=3):
    if not TAVILY_API_KEY:
        return "[WEB] Disabled"

    print("[WEB] Searching...")

    try:
        url = "https://api.tavily.com/search"
        payload = {
            "api_key": TAVILY_API_KEY,
            "query": query,
            "search_depth": "advanced",
            "include_answer": True,
            "max_results": max_results
        }

        response = requests.post(url, json=payload, timeout=15)
        data = response.json()

        results_text = ""

        if "results" in data:
            for item in data["results"]:
                results_text += f"{item.get('title','')}\n"
                results_text += f"{item.get('content','')}\n"
                results_text += f"{item.get('url','')}\n\n"

        if "answer" in data:
            results_text += f"{data['answer']}\n\n"

        print("[WEB] Done.")
        return results_text if results_text else "No useful web results."

    except Exception as e:
        return f"[WEB ERROR] {str(e)}"

# ==========================
# Build or Load Index
# ==========================
def build_or_load_index():
    if os.path.exists(INDEX_FILE) and os.path.exists(META_FILE):
        print("\n[INDEX] Loading existing index...")
        index = faiss.read_index(INDEX_FILE)
        with open(META_FILE, "rb") as f:
            metadata = pickle.load(f)
        print("[INDEX] Loaded.")
        return index, metadata

    print("\n[STEP 1] Scanning markdown files...")

    documents = []
    metadata = []

    md_files = []
    for root, _, files in os.walk(NOTES_FOLDER):
        for file in files:
            if file.endswith(".md"):
                md_files.append(os.path.join(root, file))

    print(f"[INFO] Found {len(md_files)} files.")

    for path in tqdm(md_files, desc="Reading & Chunking"):
        try:
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()
                chunks = chunk_text(text, CHUNK_SIZE)

                for chunk in chunks:
                    documents.append(chunk)
                    metadata.append({
                        "path": path,
                        "text": chunk
                    })
        except:
            continue

    if not documents:
        print("[ERROR] No markdown files found.")
        exit()

    print(f"\n[STEP 2] Generating embeddings ({len(documents)} chunks)...")

    embeddings = embed_model.encode(
        documents,
        show_progress_bar=True,
        batch_size=32
    )

    embeddings = np.array(embeddings).astype("float32")

    print("\n[STEP 3] Building FAISS index...")
    index = faiss.IndexFlatL2(embeddings.shape[1])

    for i in tqdm(range(0, len(embeddings), 1000), desc="Indexing"):
        index.add(embeddings[i:i+1000])

    print("\n[STEP 4] Saving index...")
    faiss.write_index(index, INDEX_FILE)

    with open(META_FILE, "wb") as f:
        pickle.dump(metadata, f)

    print("[DONE] Index built.\n")

    return index, metadata

index, metadata = build_or_load_index()

# ==========================
# Folder Scope Detection
# ==========================
def detect_folder_scope(query):
    folders = set()

    for item in metadata:
        parts = item["path"].split("\\")
        for p in parts:
            folders.add(p.lower())

    for folder in folders:
        if folder in query.lower():
            return folder
    return None

# ==========================
# MAIN LOOP
# ==========================
while True:
    query = input("\nAsk (or 'exit'): ").strip()

    if query.lower() == "exit":
        break

    if not query:
        continue

    print("\n[QUERY] Processing...")

    folder_scope = detect_folder_scope(query)

    if folder_scope:
        print(f"[SCOPE] Folder → {folder_scope}")
        valid_indices = {
            i for i, item in enumerate(metadata)
            if folder_scope in item["path"].lower()
        }
    else:
        valid_indices = set(range(len(metadata)))

    print(f"[DEBUG] Valid indices count: {len(valid_indices)}")

    print("[QUERY] Encoding...")
    query_embedding = embed_model.encode([query]).astype("float32")

    print("[QUERY] Searching index...")
    distances, indices = index.search(query_embedding, TOP_K * 3)

    print("[QUERY] Filtering results...")
    vault_context = ""
    count = 0

    for idx in tqdm(indices[0], desc="Selecting Chunks"):
        if idx in valid_indices:
            vault_context += metadata[idx]["text"] + "\n\n"
            count += 1

            if count >= TOP_K:
                break

    web_context = tavily_search(query) if USE_WEB else ""

    combined_context = f"""
VAULT CONTEXT:
{vault_context}

WEB CONTEXT:
{web_context}
"""

    print(f"[LLM] Using model: {CURRENT_LLM_MODEL}")

    done_flag.clear()
    t = threading.Thread(target=spinner)
    t.start()

    response = ollama.chat(
        model=CURRENT_LLM_MODEL,
        messages=[
            {
                "role": "system",
                "content": "Combine vault and web context. If web contradicts vault, explain corrections."
            },
            {
                "role": "user",
                "content": f"{combined_context}\n\nQuestion: {query}"
            }
        ]
    )

    done_flag.set()
    t.join()

    print("\r[LLM] Done.            ")
    print("\n=== FINAL ANSWER ===\n")
    print(response["message"]["content"])
