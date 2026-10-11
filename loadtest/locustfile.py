import itertools
import json
import random
from pathlib import Path

from locust import HttpUser, between, task

USERS = itertools.count()
REPO_ID = "fastapi__full-stack-fastapi-template"
QUESTIONS = [
    json.loads(line)["question"]
    for line in (Path(__file__).resolve().parents[1] / "eval" / "questions.jsonl").read_text("utf-8").splitlines()
    if line.strip() and not json.loads(line).get("held_out")
]


class Visitor(HttpUser):
    wait_time = between(0.0, 0.1)

    def on_start(self) -> None:
        self.client.headers["X-Visitor-Id"] = f"{next(USERS) % 64:032x}"

    @task
    def ask(self) -> None:
        question = random.choice(QUESTIONS)
        self.client.post("/ask", json={"repo_id": REPO_ID, "question": question}, name="/ask")
