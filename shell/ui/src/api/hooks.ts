import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { api } from "./client"
import { toQueryString, type AnimeFilters } from "@/lib/animeFilters"
import type {
  ActiveDownload,
  AniDbStatus,
  AnimeDetail,
  AnimePendingActions,
  AnimeListResponse,
  DownloadIntegration,
  DownloadPluginsResponse,
  DownloadSearchResponse,
  DownloadSeriesHit,
  DownloadTarget,
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
  UnassignedGroup,
  WantedResponse,
  WishlistCandidate,
  WishlistItem,
} from "./types"

export type { AnimeFilters }

/** One page of the library. The previous page stays on screen while the
 * next one loads, so paging doesn't flash an empty grid. */
export function useAnimesPage(filters: AnimeFilters) {
  return useQuery({
    queryKey: ["animes", "page", filters],
    queryFn: () => api.get<AnimeListResponse>(`/api/v1/animes?${toQueryString(filters)}`),
    placeholderData: (previous) => previous,
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
    // Either way, like dismissing: the Core refuses (409) once the directory
    // isn't empty any more, and keeping the modal open over that refusal
    // would block every other decision behind it.
    onSettled: (_data, _error, entry) => {
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

/** Which episodes of the provider's list have no file, for one series. */
export function useMissingEpisodes(animeId: number | undefined) {
  return useQuery({
    queryKey: ["missing-episodes", animeId],
    queryFn: () => api.get<MissingEpisodesResponse>(`/api/v1/animes/${animeId}/missing-episodes`),
    enabled: animeId !== undefined,
  })
}

/** Every series with missing episodes, one page at a time -- on a large
 * catalog the list itself can run into the hundreds. */
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
      queryClient.invalidateQueries({ queryKey: ["unassigned-files"] })
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
 * shown, the file list, the missing episodes and the open proposals. */
function invalidateSeriesViews(queryClient: ReturnType<typeof useQueryClient>) {
  queryClient.invalidateQueries({ queryKey: ["anime"] })
  queryClient.invalidateQueries({ queryKey: ["anime-pending-actions"] })
  queryClient.invalidateQueries({ queryKey: ["local-episodes"] })
  queryClient.invalidateQueries({ queryKey: ["missing-episodes"] })
}

/** Rename/sort proposals for one series, so they can be resolved from its
 * own page too. */
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
    meta: { showsOwnError: true },
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

export function useWishlist() {
  return useQuery({
    queryKey: ["wishlist"],
    queryFn: () => api.get<WishlistItem[]>("/api/v1/wishlist"),
  })
}

/** Searches the local AniDB title dump -- no AniDB request per keystroke. */
export function useWishlistSearch(query: string) {
  const trimmed = query.trim()
  return useQuery({
    queryKey: ["wishlist-search", trimmed],
    queryFn: () =>
      api.get<WishlistCandidate[]>(`/api/v1/wishlist/search?q=${encodeURIComponent(trimmed)}`),
    enabled: trimmed.length >= 2,
    placeholderData: (previous) => previous,
  })
}

export function useAddToWishlist() {
  const queryClient = useQueryClient()
  return useMutation({
    meta: { showsOwnError: true },
    mutationFn: (anidbId: number) => api.post<WishlistItem>("/api/v1/wishlist", { anidb_id: anidbId }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["wishlist"] })
      queryClient.invalidateQueries({ queryKey: ["wishlist-search"] })
      queryClient.invalidateQueries({ queryKey: ["wishlist-shared"] })
    },
  })
}

export function useRemoveFromWishlist() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (entryId: number) => api.del<void>(`/api/v1/wishlist/${entryId}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["wishlist"] })
      queryClient.invalidateQueries({ queryKey: ["wishlist-search"] })
    },
  })
}

export function useDownloadPlugins() {
  return useQuery({
    queryKey: ["download-plugins"],
    queryFn: () => api.get<DownloadPluginsResponse>("/api/v1/downloads/plugins"),
    staleTime: Infinity, // only changes with a reload or a core restart
  })
}

/** Reads the plugins folder again (a plugin added while the app or the
 * server is running). */
export function useReloadPlugins() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => api.post<DownloadPluginsResponse>("/api/v1/downloads/plugins/reload"),
    onSuccess: (data) => {
      queryClient.setQueryData(["download-plugins"], data)
      queryClient.invalidateQueries({ queryKey: ["download-integrations"] })
    },
  })
}

export function useDownloadIntegrations() {
  return useQuery({
    queryKey: ["download-integrations"],
    queryFn: () => api.get<DownloadIntegration[]>("/api/v1/downloads/integrations"),
  })
}

type IntegrationInput = { name: string; enabled: boolean; config: Record<string, unknown> }

export function useSaveIntegration() {
  const queryClient = useQueryClient()
  return useMutation({
    meta: { showsOwnError: true },
    mutationFn: ({ id, pluginId, ...input }: IntegrationInput & { id?: number; pluginId?: string }) =>
      id === undefined
        ? api.post<DownloadIntegration>("/api/v1/downloads/integrations", { plugin_id: pluginId, ...input })
        : api.put<DownloadIntegration>(`/api/v1/downloads/integrations/${id}`, input),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["download-integrations"] }),
  })
}

export function useDeleteIntegration() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => api.del<void>(`/api/v1/downloads/integrations/${id}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["download-integrations"] }),
  })
}

