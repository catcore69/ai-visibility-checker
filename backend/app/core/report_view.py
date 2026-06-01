"""
Сборка богатой схемы онлайн-отчёта (ReportFull) из объекта Report + Analysis.

Раньше get_full_report возвращал минимальный набор полей, который не совпадал
с тем, что ждёт фронтенд (frontend/lib/api.ts → ReportFull). Это давало
ошибку «Отчёт не найден / Не удалось загрузить отчёт».

Здесь собираем ровно то, что нужно UI: компоненты Score, breakdown по моделям,
матрицу промптов, sentiment, лучшие/худшие промпты, образцы ответов.
"""
from collections import Counter
from typing import Any

from app.core.analyzer import Analysis, MentionResult
from app.core.scorer import (
    calculate_visibility_score,
    calculate_presence_rate,
    calculate_share_of_voice,
    get_model_breakdown,
    get_strong_models,
    get_weak_models,
)


# Отображаемые имена и CSS-классы моделей — синхронизированы с PDF-шаблонами.
# Порядок карточек в отчёте — единое место. Источники, которые есть в данных,
# но не в этом списке, идут в конце в алфавитном порядке.
MODEL_DISPLAY_ORDER = [
    "yandexgpt",
    "gigachat",
    "yandex_ai_search",
    "google_ai_overview",
    "chatgpt",
    "gemini",
    "deepseek",
    "perplexity",
]

MODEL_META: dict[str, dict[str, str]] = {
    "chatgpt":    {"display": "ChatGPT",     "short": "GPT",  "css": "model-chatgpt"},
    "openai":     {"display": "ChatGPT",     "short": "GPT",  "css": "model-chatgpt"},
    "yandexgpt":  {"display": "YandexGPT",   "short": "Я.GPT", "css": "model-yandex"},
    "google_ai_overview": {"display": "Google AI Overview", "short": "G.AI", "css": "model-google-ai"},
    # Этап 2.4 ТЗ: честное имя источника — XMLRiver SERP с AI-блоком,
    # не голосовой ассистент Алиса (прямого API у неё нет).
    "yandex_ai_search": {"display": "Яндекс-поиск с AI-блоком", "short": "Я.AI", "css": "model-yandex-ai"},
    # Совместимость со старыми отчётами, где ключ был "alisa".
    # Миграция 003 переименовывает ключ в существующих JSONB, но если где-то
    # остался — отрисуется под новым именем.
    "alisa":      {"display": "Яндекс-поиск с AI-блоком", "short": "Я.AI", "css": "model-yandex-ai"},
    "gigachat":   {"display": "GigaChat (Сбер)", "short": "Giga", "css": "model-gigachat"},
    "gemini":     {"display": "Gemini",      "short": "Gemini", "css": "model-gemini"},
    "deepseek":   {"display": "DeepSeek",    "short": "DS",   "css": "model-deepseek"},
    "perplexity": {"display": "Perplexity",  "short": "PPLX", "css": "model-perplexity"},
}


def _model_meta(model_name: str) -> dict[str, str]:
    key = (model_name or "").lower()
    if key in MODEL_META:
        return MODEL_META[key]
    return {"display": model_name or "—", "short": model_name or "—", "css": "model-generic"}


def _verdict_for_score(score: int) -> str:
    if score >= 80:
        return "Отличная видимость в ИИ — бренд устойчиво присутствует в большинстве ответов."
    if score >= 60:
        return "Хорошая видимость, но есть точки роста — особенно в позиционировании и сентименте."
    if score >= 40:
        return "Средняя видимость. Бренд узнаваем не во всех ИИ-ассистентах — нужна системная работа."
    if score >= 20:
        return "Низкая видимость. ИИ редко рекомендует бренд — конкуренты получают большую часть трафика."
    return "Критически низкая видимость. ИИ-ассистенты почти не знают о бренде — необходим срочный план действий."


