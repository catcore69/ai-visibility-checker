export const LOADING_FACTS: string[] = [
  'ChatGPT обрабатывает более 10 млн запросов в день — многие из них про бренды и компании.',
  '46% пользователей уже используют ИИ-ассистентов для поиска товаров и услуг.',
  'Бренды с упоминаниями в Википедии получают в 3,5× больше ИИ-ссылок.',
  'GEO (Generative Engine Optimization) — самый быстрорастущий тренд в digital-маркетинге 2024–2025.',
  'YandexGPT активно использует данные из Яндекс.Маркета, отзовиков и Яндекс.Бизнеса.',
  'Первая позиция в ответе ИИ-ассистента даёт в 4× больший CTR, чем третья.',
  'GigaChat предпочитает источники на русском языке — Habr, VC.ru, РБК, профильные журналы.',
  'Gemini активно цитирует Google-источники: Google Business, YouTube, Google Maps.',
  'Perplexity использует веб-поиск в реальном времени — свежий контент получает больший вес.',
  'Позитивные отзывы на агрегаторах напрямую влияют на тональность упоминаний в ИИ.',
  'Компании с регулярными пресс-релизами упоминаются в ИИ на 60% чаще конкурентов.',
  'DeepSeek обучен преимущественно на англоязычных данных, но хорошо работает и с русским контентом.',
  'Структурированные данные (Schema.org) помогают ИИ-моделям точнее понять бренд.',
  'Около 30% запросов к ИИ-ассистентам связаны с выбором товаров, услуг или компаний.',
  'Экспертный контент в авторитетных СМИ — основа высокого AI Visibility Score.',
  'Алиса (Яндекс) учитывает данные из Яндекс.Справочника — важно держать карточку актуальной.',
  'Бренды с кейсами и реальными результатами получают в 2× больше позитивных упоминаний.',
  'FAQ-страницы с вопросами в формате поиска — один из лучших способов попасть в ИИ-ответы.',
  'ИИ-поиск меняет SEO: теперь важно быть источником, а не просто ранжироваться.',
  'Упоминания бренда в обучающих данных ИИ — фундамент долгосрочной AI Visibility.',
];

export function getRandomFacts(count = 3): string[] {
  const shuffled = [...LOADING_FACTS].sort(() => Math.random() - 0.5);
  return shuffled.slice(0, count);
}

/**
 * Названия статусов идут СТРОГО как их эмитит backend/app/core/pipeline.py.
 * Если меняешь имена в pipeline — обнови оба словаря.
 */
export const STEP_LABELS: Record<string, string> = {
  pending_verification:       'Ожидание подтверждения email',
  verification_complete:      'Email подтверждён, ставим в очередь',
  pending:                    'В очереди на проверку',
  queued:                     'В очереди на проверку',
  niche_detection:            'Определяем нишу и рынок',
  competitor_discovery:       'Ищем конкурентов',
  prompt_generation:          'Генерируем поисковые запросы',
  polling_models:             'Опрашиваем ИИ-ассистентов',
  analyzing_responses:        'Анализируем упоминания',
  calculating_score:          'Рассчитываем AI Visibility Score',
  generating_recommendations: 'Готовим рекомендации',
  building_pdf:               'Формируем PDF-отчёт',
  awaiting_personal_note:     'Эксперт добавляет личную заметку',
  sending_email:              'Отправляем на почту',
  completed:                  'Готово!',
  failed:                     'Ошибка',
};

export const STEP_PROGRESS: Record<string, number> = {
  pending_verification:        0,
  verification_complete:       3,
  pending:                     3,
  queued:                      3,
  niche_detection:             5,
  competitor_discovery:       15,
  prompt_generation:          25,
  polling_models:             35,
  analyzing_responses:        70,
  calculating_score:          85,
  generating_recommendations: 92,
  building_pdf:               96,
  awaiting_personal_note:     99,
  sending_email:              99,
  completed:                 100,
  failed:                      0,
};

/**
 * Карта status → индекс шага в UI-списке `ProgressTracker.steps[]`.
 * Несколько внутренних статусов мапятся на один визуальный шаг.
 *
 * Важно: на стадии awaiting_personal_note / sending_email PDF уже физически
 * собран, поэтому шаги «Анализ» и «Формирование отчёта» помечаем как done
 * (индекс = steps.length). Клиент видит «всё готово, ждём эксперта».
 */
export const STEP_INDEX: Record<string, number> = {
  niche_detection:             0,
  competitor_discovery:        1,
  prompt_generation:           2,
  polling_models:              3,
  analyzing_responses:         4,
  calculating_score:           4,
  generating_recommendations:  4,
  building_pdf:                5,
  awaiting_personal_note:      6, // PDF уже готов, ждём эксперта
  sending_email:               6,
  completed:                   6, // > последнего индекса = все шаги done
};
