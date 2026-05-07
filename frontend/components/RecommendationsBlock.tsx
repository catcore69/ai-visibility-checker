'use client';

import type { Recommendation } from '@/lib/api';

interface Props {
  recommendations: Recommendation[];
}

const EFFORT_CONFIG: Record<string, { label: string; cls: string }> = {
  low:    { label: 'Быстро',   cls: 'bg-green-100 text-green-700'  },
  medium: { label: 'Средне',   cls: 'bg-yellow-100 text-yellow-700'},
  high:   { label: 'Сложно',   cls: 'bg-red-100 text-red-700'      },
};

export default function RecommendationsBlock({ recommendations }: Props) {
  return (
    <div className="flex flex-col gap-5">
      {recommendations.map((rec, idx) => {
        const effort = EFFORT_CONFIG[rec.effort] || EFFORT_CONFIG.medium;
        return (
          <div key={idx} className="flex gap-4">
            {/* Priority circle */}
            <div className="w-9 h-9 rounded-full bg-blue-600 text-white flex items-center justify-center font-black text-sm flex-shrink-0 mt-0.5">
              {idx + 1}
            </div>

            {/* Content */}
            <div className="flex-1">
              <div className="flex flex-wrap items-center gap-2 mb-1.5">
                <h3 className="font-bold text-gray-900 text-base">{rec.title}</h3>
                <span className={`text-xs px-2 py-0.5 rounded-full font-semibold ${effort.cls}`}>
                  {effort.label}
                </span>
              </div>

              <p className="text-sm text-gray-600 leading-relaxed mb-2">{rec.description}</p>

              {rec.impact && (
                <p className="text-sm text-green-600 font-medium mb-2">
                  ↑ {rec.impact}
                </p>
              )}

              {rec.action_items && rec.action_items.length > 0 && (
                <ul className="flex flex-col gap-1">
                  {rec.action_items.map((item, i) => (
                    <li key={i} className="flex items-start gap-2 text-sm text-gray-600">
                      <span className="text-blue-600 mt-0.5 flex-shrink-0">→</span>
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