def _score_components_pct(analysis: Analysis, brand_name: str) -> dict[str, int]:
    """Те же 4 компонента, что в calculate_visibility_score, но в виде процентов 0–100."""
    brand_results = analysis.get_brand_results(brand_name)
    total_prompts = analysis.total_prompts
    total_models = analysis.total_models

    if total_prompts == 0 or total_models == 0:
        return {"presence_rate_pct": 0, "model_coverage_pct": 0, "position_pct": 0, "sentiment_pct": 0}

    prompts_with_mention = len({r.prompt for r in brand_results if r.mentioned})
    presence = round(prompts_with_mention / total_prompts * 100)

    models_with_mention = len({r.model_name for r in brand_results if r.mentioned})
    coverage = round(models_with_mention / total_models * 100)

    positions = [r.position for r in brand_results if r.mentioned and r.position > 0]
    if positions:
        avg_pos = sum(positions) / len(positions)
        pos_pct = round(max(0.1, 1.0 - (avg_pos - 1) * 0.1) * 100)
    else:
        pos_pct = 0

    sents = [r.sentiment for r in brand_results if r.mentioned]
    if sents:
        sent_factor = (
            sents.count("positive") * 1.0
            + sents.count("neutral") * 0.7
            + sents.count("negative") * 0.3
        ) / len(sents)
        sent_pct = round(sent_factor * 100)
    else:
        sent_pct = 0

    return {
        "presence_rate_pct": presence,
        "model_coverage_pct": coverage,
        "position_pct": pos_pct,
        "sentiment_pct": sent_pct,
    }


def _sentiment_breakdown(analysis: Analysis, brand_name: str) -> dict[str, int]:
    sents = [r.sentiment for r in analysis.get_brand_results(brand_name) if r.mentioned]
    if not sents:
        return {
            "positive": 0, "neutral": 0, "negative": 0,
            "positive_pct": 0, "neutral_pct": 0, "negative_pct": 0,
        }
    c = Counter(sents)
    total = len(sents) or 1
    return {
        "positive":     c.get("positive", 0),
        "neutral":      c.get("neutral", 0),
        "negative":     c.get("negative", 0),
        "positive_pct": round(c.get("positive", 0) / total * 100),
        "neutral_pct":  round(c.get("neutral", 0) / total * 100),
        "negative_pct": round(c.get("negative", 0) / total * 100),
    }


def _build_prompts_matrix(analysis: Analysis, brand_name: str, model_names: list[str]) -> list[dict]:
    """Матрица prompt × model для текущего бренда."""
    by_prompt: dict[str, dict[str, MentionResult]] = {}
    for r in analysis.get_brand_results(brand_name):
        by_prompt.setdefault(r.prompt, {})[r.model_name] = r

    rows = []
    for prompt, per_model in by_prompt.items():
        cells = []
        for m in model_names:
            r = per_model.get(m)
            if r is None:
                cells.append({"model_name": m, "mentioned": False})
            else:
                cell: dict[str, Any] = {
                    "model_name": m,
                    "mentioned":  bool(r.mentioned),
                    "sentiment":  r.sentiment if r.mentioned else None,
                    "position":   r.position if r.mentioned and r.position else None,
                }
                cells.append(cell)
        rows.append({"prompt": prompt, "cells": cells})
    return rows


def _top_bottom_prompts(
    analysis: Analysis, brand_name: str, competitors: list[str], limit: int = 3
) -> tuple[list[dict], list[dict]]:
    by_prompt_brand: dict[str, list[MentionResult]] = {}
    by_prompt_competitors: dict[str, int] = {}

    for r in analysis.all_results:
        if r.brand_name == brand_name:
            by_prompt_brand.setdefault(r.prompt, []).append(r)
        elif r.brand_name in competitors and r.mentioned:
            by_prompt_competitors[r.prompt] = by_prompt_competitors.get(r.prompt, 0) + 1

    scored = []
    for prompt, results in by_prompt_brand.items():
        mention_count = sum(1 for r in results if r.mentioned)
        sents = [r.sentiment for r in results if r.mentioned]
        avg_sent = max(set(sents), key=sents.count) if sents else None
        scored.append({
            "prompt": prompt,
            "mention_count": mention_count,
            "avg_sentiment": avg_sent,
            "competitor_count": by_prompt_competitors.get(prompt, 0),
        })

    top    = sorted(scored, key=lambda x: -x["mention_count"])[:limit]
    bottom = sorted(scored, key=lambda x: (x["mention_count"], -x["competitor_count"]))[:limit]

    top_out = [{"prompt": p["prompt"], "mention_count": p["mention_count"], "avg_sentiment": p["avg_sentiment"]} for p in top if p["mention_count"] > 0]
    bot_out = [{"prompt": p["prompt"], "mention_count": p["mention_count"], "competitor_count": p["competitor_count"]} for p in bottom]
    return top_out, bot_out


