"""Сборка PDF-отчёта через WeasyPrint + Jinja2, загрузка в S3."""

import base64
import io
from datetime import datetime
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
from jinja2 import Environment, FileSystemLoader
from weasyprint import HTML

from app.config import settings
from app.core.analyzer import Analysis
from app.core.scorer import (
    compare_with_competitors,
    get_model_breakdown,
    get_top_sources,
)
from app.storage.s3_client import S3Client
from app.utils.logger import get_logger

logger = get_logger(__name__)

TEMPLATES_DIR = Path(__file__).parent.parent.parent / "templates"


# ===== Цветовая палитра PDF (светлый брендбук CatCore) =====
PAPER_BG       = "#F4F1EA"
PAPER_SURFACE  = "#FFFFFF"
PAPER_BORDER   = "#D9D5CC"
PAPER_TEXT     = "#15171A"
PAPER_MUTED    = "#6E7480"
ACCENT_RED     = "#A63D3D"
ACCENT_DEEP    = "#7C1F1F"
COLOR_SUCCESS  = "#3BA776"
COLOR_WARNING  = "#D29A3C"
COLOR_DANGER   = "#B93A3A"


def _score_color(score: int) -> str:
    if score >= 60:
        return COLOR_SUCCESS
    if score >= 30:
        return COLOR_WARNING
    return COLOR_DANGER


def _make_score_chart(score: int) -> str:
    """Рисует круговой gauge для Score, возвращает base64 PNG."""
    fig, ax = plt.subplots(figsize=(4, 4), subplot_kw={"aspect": "equal"})

    color = _score_color(score)
    remaining = 100 - score

    wedges, _ = ax.pie(
        [score, remaining],
        startangle=90,
        colors=[color, PAPER_BORDER],
        wedgeprops={"width": 0.4, "edgecolor": PAPER_SURFACE, "linewidth": 2},
    )

    ax.text(0, 0, str(score), ha="center", va="center", fontsize=36, fontweight="bold", color=color)
    ax.text(0, -0.35, "/ 100", ha="center", va="center", fontsize=14, color=PAPER_MUTED)

    plt.tight_layout(pad=0)
    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=120, bbox_inches="tight", transparent=True)
    plt.close(fig)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode()


def _make_competitor_chart(comparison: list[dict]) -> str:
    """Bar chart сравнения брендов, возвращает base64 PNG."""
    fig, ax = plt.subplots(figsize=(8, max(3, len(comparison) * 0.8)))

    brands = [c["brand_name"] for c in reversed(comparison)]
    scores = [c["score"] for c in reversed(comparison)]
    colors = [ACCENT_RED if c["is_client"] else "#BDB8AD" for c in reversed(comparison)]

    bars = ax.barh(brands, scores, color=colors, height=0.6, edgecolor="none")

    for bar, score in zip(bars, scores):
        ax.text(
            bar.get_width() + 0.5,
            bar.get_y() + bar.get_height() / 2,
            str(score),
            va="center",
            fontsize=11,
            color=PAPER_TEXT,
        )

    ax.set_xlim(0, 105)
    ax.set_xlabel("AI Visibility Score", fontsize=11, color=PAPER_TEXT)
    ax.tick_params(colors=PAPER_TEXT)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color(PAPER_BORDER)
    ax.spines["bottom"].set_color(PAPER_BORDER)
    ax.axvline(x=50, color=COLOR_WARNING, linestyle="--", alpha=0.5, linewidth=1)

    plt.tight_layout()
    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=120, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode()


def _make_sentiment_pie(analysis: Analysis, brand_name: str) -> str:
    """Pie chart тональности упоминаний, возвращает base64 PNG."""
    brand_results = [r for r in analysis.get_brand_results(brand_name) if r.mentioned]
    sentiments = [r.sentiment for r in brand_results]

    pos = sentiments.count("positive")
    neu = sentiments.count("neutral")
    neg = sentiments.count("negative")

    if not (pos + neu + neg):
        pos, neu, neg = 0, 1, 0

    fig, ax = plt.subplots(figsize=(4, 4))
    labels = ["Позитивные", "Нейтральные", "Негативные"]
    sizes = [pos, neu, neg]
    colors = [COLOR_SUCCESS, PAPER_MUTED, COLOR_DANGER]
    explode = (0.05, 0, 0.05)

    ax.pie(
        sizes,
        labels=labels,
        colors=colors,
        explode=explode,
        autopct="%1.0f%%",
        startangle=90,
        textprops={"fontsize": 11},
    )

    plt.tight_layout()
    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=120, bbox_inches="tight", transparent=True)
    plt.close(fig)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode()


