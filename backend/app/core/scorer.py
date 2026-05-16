from app.core.analyzer import Analysis


def calculate_visibility_score(analysis: Analysis, brand_name: str) -> int:
    """
    AI Visibility Score 0-100.

    Компоненты:
    - Presence Rate (50%): доля промптов, где бренд упомянут хотя бы одной моделью
    - Model Coverage (20%): в скольких из 6 моделей бренд встречается
    - Position (15%): средняя позиция упоминания
    - Sentiment (15%): тональность упоминаний
    """
    brand_results = analysis.get_brand_results(brand_name)
    total_prompts = analysis.total_prompts
    total_models = analysis.total_models

    if total_prompts == 0 or total_models == 0:
        return 0

    # 1. Presence Rate
    prompts_with_mention = len({r.prompt for r in brand_results if r.mentioned})
    presence_rate = prompts_with_mention / total_prompts

    # 2. Model Coverage
    models_with_mention = len({r.model_name for r in brand_results if r.mentioned})
    model_coverage = models_with_mention / total_models

    # 3. Position (нормализованная: 1-я = 1.0, 5-я = 0.5, 10+ = 0.1)
    positions = [r.position for r in brand_results if r.mentioned and r.position > 0]
    if positions:
        avg_position = sum(positions) / len(positions)
        position_score = max(0.1, 1.0 - (avg_position - 1) * 0.1)
    else:
        position_score = 0.0

    # 4. Sentiment
    sentiments = [r.sentiment for r in brand_results if r.mentioned]
    if sentiments:
        sentiment_factor = (
            sentiments.count("positive") * 1.0
            + sentiments.count("neutral") * 0.7
            + sentiments.count("negative") * 0.3
        ) / len(sentiments)
    else:
        sentiment_factor = 0.0

    score = (
        presence_rate * 50
        + model_coverage * 20
        + position_score * 15
        + sentiment_factor * 15
    )

    return min(100, max(0, round(score)))


def calculate_share_of_voice(analysis: Analysis, brand_name: str) -> float:
    """Доля голоса бренда среди всех упоминаний."""
    total_mentions = sum(1 for r in analysis.all_results if r.mentioned)
    brand_mentions = sum(
        1 for r in analysis.all_results if r.mentioned and r.brand_name == brand_name
    )
    return round(brand_mentions / total_mentions * 100, 1) if total_mentions else 0.0


def calculate_presence_rate(analysis: Analysis, brand_name: str) -> int:
    """Процент промптов, в которых бренд упомянут."""
    if analysis.total_prompts == 0:
        return 0
    brand_results = analysis.get_brand_results(brand_name)
    mentioned_prompts = len({r.prompt for r in brand_results if r.mentioned})
    return round(mentioned_prompts / analysis.total_prompts * 100)


def get_model_breakdown(analysis: Analysis, brand_name: str) -> list[dict]:
    """Разбивка по моделям: % упоминаний, средняя позиция, тональность."""
    breakdown = []
    all_models = {r.model_name for r in analysis.all_results}

    for model_name in all_models:
        model_results = [
            r for r in analysis.get_brand_results(brand_name) if r.model_name == model_name
        ]
        total = len(model_results)
        if total == 0:
            continue

        mentioned = [r for r in model_results if r.mentioned]
        mention_rate = round(len(mentioned) / total * 100)

        positions = [r.position for r in mentioned if r.position > 0]
        avg_pos = round(sum(positions) / len(positions), 1) if positions else 0

        sentiments = [r.sentiment for r in mentioned]
        dominant_sentiment = (
            max(set(sentiments), key=sentiments.count) if sentiments else "neutral"
        )

        breakdown.append(
            {
                "model_name": model_name,
                "mention_rate": mention_rate,
                "avg_position": avg_pos,
                "dominant_sentiment": dominant_sentiment,
                "total_prompts": total,
                "mentioned_count": len(mentioned),
            "mentions": len(mentioned),
            "prompts_tested": total,
            "display_name": model_name,
            "presence_rate": mention_rate,
            "positive_count": sum(1 for r in mentioned if r.sentiment == "positive"),
            }
        )

    return sorted(breakdown, key=lambda x: x["mention_rate"], reverse=True)


def get_weak_models(analysis: Analysis, brand_name: str) -> list[str]:
    """Модели, где бренд не упоминается совсем."""
    breakdown = get_model_breakdown(analysis, brand_name)
    return [b["model_name"] for b in breakdown if b["mention_rate"] == 0]


def get_strong_models(analysis: Analysis, brand_name: str) -> list[str]:
    """Модели, где бренд упоминается часто."""
    breakdown = get_model_breakdown(analysis, brand_name)
    return [b["model_name"] for b in breakdown if b["mention_rate"] >= 50]


def get_top_sources(analysis: Analysis) -> list[str]:
    """Топ-10 доменов, на которые ИИ чаще всего ссылается."""
    from collections import Counter
    counter: Counter[str] = Counter(analysis.all_citations)
    return [domain for domain, _ in counter.most_common(10)]


def compare_with_competitors(
    analysis: Analysis, brand_name: str, all_brands: list[str]
) -> list[dict]:
    """Сравнение бренда с конкурентами по Score."""
    results = []
    for brand in all_brands:
        score = calculate_visibility_score(analysis, brand)
        presence = calculate_presence_rate(analysis, brand)
        sov = calculate_share_of_voice(analysis, brand)
        results.append(
            {
                "brand_name": brand,
                "is_client": brand == brand_name,
                "score": score,
                "presence_rate": presence,
                "share_of_voice": sov,
            "name": brand,
            "sov": sov,
            "models_found": 0,
            "models_total": 0,
            "dominant_sentiment": "neutral",
            }
        )
    return sorted(results, key=lambda x: x["score"], reverse=True)
