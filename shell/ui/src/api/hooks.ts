import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { api } from "./client"
import { toQueryString, type AnimeFilters } from "@/lib/animeFilters"
import type {
  AnimeDetail,
  AnimeListResponse,
  Folder,
  ReviewItem,
  TagSummary,
} from "./types"

export type { AnimeFilters }

export function useAnimes(filters: AnimeFilters) {
  return useQuery({
    queryKey: ["animes", filters],
    queryFn: () => api.get<AnimeListResponse>(`/api/v1/animes?${toQueryString(filters)}`),
  })
}

export function useAnime(animeId: number | undefined) {
  return useQuery({
    queryKey: ["anime", animeId],
    queryFn: () => api.get<AnimeDetail>(`/api/v1/animes/${animeId}`),
    enabled: animeId !== undefined,
  })
}

export function useTags() {
  return useQuery({
    queryKey: ["tags"],
    queryFn: () => api.get<TagSummary[]>("/api/v1/tags"),
  })
}

export function useFolders() {
  return useQuery({
    queryKey: ["folders"],
    queryFn: () => api.get<Folder[]>("/api/v1/folders"),
  })
}

export function useSettings() {
  return useQuery({
    queryKey: ["settings"],
    queryFn: () => api.get<{ values: Record<string, unknown> }>("/api/v1/settings"),
    // The AniDB-ban banner depends on this; poll so it clears itself once
    // the cooldown expires without needing a manual refresh.
    refetchInterval: 60_000,
  })
}

export function useCreateFolder() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: { path: string; type: string; name?: string }) =>
      api.post<Folder>("/api/v1/folders", payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["folders"] })
      queryClient.invalidateQueries({ queryKey: ["animes"] })
    },
  })
}

export function useDeleteFolder() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (folderId: number) => api.del<void>(`/api/v1/folders/${folderId}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["folders"] }),
  })
}

export function useRescanFolder() {
  return useMutation({
    mutationFn: (folderId: number) => api.post(`/api/v1/folders/${folderId}/rescan`),
  })
}

export function useReviewQueue() {
  return useQuery({
    queryKey: ["review-queue"],
    queryFn: () => api.get<ReviewItem[]>("/api/v1/review-queue"),
  })
}

export function useIdentifyAnime() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ animeId, anidbId }: { animeId: number; anidbId: number }) =>
      api.post<AnimeDetail>(`/api/v1/animes/${animeId}/identify`, { anidb_id: anidbId }),
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({ queryKey: ["animes"] })
      queryClient.invalidateQueries({ queryKey: ["review-queue"] })
      queryClient.invalidateQueries({ queryKey: ["anime", variables.animeId] })
    },
  })
}

export function useRefreshMetadata() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (animeId: number) => api.post<AnimeDetail>(`/api/v1/animes/${animeId}/refresh-metadata`),
    onSuccess: (_data, animeId) => {
      queryClient.invalidateQueries({ queryKey: ["animes"] })
      queryClient.invalidateQueries({ queryKey: ["anime", animeId] })
    },
  })
}

export function useUpdateSettings() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (values: Record<string, unknown>) =>
      api.put<{ values: Record<string, unknown> }>("/api/v1/settings", { values }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["settings"] }),
  })
}

export function useRescanAll() {
  return useMutation({
    mutationFn: () => api.post<{ queued: number }>("/api/v1/animes/rescan-all"),
  })
}
