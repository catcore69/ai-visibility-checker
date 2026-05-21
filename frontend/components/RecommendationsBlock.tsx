'use client';

import type { Recommendation } from '@/lib/api';

interface Props {
  recommendations: Recommendation[];
}

const EFFORT_CONFIG: Record<string, { label: string; cls: string }> = {
  low:    { label: 'Быстро', cls: 'bg-success/15 text-success border border-success/30' },
  medium: { label: 'Средне', cls: 'bg-warning/15 text-warning border border-warning/30' },
  high:   { label: 'Сложно', cls: 'bg-danger/15 text-danger border border-danger/30' },
};

export default function RecommendationsBlock({ recommendations }: Props) {
  return (
    <div className="flex flex-col gap-6">
      {recommendations.map((rec, idx) => {
        const effort = EFFORT_CONFIG[rec.effort] || EFFORT_CONFIG.medium;
        return (
          <div key={idx} className="flex gap-4">
            <div className="w-9 h-9 rounded-full border border-accent-500 text-accent-300 flex items-center justify-center font-heading text-sm flex-shrink-0 mt-0.5">
              {idx + 1}
            </div>

            <div className="flex-1">
              <div className="flex flex-wrap items-center gap-2 mb-1.5">
                <h3 className="font-heading text-base text-brand-textBright">{rec.title}</h3>
                <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${effort.cls}`}>
                  {effort.label}
                </span>
              </div>

              <p className="text-sm text-brand-text leading-relaxed mb-2">{rec.description}</p>

              {rec.impact && (
                <p className="text-sm text-success font-medium mb-2">↑ {rec.impact}</p>
              )}

              {rec.action_items && rec.action_items.length > 0 && (
                <ul className="flex flex-col gap-1">
                  {rec.action_items.map((item, i) => (
                    <li key={i} className="flex items-start gap-2 text-sm text-brand-muted">
                      <span className="text-accent-400 mt-0.5 flex-shrink-0">→</span>
                      {item}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