def _get_worst_prompts(
    analysis: Analysis, brand_name: str, competitors: list[str], count: int = 5
) -> list[dict]:
    """Промпты, где конкуренты упоминаются, а бренд клиента — нет."""
    worst = []
    all_prompts = {r.prompt for r in analysis.all_results}

    for prompt in all_prompts:
        client_mentioned = any(
            r.mentioned for r in analysis.get_brand_results(brand_name) if r.prompt == prompt
        )
        if client_mentioned:
            continue

        # Собираем упоминания конкурентов в этом промпте
        competitor_mentions = []
        for comp in competitors:
            for r in analysis.get_brand_results(comp):
                if r.prompt == prompt and r.mentioned:
                    competitor_mentions.append(
                        {
                            "brand": comp,
                            "model": r.model_name,
                            "context": r.context,
                            "sentiment": r.sentiment,
                        }
                    )
        if competitor_mentions:
            # Уникальные конкуренты упомянутые в этом промпте
            competitors_mentioned = list(dict.fromkeys(m["brand"] for m in competitor_mentions))
            # Сколько моделей упомянули конкурентов
            models_with_competitor = len(set(m["model"] for m in competitor_mentions))
            total_models = len(set(r.model_name for r in analysis.all_results if r.prompt == prompt))
            gap_score = int(models_with_competitor / total_models * 100) if total_models > 0 else 0
            worst.append({
                "prompt": prompt,
                "competitor_mentions": competitor_mentions[:3],
                "competitors_mentioned": competitors_mentioned[:5],
                "client_position": None,
                "gap_score": gap_score,
            })

    return worst[:count]


def _mark_competitors_red(text: str, competitors: list[str]) -> str:
    """Выделяет упоминания конкурентов красным цветом в HTML."""
    import re

    for comp in competitors:
        pattern = re.compile(re.escape(comp), re.IGNORECASE)
        text = pattern.sub(
            f'<span style="color:{ACCENT_RED}; font-weight:600;">{comp}</span>', text
        )
    return text


