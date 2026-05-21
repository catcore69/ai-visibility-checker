'use client';

import type { ModelBreakdown } from '@/lib/api';

interface Props {
  data: ModelBreakdown[];
}

const SENTIMENT_LABELS: Record<string, { label: string; cls: string }> = {
  positive: { label: 'позитив',     cls: 'bg-success/15 text-success border border-success/30' },
  neutral:  { label: 'нейтрально',  cls: 'bg-brand-surface text-brand-muted border border-brand-border' },
  negative: { label: 'негатив',     cls: 'bg-danger/15 text-danger border border-danger/30' },
};

function statusColor(rate: number) {
  if (rate >= 60) return 'text-success';
  if (rate >= 30) return 'text-warning';
  if (rate > 0)   return 'text-danger';
  return 'text-brand-muted';
}

function barColor(rate: number) {
  if (rate >= 60) return 'bg-success';
  if (rate >= 30) return 'bg-warning';
  if (rate > 0)   return 'bg-danger';
  return 'bg-brand-elevated';
}

export default function ModelBreakdownGrid({ data }: Props) {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
      {data.map((model) => {
        const rate = model.presence_rate;
        return (
          <div key={model.model_name} className="card-surface p-5 flex flex-col gap-3">
            <div className="flex items-center gap-2">
              <span className={`w-2 h-2 rounded-full ${rate > 0 ? 'bg-accent-500' : 'bg-brand-elevated'}`} />
              <span className="font-heading text-sm text-brand-textBright">{model.display_name}</span>
            </div>

            <div>
              <div className="flex justify-between items-end mb-1">
                <span className="text-xs text-brand-muted">Presence Rate</span>
                <span className={`text-2xl font-heading leading-none ${statusColor(rate)}`}>{rate}%</span>
              </div>
              <div className="w-full h-1.5 bg-brand-elevated rounded-full overflow-hidden">
                <div
                  className={`h-full rounded-full transition-all duration-700 ${barColor(rate)}`}
                  style={{ width: `${rate}%` }}
                />
              </div>
              <p className="text-xs text-brand-muted mt-1">
                {model.mentions} из {model.prompts_tested} запросов
              </p>
            </div>

            {model.avg_position != null && (
              <div className="text-xs text-brand-muted">
                Средняя позиция: <strong className="text-brand-text">#{model.avg_position}</strong>
              </div>
            )}

            {model.dominant_sentiment && SENTIMENT_LABELS[model.dominant_sentiment] && (
              <span
                className={`text-xs px-2 py-0.5 rounded-full font-medium self-start ${SENTIMENT_LABELS[model.dominant_sentiment].cls}`}
              >
                {SENTIMENT_LABELS[model.dominant_sentiment].label}
              </span>
            )}

            <div className="mt-auto">
              {rate >= 60 ? (
                <span className="text-xs font-medium text-success">Сильная позиция</span>
              ) : rate >= 30 ? (
                <span className="text-xs font-medium text-warning">Требует внимания</span>
              ) : rate > 0 ? (
                <span className="text-xs font-medium text-danger">Слабая позиция</span>
              ) : (
                <span className="text-xs font-medium text-brand-muted">Не упоминается</span>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
