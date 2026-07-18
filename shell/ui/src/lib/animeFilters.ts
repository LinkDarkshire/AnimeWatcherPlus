export interface AnimeFilters {
  query?: string
  tag?: string
  year?: number
  type?: string
  status?: string
  page?: number
  size?: number
}

export function toQueryString(filters: AnimeFilters): string {
  const params = new URLSearchParams()
  if (filters.query) params.set("query", filters.query)
  if (filters.tag) params.set("tag", filters.tag)
  if (filters.year) params.set("year", String(filters.year))
  if (filters.type) params.set("type", filters.type)
  if (filters.status) params.set("status", filters.status)
  params.set("page", String(filters.page ?? 1))
  params.set("size", String(filters.size ?? 60))
  return params.toString()
}
