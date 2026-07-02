export function getErrorMessage(err: unknown, fallback: string): string {
  const detail = (err as any)?.response?.data?.detail
  if (typeof detail === 'string' && detail) return detail
  if (Array.isArray(detail)) {
    // FastAPI 422 validation errors
    return detail.map((d: any) => d?.msg ?? JSON.stringify(d)).join('; ')
  }
  const msg = (err as any)?.message
  return typeof msg === 'string' && msg ? msg : fallback
}
