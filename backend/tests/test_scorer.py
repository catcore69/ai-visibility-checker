"""
Тесты калькулятора AI Visibility Score.
"""
import pytest

from app.core.scorer import (
    calculate_visibility_score,
    calculate_share_of_voice,
    calculate_presence_rate,
    get_model_breakdown,
    get_weak_models,
    get_strong_models,
    compare_with_competitors,
)
from app.core.analyzer import Analysis, MentionResult


# ──────────────────────────────────────────────────────────────
# Вспомогательные фикстуры
# ──────────────────────────────────────────────────────────────
def make_analysis(
    brand_name: str = "TestBrand",
    mentions: list[dict] | None = None,
    total_responses: int = 10,
) -> Analysis:
    if mentions is None:
        mentions = []

    results = [
        MentionResult(
            model_name=m.get("model", "chatgpt"),
            prompt=m.get("prompt", "Тест"),
            brand_mentioned=m.get("mentioned", True),
            position=m.get("position"),
            sentiment=m.get("sentiment", "neutral"),
            competitors_mentioned=m.get("competitors", []),
        )
        for m in mentions
    ]

    models_with = {r.model_name for r in results if r.brand_mentioned}

    return Analysis(
        brand_name=brand_name,
        mention_results=results,
        total_responses=total_responses,
        brand_mention_count=sum(1 for r in results if r.brand_mentioned),
        models_with_mentions=models_with,
    )


# ──────────────────────────────────────────────────────────────
# Presence Rate
# ──────────────────────────────────────────────────────────────
def test_presence_rate_full():
    """100% упоминаний → presence rate = 100."""
    analysis = make_analysis(
        mentions=[{"mentioned": True} for _ in range(10)],
        total_responses=10,
    )
    rate = calculate_presence_rate(analysis)
    assert rate == 100


def test_presence_rate_half():
    analysis = make_analysis(
        mentions=(
            [{"mentioned": True}] * 5 +
            [{"mentioned": False}] * 5
        ),
        total_responses=10,
    )
    rate = calculate_presence_rate(analysis)
    assert rate == 50


def test_presence_rate_zero():
    analysis = make_analysis(
        mentions=[{"mentioned": False} for _ in range(5)],
        total_responses=5,
    )
    rate = calculate_presence_rate(analysis)
    assert rate == 0


def test_presence_rate_empty():
    analysis = make_analysis(mentions=[], total_responses=0)
    rate = calculate_presence_rate(analysis)
    assert rate == 0


# ──────────────────────────────────────────────────────────────
# AI Visibility Score
# ──────────────────────────────────────────────────────────────
def test_score_range():
    """Score всегда в диапазоне 0–100."""
    for total in [5, 10, 20]:
        for mentioned in range(0, total + 1, 2):
            analysis = make_analysis(
                mentions=(
                    [{"mentioned": True, "sentiment": "positive", "position": 1}] * mentioned +
                    [{"mentioned": False}] * (total - mentioned)
                ),
                total_responses=total,
            )
            score = calculate_visibility_score(analysis, models_total=7)
            assert 0 <= score <= 100, f"Score {score} вне диапазона при {mentioned}/{total}"


def test_score_perfect():
    """Все упоминания позитивны, первая позиция → максимальный score."""
    analysis = make_analysis(
        mentions=[
            {"mentioned": True, "sentiment": "positive", "position": 1, "model": f"model_{i}"}
            for i in range(7)
        ] * 3,
        total_responses=21,
    )
    score = calculate_visibility_score(analysis, models_total=7)
    assert score >= 90, f"Ожидался score ≥90, получен {score}"


def test_score_zero():
    """Ни одного упоминания → score = 0."""
    analysis = make_analysis(mentions=[], total_responses=10)
    score = calculate_visibility_score(analysis, models_total=7)
    assert score == 0