def _best_responses(
    analysis: Analysis, brand_name: str, raw_responses: dict | None, limit: int = 3
) -> list[dict]:
    """Образцы ответов: берём по одному «лучшему» (упомянутому) на разные модели."""
    if not raw_responses:
        return []

    used_models: set[str] = set()
    out: list[dict] = []

    # сначала — где бренд упомянут, по приоритету: positive → neutral
    candidates: list[MentionResult] = sorted(
        [r for r in analysis.get_brand_results(brand_name) if r.mentioned],
        key=lambda r: 0 if r.sentiment == "positive" else (1 if r.sentiment == "neutral" else 2),
    )

    for r in candidates:
        if r.model_name in used_models:
            continue
        text = (raw_responses.get(r.model_name, {}) or {}).get(r.prompt) or ""
        if not text:
            continue
        meta = _model_meta(r.model_name)
        out.append({
            "model_name": r.model_name,
            "model_display_name": meta["display"],
            "model_css_class": meta["css"],
            "prompt": r.prompt,
            "response_excerpt": text[:380] + ("…" if len(text) > 380 else ""),
            "brand_mentioned": True,
            "position": r.position or None,
            "sentiment": r.sentiment,
        })
        used_models.add(r.model_name)
        if len(out) >= limit:
            break
    return out


def _top_weakness(
    competitor_rows: list[dict], brand_name: str, weak_models: list[str]
) -> str | None:
    me  = next((c for c in competitor_rows if c.get("is_client")), None)
    top = competitor_rows[0] if competitor_rows else None
    if me and top and not top.get("is_client") and top["score"] - me["score"] >= 10:
        return f"Конкурент «{top['name']}» опережает по AI Visibility Score на {top['score'] - me['score']} баллов."
    if weak_models:
        return f"Бренд практически не упоминается в: {', '.join(weak_models[:3])}."
    return None


