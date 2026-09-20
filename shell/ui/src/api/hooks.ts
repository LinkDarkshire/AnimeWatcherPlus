import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { api } from "./client"
import { toQueryString, type AnimeFilters } from "@/lib/animeFilters"
import type {
  AnimeDetail,
  AnimePendingActions,
  AnimeListResponse,
  DuplicateGroup,
  EmptyDirEntry,
  Folder,
  LocalEpisodeItem,
  MissingEpisodesOverview,
  MissingEpisodesResponse,
  PendingActionsCount,
  RenameQueueItem,
  RepairScanResult,
  RenameResolveResult,
  ReviewItem,
  SortQueueItem,
  SortResolveResult,
  TagSummary,
} from "./types"

export type { AnimeFilters }

/** One page of anime per fetch, appended as the grid scrolls (FA: the library
 * can hold thousands of entries -- a single request for all of them would
 * transfer the whole catalog on every filter change and still only render a
 * virtualized window of it).
 *
 * Loaded pages stay in the query cache under the same key, which is also what
 * makes the Library's scroll restoration work after visiting an anime: coming
 * back re-renders the full set of pages the user had scrolled through, not
 * just the first one.
 */
export function useAnimesInfinite(filters: Omit<AnimeFilters, "page">) {
  return useInfiniteQuery({
    queryKey: ["animes", "infinite", filters],
    initialPageParam: 1,
    queryFn: ({ pageParam }) =>
      api.get<AnimeListResponse>(`/api/v1/animes?${toQueryString({ ...filters, page: pageParam })}`),
    getNextPageParam: (lastPage, allPages) => {
      const loaded = allPages.reduce((sum, page) => sum + page.items.length, 0)
      return loaded < lastPage.total ? allPages.length + 1 : undefined
    },
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
      queryClient.invalidateQueries({ queryKey: ["duplicates"] })
      queryClient.invalidateQueries({ queryKey: ["pending-actions-count"] })
      queryClient.invalidateQueries({ queryKey: ["anime", variables.animeId] })
    },
  })
}

export function useDuplicates() {
  return useQuery({
    queryKey: ["duplicates"],
    queryFn: () => api.get<DuplicateGroup[]>("/api/v1/duplicates"),
  })
}

