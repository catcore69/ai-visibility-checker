"""Текстовые формулировки по каждому сигналу site_analyzer.

Используются на странице 6 PDF — «Что есть у лидера, чего нет у вас».
Заголовок, объяснение, приоритет — для каждой галки чек-листа.

Приоритет: high — критично для ИИ-цитирования; medium — важно;
low — желательно. По нему формируется топ-3 ключевых разрывов в gap_analysis.
"""

from typing import TypedDict


class SignalExplanation(TypedDict):
    title: str
    client_has: str
    client_lacks: str
    competitor_has: str
    explanation: str
    priority: str  # "high" / "medium" / "low"


GAP_EXPLANATIONS: dict[str, SignalExplanation] = {
    "has_llms_txt": {
        "title": "Файл /llms.txt в корне сайта",
        "client_has": "Файл /llms.txt в корне сайта",
        "client_lacks": "Нет /llms.txt — ИИ-боты не получают структурированной подсказки о бизнесе",
        "competitor_has": "Файл /llms.txt — стандарт инструкции для языковых моделей",
        "explanation": (
            "llms.txt — относительно новый стандарт: текстовый файл в корне сайта, "
            "где компания описывает себя и свои услуги формате, удобном для языковых "
            "моделей. Большинство сайтов его пока не имеют — для конкурента это "
            "явное преимущество в индексе ИИ."
        ),
        "priority": "high",
    },
    "has_faq_schema": {
        "title": "FAQ со schema.org/FAQPage",
        "client_has": "FAQ-блок с разметкой schema.org/FAQPage",
        "client_lacks": "Нет FAQ со schema.org/FAQPage",
        "competitor_has": "FAQ-блок с разметкой schema.org/FAQPage",
        "explanation": (
            "Структурированные вопросы-ответы со schema.org/FAQPage — топливо "
            "для ИИ-ассистентов. Они часто берут именно такие блоки в качестве "
            "источника прямого ответа пользователю."
        ),
        "priority": "high",
    },
    "has_organization_schema": {
        "title": "Schema.org/Organization",
        "client_has": "Размеченный профиль организации (schema.org/Organization)",
        "client_lacks": "Нет schema.org/Organization — ИИ не считывает структурные факты о бренде",
        "competitor_has": "Размеченный профиль организации с указанием экспертизы",
        "explanation": (
            "Schema.org/Organization структурно объявляет фактическую информацию "
            "о компании — название, регион, контакты, специализацию. ИИ-ассистенты "
            "и поисковики используют эту разметку для атрибуции."
        ),
        "priority": "high",
    },
    "has_breadcrumb_schema": {
        "title": "Breadcrumb-разметка",
        "client_has": "Хлебные крошки со schema.org/BreadcrumbList",
        "client_lacks": "Нет breadcrumb-разметки",
        "competitor_has": "Хлебные крошки со schema.org/BreadcrumbList",
        "explanation": (
            "Breadcrumb помогает ИИ понимать иерархию сайта и группировать страницы "
            "по тематическим кластерам. Без этого модели цитируют отдельные URL "
            "без понимания структуры."
        ),
        "priority": "low",
    },
    "faq_block_present": {
        "title": "FAQ-блок на главной",
        "client_has": "FAQ-блок присутствует",
        "client_lacks": "Нет FAQ-блока на главной",
        "competitor_has": "FAQ-блок присутствует (даже без schema)",
        "explanation": (
            "Даже без schema.org/FAQPage — простой блок вопросов-ответов помогает "
            "ИИ выдёргивать конкретные ответы для цитирования."
        ),
        "priority": "medium",
    },
    "structured_headings": {
        "title": "Структурированная h1→h2→h3 иерархия",
        "client_has": "Чёткая иерархия заголовков",
        "client_lacks": "Заголовки на странице не иерархичны (нет h1 или каша из h2/h3)",
        "competitor_has": "Чёткая иерархия h1 → h2 → h3",
        "explanation": (
            "Языковые модели режут страницу на семантические блоки именно по h2/h3. "
            "Без иерархии ИИ не может правильно сегментировать контент и часто "
            "пропускает страницу при цитировании."
        ),
        "priority": "medium",
    },
    "about_page_present": {
        "title": "Страница «О компании»",
        "client_has": "Есть страница «О компании»",
        "client_lacks": "Нет отдельной страницы «О компании»",
        "competitor_has": "Есть страница «О компании» с фактами и экспертизой",
        "explanation": (
            "Страница «О нас» — главный источник информации о бренде для языковых "
            "моделей. Её отсутствие = пустой профиль бренда в индексе ИИ."
        ),
        "priority": "medium",
    },
    "contact_page_present": {
        "title": "Страница контактов",
        "client_has": "Есть страница контактов",
        "client_lacks": "Нет отдельной страницы контактов",
        "competitor_has": "Есть страница контактов",
        "explanation": (
            "Страница контактов содержит географические якоря, важные для "
            "региональной выдачи ИИ. Особенно важно для локального бизнеса."
        ),
        "priority": "low",
    },
    "has_sitemap": {
        "title": "Sitemap.xml",
        "client_has": "Есть sitemap.xml",
        "client_lacks": "Нет sitemap.xml",
        "competitor_has": "Есть sitemap.xml",
        "explanation": (
            "Sitemap не влияет на ИИ-ассистентов напрямую, но даёт поисковым "
            "роботам полный список страниц для индексации — а индекс поисковика "
            "часто используется ИИ-системами как источник."
        ),
        "priority": "low",
    },
    "expertise_signals_low": {
        "title": "Сигналы экспертизы (E-E-A-T)",
        "client_has": "На сайте видны сигналы экспертизы",
        "client_lacks": "Мало сигналов экспертизы: лет на рынке / сертификаты / команда",
        "competitor_has": "Сигналы экспертизы — стаж, лицензии, команда, сертификаты",
        "explanation": (
            "ИИ-ассистенты избегают рекомендовать бренды без подтверждённой "
            "экспертизы. Упоминания «N лет на рынке», лицензий, команды экспертов "
            "повышают «доверие» модели к источнику."
        ),
        "priority": "high",
    },
}
