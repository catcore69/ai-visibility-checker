'use client';

import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer, Legend } from 'recharts';

interface Props {
  positive: number;
  neutral: number;
  negative: number;
}

const COLORS = ['#3BA776', '#8A8F99', '#B93A3A']; // success / muted / danger
const LABELS = ['Позитив', 'Нейтрально', 'Негатив'];

export default function SentimentPie({ positive, neutral, negative }: Props) {
  const total = positive + neutral + negative;
  if (total === 0) return null;

  const data = [
    { name: LABELS[0], value: positive },
    { name: LABELS[1], value: neutral },
    { name: LABELS[2], value: negative },
  ].filter((d) => d.value > 0);

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
              const ci = LABELS.indexOf(entry.name);
              return <Cell key={`cell-${index}`} fill={COLORS[ci >= 0 ? ci : index]} />;
            })}
          </Pie>
          <Tooltip
            contentStyle={{
              background: '#1B1D22',
              border: '1px solid #2F333B',
              borderRadius: 12,
              color: '#E6E8EC',
            }}
            formatter={(value: number) => [
              `${value} (${Math.round((value / total) * 100)}%)`,
              '',
            ]}
          />
          <Legend
            formatter={(value: string) => (
              <span style={{ fontSize: '12px', color: '#E6E8EC' }}>{value}</span>
            )}
          />
        </PieChart>
      </ResponsiveContainer>

      <div className="grid grid-cols-3 gap-3 w-full">
        {[
          { label: 'Позитив',    value: positive, pct: Math.round((positive / total) * 100), color: 'text-success' },
          { label: 'Нейтрально', value: neutral,  pct: Math.round((neutral  / total) * 100), color: 'text-brand-text' },
          { label: 'Негатив',    value: negative, pct: Math.round((negative / total) * 100), color: 'text-danger'  },
        ].map((item) => (
          <div key={item.label} className="card-surface p-3 text-center">
            <div className={`text-xl font-heading ${item.color}`}>{item.pct}%</div>
            <div className="text-xs text-brand-muted mt-0.5">{item.label}</div>
            <div className="text-xs text-brand-muted">{item.value} уп.</div>
          </div>
        ))}
      </div>
    </div>
  );
}
