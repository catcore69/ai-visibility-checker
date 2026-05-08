import FingerprintJS from '@fingerprintjs/fingerprintjs';

let fpPromise: ReturnType<typeof FingerprintJS.load> | null = null;

export async function getFingerprint(): Promise<string> {
  if (typeof window === 'undefined') return 'ssr';
  try {
    if (!fpPromise) {
      fpPromise = FingerprintJS.load();
    }
    const fp = await fpPromise;
    const result = await fp.get();
    return result.visitorId;
  } catch {
    // Fallback: basic browser fingerprint
    const ua = navigator.userAgent;
    const lang = navigator.language;
    const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
    const screen = `${window.screen.width}x${window.screen.height}`;
    const raw = `${ua}|${lang}|${tz}|${screen}`;
    // Simple hash
    let hash = 0;
    for (let i = 0; i < raw.length; i++) {
      const char = raw.charCodeAt(i);
      hash = (hash << 5) - hash + char;
      hash |= 0;
    }
    return Math.abs(hash).toString(16).padStart(8, '0');
  }
}
