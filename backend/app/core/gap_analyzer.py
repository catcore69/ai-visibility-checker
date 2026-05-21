"""Сравнение анализа сайта клиента с лидером-конкурентом.

Этап 2.3 ТЗ. Берём site_analyzer-результаты для клиента и для всех конкурентов,
находим лидера (по SoV, передаётся снаружи), и считаем разрывы: что есть у лидера,
чего нет у клиента. Это источник данных для страницы 6 PDF.
"""

from typing import Any, Optional

from app.core.gap_explanations import GAP_EXPLANATIONS
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Сигналы, которые проверяем для разрыва (boolean-флаги из site_analyzer).
# expertise_signals — числовой, обрабатывается отдельно ниже.
BOOLEAN_SIGNALS = [
    "has_llms_txt",
    "has_faq_schema",
    "has_organization_schema",
    "has_breadcrumb_schema",
    "faq_block_present",
    "structured_headings",
    "about_page_present",
    "contact_page_present",
    "has_sitemap",
]


def _signal_priority_score(priority: str) -> int:
    return {"high": 3, "medium": 2, "low": 1}.get(priority, 0)


def build_gap_analysis(
    client_analysis: Optional[dict],
    competitors_analysis: list[dict],
    competitor_urls: list[dict],
    leader_name: Optional[str] = None,
) -> dict[str, Any]:
    """Строит gap_analysis dict для страницы 6 PDF.

    Args:
        client_analysis: результат site_analyzer для клиента (или None если упал)
        competitors_analysis: список dict'ов (по одному на каждого конкурента)
        competitor_urls: [{name, url}, ...] — имена и URL конкурентов
        leader_name: имя лидера по SoV (если None, берём первого с fetched=True)

    Returns:
        dict: client_has, client_lacks, competitor_leader, key_gaps
    """
    if not client_analysis or not client_analysis.get("fetched"):
        logger.info("gap_analysis_skipped_client_not_fetched")
        return {
            "client_has": [],
            "client_lacks": [],
            "competitor_leader": None,
            "key_gaps": [],
            "note": "Не удалось проанализировать сайт клиента — gap-анализ пропущен.",
        }

    # Что есть/нет у клиента
    client_has: list[str] = []
    client_lacks: list[str] = []
    for sig in BOOLEAN_SIGNALS:
        if client_analysis.get(sig):
            client_has.append(sig)
        else:
            client_lacks.append(sig)
    # E-E-A-T — числовой
    expertise = int(client_analysis.get("expertise_signals", 0) or 0)
    if expertise < 3:
        client_lacks.append("expertise_signals_low")
    else:
        client_has.append("expertise_signals_low")

    # Находим лидера среди конкурентов
    leader: Optional[dict] = None
    if leader_name:
        # Маппим analysis к имени через competitor_urls
        url_by_name = {c.get("name"): c.get("url") for c in (competitor_urls or [])}
        leader_url = url_by_name.get(leader_name)
        for comp in competitors_analysis or []:
            if comp.get("fetched") and comp.get("url") == leader_url:
                leader = comp
                break

    # Fallback — первый успешный анализ
    if not leader:
        for comp in competitors_analysis or []:
            if comp.get("fetched"):
                leader = comp
                break

    if not leader:
        logger.info("gap_analysis_no_leader_analysed")
        return {
            "client_has": client_has,
            "client_lacks": client_lacks,
            "competitor_leader": None,
            "key_gaps": [],
            "note": "Не удалось проанализировать ни одного сайта конкурентов.",
        }

    # Что есть у лидера + чего нет у клиента → ключевые разрывы
    leader_has: list[str] = []
    leader_lacks: list[str] = []
    for sig in BOOLEAN_SIGNALS:
        if leader.get(sig):
            leader_has.append(sig)
        else:
            leader_lacks.append(sig)
    leader_expertise = int(leader.get("expertise_signals", 0) or 0)
    if leader_expertise >= 3:
        leader_has.append("expertise_signals_low")
    else:
        leader_lacks.append("expertise_signals_low")

    # Ключевые разрывы: есть у лидера, нет у клиента, отсортированы по приоритету.
    key_gaps_raw = [s for s in leader_has if s in client_lacks]
    key_gaps = sorted(
        key_gaps_raw,
        key=lambda s: -_signal_priority_score(GAP_EXPLANATIONS.get(s, {}).get("priority", "low")),
    )[:3]

    # Формируем человеческие формулировки для топ-3 разрывов
    key_gaps_detail = []
    for sig in key_gaps:
        exp = GAP_EXPLANATIONS.get(sig)
        if not exp:
            continue
        key_gaps_detail.append(
            {
                "signal": sig,
                "title": exp["title"],
                "explanation": exp["explanation"],
                "priority": exp["priority"],
            }
        )

    # Найдём имя лидера для PDF
    leader_display_name = leader_name
    if not leader_display_name:
        url_to_name = {c.get("url"): c.get("name") for c in (competitor_urls or [])}
        leader_display_name = url_to_name.get(leader.get("url"))

    return {
        "client_has": client_has,
        "client_lacks": client_lacks,
        "competitor_leader": {
            "name": leader_display_name,
            "url": leader.get("url"),
            "has": leader_has,
            "lacks": leader_lacks,
        },
        "key_gaps": key_gaps_detail,
    }
