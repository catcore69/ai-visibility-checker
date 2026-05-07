'use client';

import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer, Legend } from 'recharts';

interface Props {
  positive: number;
  neutral: number;
  negative: number;
}

const COLORS = ['#34C759', '#8E8E93', '#FF3B30'];
const LABELS = ['Позитив', 'Нейтрально', 'Негатив'];

export default function SentimentPie({ positive, neutral, negative }: Props) {
  const total = positive + neutral + negative;
  if (total === 0) return null;

  const data = [
    { name: LABELS[0], value: positive  },
    { name: LABELS[1], value: neutral   },
    { name: LABELS[2], value: negative  },
  ].filter(d => d.value > 0);

  return (
    <div className="flex flex-col items-center gap-2">
      <ResponsiveContainer width="100%" height={200}>
        <PieChart>
          <Pie
            data={data}
            cx="50%"
            cy="50%"
            innerRadius={55}
            outerRadius={85}
            paddingAngle={3}
            dataKey="value"
          >
            {data.map((entry, index) => {
              const colorIndex = LABELS.indexOf(entry.name);
              return <Cell key={`cell-${index}`} fill={COLORS[colorIndex >= 0 ? colorIndex : index]} />;
            })}
          </Pie>
          <Tooltip
            formatter={(value: number) => [`${value} (${Math.round((value / total) * 100)}%)`, '']}
          />
          <Legend
            formatter={(value: string) => (
              <span style={{ fontSize: '12px', color: '#1C1C1E' }}>{value}</span>
            )}
          />
        </PieChart>
      </ResponsiveContainer>

      {/* Summary */}
      <div className="grid grid-cols-3 gap-3 w-full">
        {[
          { label: 'Позитив',    value: positive,  pct: Math.round((positive  / total) * 100), color: 'text-green-500',  bg: 'bg-green-50'  },
          { label: 'Нейтрально', value: neutral,   pct: Math.round((neutral   / total) * 100), color: 'text-gray-500',   bg: 'bg-gray-50'   },
          { label: 'Негатив',    value: negative,  pct: Math.round((negative  / total) * 100), color: 'text-red-500',    bg: 'bg-red-50'    },
        ].map(item => (
          <div key={item.label} className={`${item.bg} rounded-xl p-3 text-center`}>
            <div className={`text-xl font-black ${item.color}`}>{item.pct}%</div>
            <div className="text-xs text-gray-500 mt-0.5">{item.label}</div>
            <div className="text-xs text-gray-400">{item.value} уп.</div>
          </div>
        ))}
      </div>
    </div>
  );
}