def test_score_formula_components():
    """Проверяем что компоненты формулы учитываются корректно."""
    # Половина упоминаний (presence=50%), 3/7 моделей, позиция #2, нейтрально
    analysis = make_analysis(
        mentions=(
            [{"mentioned": True, "sentiment": "neutral", "position": 2, "model": "chatgpt"}] * 5 +
            [{"mentioned": True, "sentiment": "neutral", "position": 2, "model": "yandex"}]  * 3 +
            [{"mentioned": True, "sentiment": "neutral", "position": 2, "model": "gemini"}]  * 2 +
            [{"mentioned": False}] * 10
        ),
        total_responses=20,
    )
    score = calculate_visibility_score(analysis, models_total=7)
    # Не нули, но и не максимум
    assert 10 < score < 70


# ──────────────────────────────────────────────────────────────
# Share of Voice
# ──────────────────────────────────────────────────────────────
def test_share_of_voice():
    brand_mentions     = 10
    total_all_mentions = 40  # brand + конкуренты
    sov = calculate_share_of_voice(brand_mentions, total_all_mentions)
    assert sov == 25.0


def test_share_of_voice_zero_total():
    sov = calculate_share_of_voice(0, 0)
    assert sov == 0


def test_share_of_voice_100_percent():
    sov = calculate_share_of_voice(10, 10)
    assert sov == 100.0


# ──────────────────────────────────────────────────────────────
# Model breakdown
# ──────────────────────────────────────────────────────────────
def test_model_breakdown_structure():
    analysis = make_analysis(
        mentions=[
            {"model": "chatgpt", "mentioned": True,  "sentiment": "positive", "position": 1},
            {"model": "chatgpt", "mentioned": True,  "sentiment": "positive", "position": 2},
            {"model": "yandex",  "mentioned": False},
            {"model": "gemini",  "mentioned": True,  "sentiment": "negative", "position": 3},
        ],
        total_responses=6,
    )
    breakdown = get_model_breakdown(analysis, prompts_per_model={"chatgpt": 2, "yandex": 2, "gemini": 2})

    chatgpt_data = next((m for m in breakdown if m["model_name"] == "chatgpt"), None)
    assert chatgpt_data is not None
    assert chatgpt_data["mentions"] == 2
    assert chatgpt_data["presence_rate"] == 100

    yandex_data = next((m for m in breakdown if m["model_name"] == "yandex"), None)
    assert yandex_data is not None
    assert yandex_data["mentions"] == 0
    assert yandex_data["presence_rate"] == 0


# ──────────────────────────────────────────────────────────────
# Weak / Strong models
# ──────────────────────────────────────────────────────────────
def test_weak_strong_models():
    breakdown = [
        {"model_name": "chatgpt",  "presence_rate": 80},
        {"model_name": "yandex",   "presence_rate": 10},
        {"model_name": "gemini",   "presence_rate": 60},
        {"model_name": "gigachat", "presence_rate": 0},
    ]
    weak   = get_weak_models(breakdown, threshold=30)
    strong = get_strong_models(breakdown, threshold=50)

    assert set(weak)   == {"yandex", "gigachat"}
    assert set(strong) == {"chatgpt", "gemini"}


# ──────────────────────────────────────────────────────────────
# compare_with_competitors
# ──────────────────────────────────────────────────────────────
def test_compare_with_competitors_rank():
    competitor_analyses = {
        "CompetitorA": make_analysis(
            brand_name="CompetitorA",
            mentions=[{"mentioned": True} for _ in range(10)],
            total_responses=10,
        ),
        "CompetitorB": make_analysis(
            brand_name="CompetitorB",
            mentions=[{"mentioned": True} for _ in range(3)],
            total_responses=10,
        ),
    }
    client_analysis = make_analysis(
        brand_name="TestBrand",
        mentions=[{"mentioned": True} for _ in range(5)],
        total_responses=10,
    )

    result = compare_with_competitors(
        client_analysis=client_analysis,
        competitor_analyses=competitor_analyses,
        models_total=7,
    )

    names  = [r["name"] for r in result]
    assert "TestBrand"   in names
    assert "CompetitorA" in names
    assert "CompetitorB" in names

    # Клиент помечен is_client=True
    client_row = next(r for r in result if r["name"] == "TestBrand")
    assert client_row["is_client"] is True
