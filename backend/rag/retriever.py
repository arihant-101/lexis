"""
RAG pipeline for Lexis.

Corpus: GRE word list (~3500 words) + reading passages.
Vector store: ChromaDB (local, no infra needed).

Retrieval strategy:
  - Words: semantic search + filter by difficulty + rerank by mastery score
  - Passages: filter by difficulty/topic + semantic match to user's weak areas
"""

import chromadb
from chromadb.utils import embedding_functions
from typing import Optional
import json
import os

CHROMA_PATH = os.environ.get("CHROMA_PATH", "./chroma_db")


class _Retriever:
    """
    Lazy-loaded wrapper around ChromaDB collections.
    Use as:  retriever.gre_words.query(...)
             retriever.gre_passages.get(...)
    """

    def __init__(self):
        self._client = None
        self._gre_words = None
        self._gre_passages = None

    def _init(self):
        if self._client is None:
            self._client = chromadb.PersistentClient(path=CHROMA_PATH)
            ef = embedding_functions.DefaultEmbeddingFunction()
            self._gre_words = self._client.get_or_create_collection(
                "gre_words",
                embedding_function=ef,
                metadata={"hnsw:space": "cosine"}
            )
            self._gre_passages = self._client.get_or_create_collection(
                "gre_passages",
                embedding_function=ef,
                metadata={"hnsw:space": "cosine"}
            )

    @property
    def gre_words(self):
        self._init()
        return self._gre_words

    @property
    def gre_passages(self):
        self._init()
        return self._gre_passages


# Module-level singleton — import this in nodes/agent code
retriever = _Retriever()


# ── Ingestion ──────────────────────────────────────────────────────────────

def ingest_word_list(word_list_path: str):
    """
    Ingest GRE word list into ChromaDB.
    JSON format: [{word, definition, pos, examples, synonyms, difficulty (1-5)}]
    """
    col = retriever.gre_words

    with open(word_list_path) as f:
        words = json.load(f)

    documents, metadatas, ids = [], [], []
    for w in words:
        doc = (
            f"{w['word']}: {w['definition']}. "
            f"Example: {w['examples'][0] if w.get('examples') else ''}. "
            f"Synonyms: {', '.join(w.get('synonyms', [])[:3])}"
        )
        documents.append(doc)
        metadatas.append({
            "word": w["word"],
            "difficulty": int(w.get("difficulty", 3)),       # stored as int for $lte filters
            "pos": w.get("pos", ""),
            "semantic_cluster": w.get("semantic_cluster", "general")
        })
        ids.append(f"word_{w['word']}")

    batch_size = 100
    for i in range(0, len(documents), batch_size):
        col.upsert(
            documents=documents[i:i+batch_size],
            metadatas=metadatas[i:i+batch_size],
            ids=ids[i:i+batch_size]
        )

    print(f"Ingested {len(words)} words into ChromaDB")


def ingest_passage_list(passage_list_path: str):
    """
    Ingest GRE reading passages into ChromaDB.
    JSON format: [{id, title, text, difficulty (1-5), topic, gre_words}]
    """
    col = retriever.gre_passages

    with open(passage_list_path) as f:
        passages = json.load(f)

    documents, metadatas, ids = [], [], []
    for p in passages:
        documents.append(p["text"])
        metadatas.append({
            "title": p.get("title", ""),
            "difficulty": int(p.get("difficulty", 3)),
            "topic": p.get("topic", "general"),
            "gre_words": json.dumps(p.get("gre_words", [])),
        })
        ids.append(p["id"])

    col.upsert(documents=documents, metadatas=metadatas, ids=ids)
    print(f"Ingested {len(passages)} passages into ChromaDB")


# ── Retrieval ──────────────────────────────────────────────────────────────

def retrieve_words_for_quiz(
    user_id: str,
    n: int = 5,
    difficulty: Optional[int] = None,
    semantic_cluster: Optional[str] = None,
    mastery_scores: Optional[dict] = None
) -> list[dict]:
    """
    Retrieve words for a quiz session, excluding mastered words (level 4).
    Sorted by ascending mastery (lowest mastery = highest priority).
    """
    col = retriever.gre_words

    where = {}
    if difficulty:
        where["difficulty"] = {"$lte": difficulty}
    if semantic_cluster:
        where["semantic_cluster"] = semantic_cluster

    results = col.get(
        where=where if where else None,
        include=["metadatas", "documents"]
    )

    words = []
    for doc, meta in zip(results["documents"], results["metadatas"]):
        word = meta["word"]
        mastery = (mastery_scores or {}).get(word, 0)
        if mastery >= 4:
            continue
        words.append({
            "word": word,
            "document": doc,
            "mastery": mastery,
            "difficulty": int(meta.get("difficulty", 3)),
            "cluster": meta.get("semantic_cluster", "general")
        })

    words.sort(key=lambda w: (w["mastery"], -w["difficulty"]))
    return words[:n]


def retrieve_semantically_similar(query: str, n: int = 5, exclude_words: list = None) -> list[dict]:
    """Semantic search over word corpus."""
    col = retriever.gre_words
    exclude = set(exclude_words or [])

    results = col.query(
        query_texts=[query],
        n_results=n + len(exclude),
        include=["metadatas", "documents", "distances"]
    )

    words = []
    for doc, meta, dist in zip(
        results["documents"][0],
        results["metadatas"][0],
        results["distances"][0]
    ):
        if meta["word"] not in exclude:
            words.append({
                "word": meta["word"],
                "document": doc,
                "relevance_score": round(1 - dist, 3),
                "difficulty": int(meta.get("difficulty", 3))
            })

    return words[:n]


def retrieve_passage(
    difficulty: int = 3,
    topic: Optional[str] = None,
    exclude_ids: list = None
) -> dict:
    """Retrieve a reading passage. difficulty is an int 1-5."""
    col = retriever.gre_passages
    exclude = set(exclude_ids or [])

    where: dict = {"difficulty": {"$lte": difficulty}}
    if topic:
        where["topic"] = topic

    results = col.get(where=where, include=["metadatas", "documents"])

    for doc, meta, pid in zip(
        results.get("documents", []),
        results.get("metadatas", []),
        results.get("ids", []),
    ):
        if pid in exclude:
            continue
        return {
            "passage_id": pid,
            "text": doc,
            "difficulty": meta.get("difficulty", difficulty),
            "topic": meta.get("topic", "general"),
            "questions": [],
        }

    return {
        "passage_id": "",
        "text": "No matching reading passage found.",
        "difficulty": difficulty,
        "topic": topic or "general",
        "questions": [],
    }


def get_word_from_corpus(word: str) -> dict:
    """Return word data from the local seed corpus when the dictionary API misses."""
    data_path = os.path.join(os.path.dirname(__file__), "data", "gre_words.json")
    with open(data_path) as f:
        words = json.load(f)

    for item in words:
        if item.get("word", "").lower() == word.lower():
            return {
                "word": item.get("word", word),
                "definition": item.get("definition", ""),
                "part_of_speech": item.get("pos", ""),
                "example_sentences": item.get("examples", []),
                "synonyms": item.get("synonyms", []),
                "antonyms": item.get("antonyms", []),
                "etymology": item.get("etymology"),
            }

    return {
        "word": word,
        "definition": "Definition not found in local corpus.",
        "part_of_speech": "",
        "example_sentences": [],
        "synonyms": [],
        "antonyms": [],
        "etymology": None,
    }