async def build_and_upload_pdf(report, analysis: Analysis, competitors: list[str]) -> str:
    """Собирает PDF-отчёт, загружает в S3, возвращает URL."""
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=True,
    )
    env.filters["mark_competitors_red"] = lambda text: _mark_competitors_red(
        text, competitors
    )

    brand_name = report.brand_name
    score = report.visibility_score or 0
    niche = report.niche_data or {}
    all_brands = [brand_name] + competitors

    comparison = compare_with_competitors(analysis, brand_name, all_brands)
    model_breakdown = get_model_breakdown(analysis, brand_name)
    top_sources = get_top_sources(analysis)
    worst_prompts = _get_worst_prompts(analysis, brand_name, competitors)

    # Графики
    score_chart_b64 = _make_score_chart(score)

    # Score components for template
    _brand_results = analysis.get_brand_results(brand_name)
    _total_prompts = analysis.total_prompts
    _total_models = analysis.total_models
    if _total_prompts > 0 and _total_models > 0:
        _presence_rate = len([r for r in _brand_results if r.mentioned]) / _total_prompts
        _model_coverage = len({r.model_name for r in _brand_results if r.mentioned}) / _total_models
        _positions = [r.position for r in _brand_results if r.mentioned and r.position > 0]
        _position_score = max(0.1, 1.0 - (sum(_positions) / len(_positions) - 1) * 0.1) if _positions else 0.0
        _sentiments = [r.sentiment for r in _brand_results if r.mentioned]
        if _sentiments:
            _sentiment_factor = (
                _sentiments.count("positive") * 1.0
                + _sentiments.count("neutral") * 0.7
                + _sentiments.count("negative") * 0.3
            ) / len(_sentiments)
        else:
            _sentiment_factor = 0.0
    else:
        _presence_rate = _model_coverage = _position_score = _sentiment_factor = 0.0
    score_components = type("ScoreComponents", (), {
        "presence_rate_pct": round(_presence_rate * 100),
        "model_coverage_pct": round(_model_coverage * 100),
        "position_pct": round(_position_score * 100),
        "sentiment_pct": round(_sentiment_factor * 100),
    })()

    competitor_chart_b64 = _make_competitor_chart(comparison)
    sentiment_chart_b64 = _make_sentiment_pie(analysis, brand_name)

    # Этап 3 ТЗ: данные для новых страниц PDF.
    # Сборка нужных представлений из ReportView, чтобы PDF и фронт показывали
    # одни и те же цифры (consistency).
    from app.core.report_view import build_report_full_payload
    view_payload = build_report_full_payload(report, analysis)

    # Cover-вердикт по диапазонам ТЗ — короткая фраза, не «низкая видимость».
    if score < 31:
        cover_verdict = "Ваш бренд почти невидим для ИИ."
    elif score < 61:
        cover_verdict = "ИИ знает о вас, но рекомендует других."
    else:
        cover_verdict = "Вы в игре — есть куда расти."

    context = {
        # Основные данные
        "report": report,
        "brand_name": brand_name,
        "score": score,
        "visibility_score": score,
        "score_color": _score_color(score),
        "score_label": "Низкая" if score < 30 else "Средняя" if score < 60 else "Высокая",
        "cover_verdict": cover_verdict,
        "report_date": datetime.now().strftime("%d.%m.%Y"),
        "niche": niche,
        "region": report.region,
        "competitors": competitors,
        "competitors_source": report.competitors_source or "llm",  # для методологии
        "prompts": report.prompts or [],  # список 10 промптов для методологии
        "recommendations": report.recommendations or [],
        "expert_note": report.expert_note,

        # Этап 2 ТЗ — данные site_analyzer и gap_analyzer
        "client_site_analysis": report.client_site_analysis or {},
        "competitors_site_analysis": report.competitors_site_analysis or [],
        "competitor_urls": report.competitor_urls or [],
        "gap_analysis": report.gap_analysis or {},

        # Аналитика
        "comparison": comparison,
        "competitor_comparison": comparison,
        "model_breakdown": model_breakdown,
        "top_sources": top_sources[:10],
        "worst_prompts": worst_prompts,
        "presence_rate": report.presence_rate or 0,
        "share_of_voice": report.share_of_voice or 0,

        # Данные из view_payload для синхронизации с фронтом
        "prompts_matrix": view_payload.get("prompts_matrix", []),
        "models_list": view_payload.get("models_list", []),
        "best_responses": view_payload.get("best_responses", []),
        "sentiment_breakdown": view_payload.get("sentiment_breakdown"),
        "strong_models": view_payload.get("strong_models", []),
        "weak_models": view_payload.get("weak_models", []),
        "top_prompts": view_payload.get("top_prompts", []),
        "bottom_prompts": view_payload.get("bottom_prompts", []),

        # Графики (base64 PNG)
        "score_components": score_components,
        "score_chart_b64": score_chart_b64,
        "competitor_chart_b64": competitor_chart_b64,
        "sentiment_chart_b64": sentiment_chart_b64,

        # Студия и эксперт
        "EXPERT_NAME": settings.EXPERT_NAME,
        "EXPERT_TITLE": settings.EXPERT_TITLE,
        "EXPERT_PHOTO_URL": settings.EXPERT_PHOTO_URL,
        "STUDIO_NAME": settings.STUDIO_NAME,
        "STUDIO_FULL_URL": settings.STUDIO_FULL_URL,
        "STUDIO_LOGO_URL": settings.STUDIO_LOGO_URL,
        "CONTACT_TG_BOT_URL": settings.CONTACT_TG_BOT_URL,
        "CONTACT_TG_BOT": settings.CONTACT_TG_BOT,
        "CONTACT_EMAIL": settings.CONTACT_EMAIL,

        # Этап 3 ТЗ — пакеты услуг и виджет бронирования
        "PACKAGE_DORABOTKA_PRICE_FROM": settings.PACKAGE_DORABOTKA_PRICE_FROM,
        "PACKAGE_FULL_SITE_PRICE_FROM": settings.PACKAGE_FULL_SITE_PRICE_FROM,
        "PACKAGE_GROWTH_PROMISE_POINTS": settings.PACKAGE_GROWTH_PROMISE_POINTS,
        "BOOKING_WIDGET_URL": (
            f"{settings.STUDIO_FULL_URL}/zapis-na-razgovor"
            f"?report_id={report.id}&utm_source=ai_report&utm_campaign=cta_call"
        ),
        "CHECKLIST_URL": (
            f"{settings.STUDIO_FULL_URL}/checklist"
            f"?report_id={report.id}&utm_source=ai_report&utm_campaign=cta_checklist"
        ),

        # Статистика анализа (для шаблонов)
        "prompts_count": analysis.total_prompts,
        "models_total": analysis.total_models,
        "models_found": len(set(r.model_name for r in analysis.get_brand_results(brand_name) if r.mentioned)),
        "total_queries": analysis.total_prompts * analysis.total_models,
        "competitors_count": len(competitors),
        "sov_rank": next((i+1 for i, c in enumerate(sorted(comparison, key=lambda x: -x.get("share_of_voice", 0))) if c.get("brand_name") == brand_name or c.get("name") == brand_name), len(competitors)+1),
        "verdict": ("Высокая видимость" if score >= 60 else "Средняя видимость" if score >= 30 else "Низкая видимость"),
        "top_weakness": (worst_prompts[0]["prompt"] if worst_prompts else "Нет данных"),
    }

    template = env.get_template("report.html")
    html_content = template.render(**context)

    # WeasyPrint рендер
    pdf_bytes = HTML(string=html_content, base_url=str(TEMPLATES_DIR)).write_pdf()

    # Загрузка в S3
    s3 = S3Client()
    key = f"reports/{report.id}.pdf"
    pdf_url = await s3.upload_bytes(key, pdf_bytes, content_type="application/pdf")

    # Сохраняем ключ в report
    from app.db.session import AsyncSessionLocal
    from app.db.repositories.report_repo import update_report_field
    async with AsyncSessionLocal() as db:
        await update_report_field(db, report.id, pdf_s3_key=key, pdf_url=pdf_url)

    logger.info("pdf_built", report_id=str(report.id), size=len(pdf_bytes))
    return pdf_url
