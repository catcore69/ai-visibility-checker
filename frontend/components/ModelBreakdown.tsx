'use client';

import type { ModelBreakdown } from '@/lib/api';

interface Props {
  data: ModelBreakdown[];
}

const MODEL_COLORS: Record<string, { bg: string; text: string; dot: string }> = {
  chatgpt:    { bg: 'bg-gray-50',     text: 'text-gray-800',  dot: 'bg-gray-700'  },
  yandex:     { bg: 'bg-yellow-50',   text: 'text-yellow-900',dot: 'bg-yellow-500'},
  gigachat:   { bg: 'bg-green-50',    text: 'text-green-900', dot: 'bg-green-500' },
  gemini:     { bg: 'bg-blue-50',     text: 'text-blue-900',  dot: 'bg-blue-500'  },
  deepseek:   { bg: 'bg-purple-50',   text: 'text-purple-900',dot: 'bg-purple-500'},
  alisa:      { bg: 'bg-pink-50',     text: 'text-pink-900',  dot: 'bg-pink-500'  },
  perplexity: { bg: 'bg-violet-50',   text: 'text-violet-900',dot: 'bg-violet-500'},
};

function getCssClass(modelName: string): string {
  const lower = modelName.toLowerCase();
  if (lower.includes('chatgpt') || lower.includes('openai') || lower.includes('gpt')) return 'chatgpt';
  if (lower.includes('yandex') || lower.includes('yagpt')) return 'yandex';
  if (lower.includes('gigachat') || lower.includes('giga')) return 'gigachat';
  if (lower.includes('gemini')) return 'gemini';
  if (lower.includes('deepseek')) return 'deepseek';
  if (lower.includes('alisa') || lower.includes('alice') || lower.includes('yandex_neuro')) return 'alisa';
  if (lower.includes('perplexity')) return 'perplexity';
  return 'chatgpt';
}

const SENTIMENT_LABELS: Record<string, { label: string; cls: string }> = {
  positive: { label: 'позитив', cls: 'bg-green-100 text-green-700' },
  neutral:  { label: 'нейтрально', cls: 'bg-gray-100 text-gray-600' },
  negative: { label: 'негатив', cls: 'bg-red-100 text-red-700' },
};

export default function ModelBreakdownGrid({ data }: Props) {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
      {data.map(model => {
        const cssKey = getCssClass(model.model_name);
        const colors = MODEL_COLORS[cssKey] || MODEL_COLORS.chatgpt;
        const hasData = model.mentions > 0;
        const rate = model.presence_rate;

        return (
          <div
            key={model.model_name}
            className={`rounded-2xl border-2 p-5 flex flex-col gap-3 ${
              hasData ? `${colors.bg} border-current` : 'bg-gray-50 border-gray-100'
            }`}
          >
            {/* Header */}
            <div className="flex items-center gap-2">
              <div className={`w-2.5 h-2.5 rounded-full flex-shrink-0 ${hasData ? colors.dot : 'bg-gray-300'}`} />
              <span className={`font-bold text-sm ${hasData ? colors.text : 'text-gray-500'}`}>
                {model.display_name}
              </span>
            </div>

            {/* Presence Rate */}
            <div>
              <div className="flex justify-between items-end mb-1">
                <span className="text-xs text-gray-500">Presence Rate</span>
                <span className={`text-2xl font-black leading-none ${
                  rate >= 60 ? 'text-green-500' : rate >= 30 ? 'text-orange-500' : rate > 0 ? 'text-red-500' : 'text-gray-400'
                }`}>
                  {rate}%
                </span>
              </div>
              <div className="w-full h-2 bg-gray-200 rounded-full overflow-hidden">
                <div
                  className={`h-full rounded-full transition-all duration-700 ${
                    rate >= 60 ? 'bg-green-500' : rate >= 30 ? 'bg-orange-500' : rate > 0 ? 'bg-red-500' : 'bg-gray-300'
                  }`}
                  style={{ width: `${rate}%` }}
                />
              </div>
              <p className="text-xs text-gray-400 mt-1">
                {model.mentions} из {model.prompts_tested} запросов
              </p>
            </div>

            {/* Avg position */}
            {model.avg_position != null && (
              <div className="text-xs text-gray-500">
                Средняя позиция: <strong>#{model.avg_position}</strong>
              </div>
            )}

            {/* Sentiment */}
            {model.dominant_sentiment && (
              <div>
                {(() => {
                  const s = SENTIMENT_LABELS[model.dominant_sentiment];
                  return s ? (
                    <span className={`text-xs px-2 py-0.5 rounded-full font-semibold ${s.cls}`}>
                      {s.label}
                    </span>
                  ) : null;
                })()}
              </div>
            )}

            {/* Status badge */}
            <div className="mt-auto">
              {rate >= 60 ? (
                <span className="text-xs font-medium text-green-600">✅ Сильная позиция</span>
              ) : rate >= 30 ? (
                <span className="text-xs font-medium text-orange-500">⚡ Требует внимания</span>
              ) : rate > 0 ? (
                <span className="text-xs font-medium text-red-500">⚠️ Слабая позиция</span>
              ) : (
                <span className="text-xs font-medium text-gray-400">❌ Не упоминается</span>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