export function useTestIntegration() {
  return useMutation({
    mutationFn: (id: number) =>
      api.post<{ ok: boolean; message: string }>(`/api/v1/downloads/integrations/${id}/test`),
  })
}

export function useWanted() {
  return useQuery({
    queryKey: ["downloads-wanted"],
    queryFn: () => api.get<WantedResponse>("/api/v1/downloads/wanted"),
  })
}

export function useDownloadSearch() {
  return useMutation({
    mutationFn: (target: DownloadTarget) => api.post<DownloadSearchResponse>("/api/v1/downloads/search", target),
  })
}

/** Step 2 of a two-stage source: the links on the series page the user picked. */
export function useDownloadReleases() {
  return useMutation({
    mutationFn: ({ target, series }: { target: DownloadTarget; series: DownloadSeriesHit }) =>
      api.post<DownloadSearchResponse>("/api/v1/downloads/releases", {
        ...target,
        integration_id: series.integration_id,
        series: { title: series.title, url: series.url, extra: series.extra },
      }),
  })
}

export function useSendDownload() {
  const queryClient = useQueryClient()
  return useMutation({
    meta: { showsOwnError: true },
    mutationFn: (payload: DownloadTarget & { client_id: number; link: string; folder_id?: number }) =>
      api.post<{ title: string; client_name: string; resolving: boolean }>("/api/v1/downloads/send", payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["downloads-wanted"] })
      queryClient.invalidateQueries({ queryKey: ["downloads-active"] })
    },
  })
}

/** Live progress of recently sent downloads. Polls every few seconds while
 * anything is still running, rarely otherwise. */
export function useActiveDownloads() {
  return useQuery({
    queryKey: ["downloads-active"],
    queryFn: () => api.get<ActiveDownload[]>("/api/v1/downloads/active"),
    refetchInterval: (query) =>
      query.state.data?.some((d) => ["resolving", "queued", "downloading"].includes(d.status.state)) ? 5_000 : 60_000,
  })
}

export interface ClearFinishedResult {
  hidden: number
  removed_from_clients: number
  errors: string[]
}

/** Hides every download that is done and removes the finished ones from
 * their client's list too (JDownloader, ...); the files stay. */
export function useClearFinishedDownloads() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => api.post<ClearFinishedResult>("/api/v1/downloads/requests/clear-finished"),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["downloads-active"] }),
  })
}

export function useDismissDownload() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (requestId: number) => api.post<void>(`/api/v1/downloads/requests/${requestId}/dismiss`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["downloads-active"] }),
  })
}

/** Live AniDB activity for the header. Kept current by the "anidb.activity"
 * live event; the polling is only a fallback (e.g. for the queue count). */
export function useAniDbStatus() {
  return useQuery({
    queryKey: ["anidb-status"],
    queryFn: () => api.get<AniDbStatus>("/api/v1/anidb/status"),
    refetchInterval: (query) => {
      const data = query.state.data
      return data && (data.state !== "idle" || data.queued_jobs > 0) ? 5_000 : 30_000
    },
  })
}

/** Video files that couldn't be matched to an episode, grouped by anime. */
export function useUnassignedFiles() {
  return useQuery({
    queryKey: ["unassigned-files"],
    queryFn: () => api.get<UnassignedGroup[]>("/api/v1/unassigned-files"),
  })
}

/** Re-reads all folders on file level (no AniDB lookups for known anime).
 * Runs in the background; results arrive through live events. */
export function useMediaScan() {
  return useMutation({
    mutationFn: () => api.post<{ folders: number }>("/api/v1/maintenance/media-scan"),
  })
}
