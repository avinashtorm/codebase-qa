from sentence_transformers import SentenceTransformer

BGE_QUERY_INSTRUCTION = "Represent this sentence for searching relevant passages: "


class SentenceTransformerEmbedder:
    def __init__(self, model_name: str, batch_size: int = 32, device: str | None = None) -> None:
        self.model = SentenceTransformer(model_name, device=device)
        self.batch_size = batch_size
        self.query_instruction = BGE_QUERY_INSTRUCTION if "bge" in model_name.lower() else ""

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        vectors = self.model.encode(
            texts, batch_size=self.batch_size, normalize_embeddings=True, show_progress_bar=False
        )
        return [vector.tolist() for vector in vectors]

    def embed_query(self, text: str) -> list[float]:
        vector = self.model.encode(self.query_instruction + text, normalize_embeddings=True)
        return vector.tolist()
