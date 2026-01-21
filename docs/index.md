# Wobsongo Verify: Automated Claim Verification Framework

[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![DPG Candidate](https://img.shields.io/badge/DPG-Candidate-green)](https://digitalpublicgoods.net/)

## **THIS REPOSITORY IS A WORK IN PROGRESS AND NOT YET PRODUCTION READY.**

## **DO NOT RUN ANY COMMANDS YOU SEE LISTED ANYWHERE IN THIS REPOSITORY**

**Wobsongo Verify** is an open-source, RAG-based engine for automating the verification of claims against a trusted knowledge base.

Originally built to fight health misinformation in low-resource languages (SDG 3), this framework abstracts the logic of "Claim Extraction," "Evidence Retrieval," and "LLM Adjudication" so it can be applied to any domain with similar problem/solution.

## Features

- **Claim Extraction**: Automatically parses messy social media text (Tweets, Transcripts) into verifiable atomic claims.
- **Hybrid Retrieval Interface**: A standardized way to query Vector DBs using both Semantic Search and Keyword (BM25) matching.
- **The "Judge" Logic**: A tuned LLM feedback loop that determines if evidence _Supports_, _Refutes_, or is _Irrelevant_ to a claim, providing a confidence score.

## Quick Start

```bash
uv install wobsongo-verify
```

## Usage Example

```python
from wobsongo.core import Judge, SimpleRetriever
from wobsongo.prompts import load_prompt

# 1. Initialize your specific Knowledge Base (e.g., Weaviate/Pinecone)
retriever = SimpleRetriever(index_name="health_facts")

# 2. Initialize the Judge
judge = Judge(model="gpt-4o", retriever=retriever)

# 3. Verify a text
verdict = judge.check("Drinking hot lemon water cures cancer.")

print(verdict)
# Output:
# {
#   "status": "MISINFORMATION",
#   "confidence": 0.95,
#   "reasoning": "Multiple sources (WHO, CDC) state that while lemon water is healthy, it does not cure cancer.",
#   "evidence": ["doc_id_123", "doc_id_456"]
# }
```

## SDG Alignment

This project contributes to:

- **SDG 3 (Good Health & Well-being)**: By providing infrastructure to combat health misinformation.
- **SDG 16 (Peace, Justice, Strong Institutions)**: By enabling transparent fact-checking of public information.

## License

Distributed under the Apache 2.0 License. See `LICENSE` for more information.