export function useDeleteAnime() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (animeId: number) => api.del<void>(`/api/v1/animes/${animeId}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["duplicates"] })
      queryClient.invalidateQueries({ queryKey: ["animes"] })
      queryClient.invalidateQueries({ queryKey: ["review-queue"] })
      queryClient.invalidateQueries({ queryKey: ["pending-actions-count"] })
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
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["settings"] })
      // A changed title-preference order rewrites stored display names and
      // can make folder names newly mismatched, so the library and the
      // rename queue both go stale on any settings save.
      queryClient.invalidateQueries({ queryKey: ["animes"] })
      queryClient.invalidateQueries({ queryKey: ["anime"] })
      queryClient.invalidateQueries({ queryKey: ["rename-queue"] })
      queryClient.invalidateQueries({ queryKey: ["anime-pending-actions"] })
      queryClient.invalidateQueries({ queryKey: ["pending-actions-count"] })
    },
  })
}

export function useRescanAll() {
  return useMutation({
    mutationFn: () => api.post<{ queued: number }>("/api/v1/animes/rescan-all"),
  })
}

/** Pure client-side cache, populated by useLiveEvents on "folder.empty_dir_found"
 * -- never fetched from the server, just a TanStack-Query-cache-as-store for
 * the queue the EmptyFolderPrompt dialog works through. */
export function usePendingEmptyDirs() {
  return useQuery<EmptyDirEntry[]>({
    queryKey: ["pending-empty-dirs"],
    queryFn: () => [],
    initialData: [],
    staleTime: Infinity,
  })
}

export function useDeleteEmptyDir() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (entry: EmptyDirEntry) =>
      api.post<void>(`/api/v1/folders/${entry.folder_id}/delete-empty-dir`, { path: entry.path }),
    onSuccess: (_data, entry) => {
      queryClient.setQueryData<EmptyDirEntry[]>(["pending-empty-dirs"], (old = []) =>
        old.filter((e) => e.path !== entry.path)
      )
    },
  })
}

export function useSortQueue() {
  return useQuery({
    queryKey: ["sort-queue"],
    queryFn: () => api.get<SortQueueItem[]>("/api/v1/sort-queue"),
  })
}

export function useResolveSort() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ animeId, targetFolderId }: { animeId: number; targetFolderId: number }) =>
      api.post<SortResolveResult>(`/api/v1/sort-queue/${animeId}/resolve`, { target_folder_id: targetFolderId }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["sort-queue"] })
      queryClient.invalidateQueries({ queryKey: ["animes"] })
      queryClient.invalidateQueries({ queryKey: ["folders"] })
      queryClient.invalidateQueries({ queryKey: ["review-queue"] })
      queryClient.invalidateQueries({ queryKey: ["pending-actions-count"] })
      queryClient.invalidateQueries({ queryKey: ["rename-queue"] })
      invalidateSeriesViews(queryClient)
    },
  })
}

/** "Keep" is remembered by the Core: an empty directory has no Anime row to
 * hang the decision on, so a purely client-side dismissal brought the prompt
 * back on the next scan. */
export function useDismissEmptyDir() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (entry: EmptyDirEntry) =>
      api.post<void>(`/api/v1/folders/${entry.folder_id}/keep-empty-dir`, { path: entry.path }),
    onSettled: (_data, _error, entry) => {
      // Take it out of the queue either way: a failed write only means the
      // prompt returns on the next scan, and keeping the modal open would
      // block every other decision behind it.
      queryClient.setQueryData<EmptyDirEntry[]>(["pending-empty-dirs"], (old = []) =>
        old.filter((e) => e.path !== entry.path)
      )
    },
  })
}

export function useRenameQueue() {
  return useQuery({
    queryKey: ["rename-queue"],
    queryFn: () => api.get<RenameQueueItem[]>("/api/v1/rename-queue"),
  })
}

export function useResolveRename() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (animeId: number) =>
      api.post<RenameResolveResult>(`/api/v1/rename-queue/${animeId}/resolve`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["rename-queue"] })
      queryClient.invalidateQueries({ queryKey: ["animes"] })
      queryClient.invalidateQueries({ queryKey: ["pending-actions-count"] })
      invalidateSeriesViews(queryClient)
    },
  })
}

/** FA-12 per series: which episodes of the provider's list have no file. */
export function useMissingEpisodes(animeId: number | undefined) {
  return useQuery({
    queryKey: ["missing-episodes", animeId],
    queryFn: () => api.get<MissingEpisodesResponse>(`/api/v1/animes/${animeId}/missing-episodes`),
    enabled: animeId !== undefined,
  })
}

/** FA-12 global view, paginated the same way the library is -- an incomplete
 * list can itself run into the hundreds on a large catalog. */
export function useMissingEpisodesOverview(page: number, size = 50) {
  return useQuery({
    queryKey: ["missing-episodes-overview", page, size],
    queryFn: () =>
      api.get<MissingEpisodesOverview>(`/api/v1/missing-episodes?page=${page}&size=${size}`),
    placeholderData: (previous) => previous,
  })
}

export function useLocalEpisodes(animeId: number | undefined) {
  return useQuery({
    queryKey: ["local-episodes", animeId],
    queryFn: () => api.get<LocalEpisodeItem[]>(`/api/v1/animes/${animeId}/episodes`),
    enabled: animeId !== undefined,
  })
}

/** Manual episode-number correction; sets manual_override so the next scan
 * doesn't re-parse the filename over it. */
export function useUpdateEpisodeNumber() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({
      animeId,
      episodeId,
      epNumber,
    }: {
      animeId: number
      episodeId: number
      epNumber: string | null
    }) =>
      api.patch<LocalEpisodeItem>(`/api/v1/animes/${animeId}/episodes/${episodeId}`, {
        ep_number: epNumber,
      }),
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({ queryKey: ["local-episodes", variables.animeId] })
      queryClient.invalidateQueries({ queryKey: ["missing-episodes", variables.animeId] })
      queryClient.invalidateQueries({ queryKey: ["missing-episodes-overview"] })
      queryClient.invalidateQueries({ queryKey: ["animes"] })
      queryClient.invalidateQueries({ queryKey: ["rename-queue"] })
      queryClient.invalidateQueries({ queryKey: ["pending-actions-count"] })
    },
  })
}

export function usePendingActionsCount() {
  return useQuery({
    queryKey: ["pending-actions-count"],
    queryFn: () => api.get<PendingActionsCount>("/api/v1/pending-actions/count"),
    // The badge sits in the nav on every route, and the rename part of this
    // count still costs a pass over the library. A stale window keeps a burst
    // of invalidations during a scan from turning into a burst of requests;
    // useLiveEvents already coalesces the invalidations themselves.
    staleTime: 10_000,
  })
}

/** Everything on the series page that a sort or rename changes: the paths
 * shown, the file list, the soll/ist comparison and the open requests. */
function invalidateSeriesViews(queryClient: ReturnType<typeof useQueryClient>) {
  queryClient.invalidateQueries({ queryKey: ["anime"] })
  queryClient.invalidateQueries({ queryKey: ["anime-pending-actions"] })
  queryClient.invalidateQueries({ queryKey: ["local-episodes"] })
  queryClient.invalidateQueries({ queryKey: ["missing-episodes"] })
}

/** Rename/sort proposals for one series, so they can be resolved from the
 * series page instead of only from the Abfragen list. */
export function useAnimePendingActions(animeId: number | undefined) {
  return useQuery({
    queryKey: ["anime-pending-actions", animeId],
    queryFn: () => api.get<AnimePendingActions>(`/api/v1/animes/${animeId}/pending-actions`),
    enabled: animeId !== undefined,
  })
}

/** Re-derives everything the Core can work out from local data, for every
 * series including the ones the staleness rule freezes out of rescans.
 * Touches no network, so it is safe to run at any time. */
export function useRepairScan() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => api.post<RepairScanResult>("/api/v1/maintenance/repair-scan"),
    // It can touch titles, episode numbers, artwork and expected episodes at
    // once -- cheaper to refetch everything than to enumerate the effects.
    onSuccess: () => invalidateServerQueries(queryClient),
  })
}

/** `pending-empty-dirs` is a client-side store fed by live events; its
 * queryFn returns an empty list, so a blanket `invalidateQueries()` would
 * refetch it and silently discard the prompts waiting there. Everything that
 * wants "refresh all server data" goes through this instead. */
export function invalidateServerQueries(
  queryClient: ReturnType<typeof useQueryClient>,
  onlyFailed = false,
) {
  queryClient.invalidateQueries({
    predicate: (query) =>
      query.queryKey[0] !== "pending-empty-dirs" &&
      (!onlyFailed || query.state.status === "error"),
  })
}
