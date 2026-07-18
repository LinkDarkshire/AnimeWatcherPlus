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
  missing_on_disk: boolean
  is_duplicate: boolean
  duplicate_of_anime_id: number | null
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

export interface WsEvent<T = unknown> {
  event: string
  data: T
}
