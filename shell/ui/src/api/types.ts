export type FolderType = "content" | "download"

export interface Folder {
  id: number
  path: string
  type: FolderType
  name: string
  active: boolean
  offline: boolean
}

export type IdentStatus = "pending" | "identified" | "needs_manual_id" | "review"

/** FA-12 soll/ist comparison. null when the provider lists no numbered
 * episodes for this entry (or it isn't identified yet). */
export interface Completeness {
  expected: number
  present: number
  missing: number
}

export interface AnimeListItem {
  id: number
  anidb_id: number | null
  title: string
  year: number | null
  media_type: string | null
  poster_path: string | null
  ident_status: IdentStatus
  match_score: number | null
  episode_count_expected: number | null
  is_duplicate: boolean
  duplicate_of_anime_id: number | null
  completeness: Completeness | null
}

export interface AnimeListResponse {
  total: number
  page: number
  items: AnimeListItem[]
}

export interface AnimeTag {
  name: string
  weight: number
}

export interface ReviewCandidate {
  aid: number
  title: string
  score: number
}

export interface AnimeDetail {
  id: number
  anidb_id: number | null
  title: string
  original_title: string | null
  alt_titles: string[]
  year: number | null
  media_type: string | null
  description: string | null
  poster_path: string | null
  ident_status: IdentStatus
  match_score: number | null
  episode_count_expected: number | null
  directory_path: string
  tags: AnimeTag[]
  review_candidates: ReviewCandidate[] | null
  is_duplicate: boolean
  duplicate_of_anime_id: number | null
  last_metadata_refresh: string | null
  last_episode_air_date: string | null
  is_stale: boolean
}

export interface TagSummary {
  id: number
  name: string
  description: string | null
  category: string | null
  anime_count: number
}

export interface ReviewItem {
  anime_id: number
  directory_path: string
  title_guess: string
  ident_status: IdentStatus
  candidates: ReviewCandidate[] | null
}

export interface DuplicateEntry {
  anime_id: number
  title: string
  directory_path: string
  poster_path: string | null
}

export interface DuplicateGroup {
  anidb_id: number
  title: string
  entries: DuplicateEntry[]
}

export interface WsEvent<T = unknown> {
  event: string
  data: T
}

export interface EmptyDirEntry {
  folder_id: number
  path: string
}

export interface SortQueueItem {
  anime_id: number
  title: string
  directory_path: string
  anidb_id: number
  episode_count: number
  matched_count: number
  suggested_target_folder_id: number | null
}

export interface SortResolveResult {
  moved: number
  unmatched: number
  target_anime_id: number
}

export interface RenameQueueItem {
  anime_id: number
  title: string
  current_dir_name: string
  target_dir_name: string
  mismatched_file_count: number
  total_matched_episodes: number
}

export interface RenameResolveResult {
  renamed_dir: boolean
  renamed_files: number
}

export interface PendingActionsCount {
  total: number
}

export interface MissingEpisode {
  ep_number: string
  title: string | null
  air_date: string | null
}

export interface MissingEpisodesResponse {
  anime_id: number
  expected: number
  present: number
  missing: MissingEpisode[]
}

export interface IncompleteAnime {
  anime_id: number
  title: string
  poster_path: string | null
  year: number | null
  media_type: string | null
  expected: number
  present: number
  missing: number
}

export interface MissingEpisodesOverview {
  total: number
  page: number
  items: IncompleteAnime[]
}

export interface LocalEpisodeItem {
  id: number
  file_name: string
  ep_number: string | null
  manual_override: boolean
}

export interface FileRename {
  current: string
  target: string
}

export interface RenameProposal {
  current_dir_name: string
  target_dir_name: string
  dir_needs_rename: boolean
  file_renames: FileRename[]
}

export interface SortProposal {
  episode_count: number
  matched_count: number
  suggested_target_folder_id: number | null
}

/** The Abfragen-page entries that concern one series. */
export interface AnimePendingActions {
  rename: RenameProposal | null
  sort: SortProposal | null
}

/** What a repair scan changed across the whole library. */
export interface RepairScanResult {
  checked: number
  titles_backfilled: number
  titles_changed: number
  episode_numbers_fixed: number
  metadata_filled: number
  expected_episodes_added: number
  posters_relinked: number
  without_local_source: number
}
