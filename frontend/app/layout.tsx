import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'AI Visibility Checker — проверьте видимость вашего бренда в ИИ',
  description:
    'Бесплатный инструмент: узнайте, как часто ИИ-ассистенты (ChatGPT, YandexGPT, GigaChat, Gemini и другие) упоминают ваш бренд по сравнению с конкурентами.',
  openGraph: {
    title: 'AI Visibility Checker',
    description: 'Проверьте, как ИИ-ассистенты видят ваш бренд',
    type: 'website',
  },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ru">
      <head>
        {/* Cloudflare Turnstile */}
        <script
          src="https://challenges.cloudflare.com/turnstile/v0/api.js"
          async
          defer
        />
      </head>
      <body>{children}</body>
    </html>
  );
}
