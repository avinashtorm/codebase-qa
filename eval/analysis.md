# Retrieval failure analysis: vector vs BM25 vs hybrid

Dev split (35 questions), tree-sitter chunks, repo `fastapi/full-stack-fastapi-template` @ `7257e606`.
Hybrid = reciprocal rank fusion (k=60) of the top 50 from each retriever.

| Mode | Hit@1 | Hit@5 | Recall@10 | MRR |
|---|---|---|---|---|
| vector | 0.571 | 0.714 | 0.767 | 0.651 |
| bm25 | 0.171 | 0.514 | 0.610 | 0.327 |
| hybrid | 0.371 | 0.686 | 0.795 | 0.500 |

Hybrid finds more of the expected locations somewhere in the top 10 (Recall@10 +0.028) but pushes the right
chunk down from rank 1 much more often than it pulls it up (Hit@1 -0.200). Ranks below are the rank of the first
chunk overlapping an expected location (`-` = not in the top 10).

## Wins (hybrid ranks the answer higher than vector)

| Id | Question | vector | bm25 | hybrid | Why |
|---|---|---|---|---|---|
| c26 | How does the frontend react when the API responds with 401 or 403? | - | 1 | 3 | The literal tokens `401`/`403` appear in `main.tsx` (`[401, 403].includes(...)`). Embeddings blur numbers; BM25 matches them exactly. |
| c28 | How are API errors turned into toast notifications? | 6 | 1 | 2 | `toast` is an exact identifier hit in `useCustomToast.ts`; the vector model spread its top ranks over UI components that render toasts. |
| c31 | How does the reset password page get the token and submit the new password? | 7 | 3 | 3 | Identifier split (`new_password`, `resetPassword`, `token`) matches `reset-password.tsx` directly. |
| c04 | Where is the login endpoint that returns an access token defined? | 3 | 6 | 1 | Both retrievers rank `login_access_token` in their top 6; agreement lifts it to rank 1 under RRF, above the vector model's favourite (`test_token`). |
| c09 | Where is CORS configured for the backend? | 6 | 6 | 4 | `CORSMiddleware` is split into `cors`/`middleware`; both lists contain `main.py:27-33` at rank 6 and agreement moves it up. |

## Losses (hybrid ranks the answer lower than vector)

| Id | Question | vector | bm25 | hybrid | Why |
|---|---|---|---|---|---|
| c15 / c18 | Health check endpoint / public signup endpoint | 1 | 4 / 2 | 2 | BM25 ranks the generated API client (`frontend/src/client/sdk.gen.ts`, `types.gen.ts`) first: it repeats `healthCheck`, `registerUser`, `signup` many times in short chunks, so term frequency beats the real route. |
| c24 | How does listing items differ between superusers and normal users? | 1 | - | 10 | Question words (`superusers`, `normal`, `users`) are most frequent in test files and the admin page; the real code says `is_superuser` and `owner_id`. BM25 contributes only noise, and RRF lets that noise outvote the correct vector rank 1. |
| c39 | What happens when a normal user requests an item that belongs to someone else? | 1 | - | 5 | BM25 top 3 are all in `backend/tests/api/routes/test_items.py`: tests restate the scenario in their names (`test_read_item_not_enough_permissions`). |
| c30 | How is pagination implemented when listing users? | 1 | - | 10 | Vocabulary collision: `pagination` matches the shadcn `ui/pagination.tsx` component exactly, while the backend implements it with `skip`/`limit`/`offset`. |
| c43 | What happens when the JWT cannot be decoded? | 2 | - | 10 | `jwt`/`decode` also appear in `verify_password_reset_token` and generated client code; the expected `get_current_user` uses `InvalidTokenError`, which the question never mentions. |

## Takeaways

1. BM25 is valuable for exact tokens (status codes, identifiers, library names) that embeddings blur: 6 questions
   that vector missed at rank 1 are improved by fusion.
2. Unweighted RRF treats a weak retriever as an equal voter. When BM25 has no relevant result in its top 50, its
   noise still takes half of the fused ranking, which is the main source of Hit@1 loss.
3. Two noise sources dominate BM25 errors: generated code (`*.gen.ts`) and tests. Both repeat the query's terms
   without containing the implementation.
4. Next steps, each to be measured: a cross-encoder reranker over the fused top 30 (phase 7) to recover precision at
   rank 1 while keeping hybrid's recall; excluding generated files from the index; weighting vector above BM25 in RRF.

# Reranking (phase 7)

Cross-encoder `BAAI/bge-reranker-base` scores the top 30 first-stage candidates (header + code, max 512 tokens)
on CPU. "fusion" combines the reranker ranking with the first-stage ranking by RRF instead of replacing it.

| Config | Hit@1 | Hit@5 | Recall@10 | MRR | Mean retrieval latency |
|---|---|---|---|---|---|
| vector | 0.571 | 0.714 | 0.767 | 0.651 | 46 ms |
| hybrid | 0.371 | 0.686 | 0.795 | 0.500 | 54 ms |
| vector + rerank | 0.314 | 0.657 | 0.762 | 0.478 | 17.0 s (rerank 16.9 s) |
| hybrid + rerank | 0.314 | 0.657 | 0.748 | 0.471 | 16.6 s (rerank 16.4 s) |
| hybrid + rerank fusion | 0.400 | 0.743 | 0.838 | 0.544 | 18.6 s |

Why the reranker hurts here: it was trained on natural-language passage ranking, and on this repo it consistently
prefers prose and prose-like code over implementations. In the 14 questions where vector had the right answer at
rank 1 and the reranker did not, its new top 1 was a docs file (`deployment.md`, `backend/README.md`,
`development.md`) 4 times, a test whose name restates the question (`test_user.py`, `test_login.py`) 6 times, or
generated types twice. Example: c19 "How does the backend authenticate a user's email and password?" moves from
`crud.py:45-60` (`authenticate`) to `tests/crud/test_user.py:20-27` (`test_authenticate_user`, score 0.99).

Decision: the app defaults to tree-sitter + vector (best Hit@1 and MRR, ~50 ms). Reranking stays available as an
option (`RERANK=true`, `RERANK_FUSION=true`). Fusion has the best Recall@10 and Hit@5, which would matter if the
generator saw more context, but it costs ~18 s per question on CPU. A code-specific reranker or excluding tests and
docs from rerank candidates are the obvious follow-ups.
