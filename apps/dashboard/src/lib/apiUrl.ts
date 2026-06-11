const RAW_BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined) || '';
const NORMALIZED_BASE = RAW_BASE.replace(/\/+$/, '');
const USE_DEV_PROXY = Boolean(import.meta.env.DEV && NORMALIZED_BASE);
const API_BASE = USE_DEV_PROXY ? '' : NORMALIZED_BASE;

export function apiUrl(path: string): string {
  if (!path) return API_BASE || '/';
  if (/^https?:\/\//i.test(path)) return path;
  const normalized = path.startsWith('/') ? path : `/${path}`;
  return `${API_BASE}${normalized}`;
}

export const API_BASE_URL = API_BASE;