def build_report_full_payload(report, analysis: Analysis) -> dict[str, Any]:
    """
    Главная функция: собирает dict, готовый для ReportFull(**payload).

    Принимает уже восстановленный Analysis (см. _restore_analysis в routes.py).
    """
    brand_name  = report.brand_name
    competitors = list(report.competitors or [])
    # Блок Б: кого ИИ называет в нише — сохранён в niche_data.
    from app.core.niche_detector import normalize_niche as _norm_niche
    nd = _norm_niche(report.niche_data if isinstance(report.niche_data, dict) else {})
    ai_mentioned_in_niche: list[str] = list(nd.get("ai_mentioned_in_niche") or [])
    # ТЗ Задача 3: для каждого имени из Блока Б знаем, федеральный ли он
    # (не в регионе клиента). Помечается «федеральный игрок, не локальный
    # конкурент» в UI/PDF.
    ai_mentioned_meta: dict = dict(nd.get("ai_mentioned_meta") or {})
    all_brands = [brand_name] + competitors + ai_mentioned_in_niche

    def _brand_row(b: str) -> dict:
        score = calculate_visibility_score(analysis, b)
        presence = calculate_presence_rate(analysis, b)
        sov = calculate_share_of_voice(analysis, b)
        b_results = [r for r in analysis.get_brand_results(b) if r.mentioned]
        models_found = len({r.model_name for r in b_results})
        sents = [r.sentiment for r in b_results]
        dom_sent = max(set(sents), key=sents.count) if sents else "neutral"
        return {
            "name": b,
            "is_client": b == brand_name,
            "score": score,
            "presence_rate": presence,
            "sov": sov,
            "models_found": models_found,
            "mentions": len(b_results),  # ТЗ Задача 2: абс. число упоминаний
            "dominant_sentiment": dom_sent,
        }

    # Полный список ВСЕХ брендов (Блок А + Блок Б + клиент) — нужен для total SoV.
    comparison_rank: list[dict] = [_brand_row(b) for b in all_brands]
    comparison_rank.sort(key=lambda x: -x["score"])

    # Блок А отдельной таблицей: клиент + прямые из выдачи.
    block_a_rows = [_brand_row(b) for b in ([brand_name] + competitors)]
    block_a_rows.sort(key=lambda x: (not x["is_client"], -x["score"]))

    # Блок Б: клиент (для сравнения) + кого ИИ называет в нише.
    # Для не-клиентских строк добавляем флаг is_other_market и подходящий
    # текст бейджа — «республиканский игрок» для клиентов из РБ, иначе
    # «федеральный игрок» (это маркер крупного игрока без местной привязки).
    client_region_str = (getattr(report, "region", "") or "")
    is_client_belarus = "беларус" in client_region_str.lower()
    cross_country_label = (
        "республиканский игрок, не локальный конкурент"
        if is_client_belarus
        else "федеральный игрок, не локальный конкурент"
    )
    other_region_label = "из другого региона, не локальный конкурент"

    def _label_for(m: dict) -> str:
        if not m:
            return ""
        # Другой регион внутри той же страны
        if m.get("is_other_region"):
            return other_region_label
        # Другая страна или международный домен без явной страны
        if m.get("is_other_market"):
            return cross_country_label
        return ""

    def _block_b_row(b: str) -> dict:
        r = _brand_row(b)
        if not r["is_client"]:
            m = ai_mentioned_meta.get(b.lower()) or {}
            r["is_other_market"] = bool(m.get("is_other_market"))
            r["is_other_region"] = bool(m.get("is_other_region"))
            r["site_country"] = m.get("site_country") or ""
            r["other_market_label"] = _label_for(m)
        else:
            r["is_other_market"] = False
            r["is_other_region"] = False
            r["site_country"] = ""
            r["other_market_label"] = ""
        return r
    block_b_rows = (
        [_block_b_row(b) for b in ([brand_name] + ai_mentioned_in_niche)]
        if ai_mentioned_in_niche else []
    )
    block_b_rows.sort(key=lambda x: (not x["is_client"], -x["score"]))

    # ТЗ catcore-nisha-primary-secondary, Задача 3: Блок Б показывается ВСЕГДА,
    # даже при accepted=0. Пустой Блок Б — это валидный сигнал «ниша свободна»
    # (Сценарий 1), а не повод его скрывать.
    DIRECT_MENTIONS_MIN = 3
    non_client_a = [r for r in block_a_rows if not r["is_client"]]
    max_direct_score = max((r["score"] for r in non_client_a), default=0)
    direct_mentions_total = sum(r.get("mentions", 0) for r in block_a_rows)
    has_real_leader = direct_mentions_total >= DIRECT_MENTIONS_MIN

    show_block_b = True  # всегда показываем секцию (фронт сам выберет — таблица или текст)

    # Три сценария для текстового вывода:
    #   scenario_3 — есть РЕАЛЬНЫЙ прямой лидер (≥ DIRECT_MENTIONS_MIN упоминаний);
    #   scenario_2 — прямых мало, но ИИ называет других в нише (Блок Б есть);
    #   scenario_1 — рынок полностью пустой.
    if has_real_leader:
        narrative_scenario = "scenario_3"
    elif show_block_b:
        narrative_scenario = "scenario_2"
    else:
        narrative_scenario = "scenario_1"

    # Список реально опрошенных моделей
    model_names_used = sorted({r.model_name for r in analysis.all_results})
    models_list = [
        {
            "model_name":   m,
            "display_name": _model_meta(m)["display"],
            "short_name":   _model_meta(m)["short"],
        }
        for m in model_names_used
    ]

    # Разбивка по моделям — берём из scorer и обогащаем мета-инфой и счётчиками
    raw_breakdown = get_model_breakdown(analysis, brand_name)
    model_breakdown: list[dict] = []
    for b in raw_breakdown:
        m = b["model_name"]
        meta = _model_meta(m)
        m_results = [
            r for r in analysis.get_brand_results(brand_name)
            if r.model_name == m and r.mentioned
        ]
        positive = sum(1 for r in m_results if r.sentiment == "positive")
        neutral  = sum(1 for r in m_results if r.sentiment == "neutral")
        negative = sum(1 for r in m_results if r.sentiment == "negative")
        model_breakdown.append({
            "model_name":         m,
            "display_name":       meta["display"],
            "short_name":         meta["short"],
            "presence_rate":      b.get("presence_rate", b.get("mention_rate", 0)),
            "mentions":           b.get("mentions", b.get("mentioned_count", 0)),
            "prompts_tested":     b.get("prompts_tested", b.get("total_prompts", 0)),
            "avg_position":       b.get("avg_position") or None,
            "dominant_sentiment": b.get("dominant_sentiment", "neutral"),
            "positive_count":     positive,
            "neutral_count":      neutral,
            "negative_count":     negative,
        })

    # Сортируем по фиксированному порядку отображения (YandexGPT → GigaChat →
    # Яндекс-AI-блок → Google AI Overview → ChatGPT → Gemini → DeepSeek → ...).
    _order_index = {m: i for i, m in enumerate(MODEL_DISPLAY_ORDER)}
    model_breakdown.sort(key=lambda item: (_order_index.get(item["model_name"], 999), item["model_name"]))

    # SoV-ранг клиента
    sov_rank = None
    sov_sorted = sorted(comparison_rank, key=lambda x: -x["sov"])
    for i, row in enumerate(sov_sorted, start=1):
        if row["is_client"]:
            sov_rank = i
            break

    strong = get_strong_models(analysis, brand_name)
    weak   = get_weak_models(analysis, brand_name)
    weak_display = [_model_meta(m)["display"] for m in weak]
    strong_display = [_model_meta(m)["display"] for m in strong]

    prompts_matrix = _build_prompts_matrix(analysis, brand_name, model_names_used)
    top_prompts, bottom_prompts = _top_bottom_prompts(analysis, brand_name, competitors)

    raw_responses = report.raw_responses or {}
    best = _best_responses(analysis, brand_name, raw_responses)

    # Рекомендации — нормализуем к схеме фронта
    recs_in = report.recommendations or []
    recs_out: list[dict] = []
    for r in recs_in:
        if not isinstance(r, dict):
            continue
        recs_out.append({
            "title":         r.get("title", ""),
            "description":   r.get("description", ""),
            "effort":        (r.get("effort") or "medium").lower(),
            "impact":        r.get("expected_impact") or r.get("impact"),
            "action_items":  r.get("action_items") or [],
            "priority":      r.get("priority"),
        })

    niche_data = report.niche_data or {}
    niche_label = (
        niche_data.get("name")
        or niche_data.get("category")
        or niche_data.get("niche")
        or ""
    )
    if isinstance(niche_label, dict):
        niche_label = niche_label.get("name", "")

    score_components = _score_components_pct(analysis, brand_name)
    sentiment_breakdown = _sentiment_breakdown(analysis, brand_name)

    return {
        "report_id":        report.id,
        "brand_name":       brand_name,
        "website_url":      report.url,
        "niche":            str(niche_label or ""),
        "created_at":       report.created_at,

        "visibility_score": int(report.visibility_score or 0),
        "presence_rate":    int(report.presence_rate or 0),
        "verdict":          _verdict_for_score(int(report.visibility_score or 0)),

        "models_found":     len({r.model_name for r in analysis.get_brand_results(brand_name) if r.mentioned}),
        "models_total":     len(model_names_used),
        "prompts_count":    analysis.total_prompts,

        "sov_rank":           sov_rank,
        "competitors_count":  len(competitors),

        "strong_models":     strong_display,
        "weak_models":       weak_display,
        "top_weakness":      _top_weakness(comparison_rank, brand_name, weak_display),

        "competitor_comparison": comparison_rank,
        # MD2.2: Блок А (прямые из выдачи) и Блок Б (кого ИИ называет в нише).
        "block_a_rows":          block_a_rows,
        "block_b_rows":          block_b_rows,
        "show_block_b":          show_block_b,
        "max_direct_score":      max_direct_score,
        "narrative_scenario":    narrative_scenario,
        "ai_mentioned_in_niche": ai_mentioned_in_niche,
        "model_breakdown":       model_breakdown,
        "prompts_matrix":        prompts_matrix,
        "models_list":           models_list,
        "top_prompts":           top_prompts,
        "bottom_prompts":        bottom_prompts,
        "recommendations":       recs_out,
        "expert_note":           report.expert_note,

        "score_components":     score_components,
        "sentiment_breakdown":  sentiment_breakdown,
        "best_responses":       best,

        "pdf_url":              report.pdf_url,
    }
