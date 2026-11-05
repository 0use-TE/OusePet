export type Species = "cat" | "hedgehog";
export type Settings = {
  gpu_enabled: boolean;
  device: string;
  gpu_name: string | null;
  switching: boolean;
};
export type Pet = {
  video_count?: number;
  id: string;
  name: string;
  species: Species;
  cover: string | null;
  count: number;
  unnamed?: boolean;
};
export type Photo = {
  media_type?: "image" | "video";
  duration?: number;
  manual?: boolean;
  video_error?: string | null;
  video_hits?: { pet_id: string; name: string; seconds: number; last_seconds: number; frames: number }[];
  id: string;
  name: string;
  path: string;
  width: number;
  height: number;
  taken_at: string;
  species: Species[];
  favorite: boolean;
  visible: boolean;
  thumb: string;
  url: string;
  pets: (Pet & { status: string })[];
};
export type Album = {
  video_count?: number;
  id: string;
  name: string;
  count: number;
  cover: string | null;
};
export type Storage = {
  id: string;
  name: string;
  path: string;
  count: number;
  indexed: number;
  last_scan: string | null;
  auto_scan: boolean | number;
};
export type Job = {
  current_file?: string;
  id: string;
  storage_id: string;
  storage_name: string;
  status: string;
  total: number;
  processed: number;
  found: number;
  error: string | null;
};
export type State = {
  counts: {
    videos?: number;
    library: number;
    all: number;
    cats: number;
    hedgehogs: number;
    favorites: number;
    review: number;
  };
  pets: Pet[];
  albums: Album[];
  storages: Storage[];
  jobs: Job[];
  discovery?: { status: string; total: number; processed: number; errors: number; error: string | null; phase?: string };
  reset_task?: { status: string; error?: string; job_ids?: string[] };
};
export type Browse = {
  path: string;
  storage: Storage;
  directories: { name: string; path: string }[];
  photos: Photo[];
};
export class ApiError extends Error {
  constructor(public status: number, public detail: unknown, message: string) {
    super(message);
  }
}
export async function api<T>(
  path: string,
  body?: unknown,
  method = "POST",
): Promise<T> {
  const response = await fetch(
    "/api" + path,
    body === undefined
      ? undefined
      : {
          method,
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        },
  );
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new ApiError(response.status, data.detail,
      typeof data.detail === "string" ? data.detail : data.detail?.message || "操作未完成，请重试",
    );
  }
  return response.json();
}
