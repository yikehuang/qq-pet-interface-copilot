from fastapi import FastAPI

from .risk_engine import evaluate_risk
from .schemas import EvaluationRequest, EvaluationResult

app = FastAPI(
    title="Location Security Lab",
    version="0.1.0",
    description="Authorized multi-signal location-integrity research service.",
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/v1/evaluate", response_model=EvaluationResult)
def evaluate(payload: EvaluationRequest) -> EvaluationResult:
    return evaluate_risk(payload)
