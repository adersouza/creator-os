export function calendarPostPath(postId: string, publishedAt?: string | null): string {
  const params = new URLSearchParams({ postId });
  if (publishedAt) {
    const date = new Date(publishedAt);
    if (Number.isFinite(date.getTime())) {
      const yyyy = date.getFullYear();
      const mm = String(date.getMonth() + 1).padStart(2, '0');
      const dd = String(date.getDate()).padStart(2, '0');
      params.set('date', `${yyyy}-${mm}-${dd}`);
    }
  }
  return `/calendar?${params.toString()}`;
}

export function accountDetailPath(accountId: string): string {
  return `/accounts?id=${encodeURIComponent(accountId)}`;
}
