import type {
  AppConfig,
  EngineConnectionInfo,
  EngineState,
  HardwareInfo,
  InspectTorrentResult,
  TorrentDetails,
  TorrentSummary,
} from './types';

let connInfo: EngineConnectionInfo = {
  baseUrl: 'http://127.0.0.1:19742',
  wsUrl: 'ws://127.0.0.1:19742/ws',
  token: '',
};

export function setEngineConnection(info: EngineConnectionInfo): void {
  connInfo = info;
}

export function getEngineConnection(): EngineConnectionInfo {
  return connInfo;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (connInfo.token) {
    headers.set('X-Nexo-Token', connInfo.token);
  }
  const resp = await fetch(`${connInfo.baseUrl}${path}`, { ...init, headers });
  if (!resp.ok) {
    let msg = `Erro HTTP ${resp.status}`;
    try {
      const data = await resp.json();
      if (data?.detail) msg = String(data.detail);
    } catch {
      // ignora erro de parse
    }
    throw new Error(msg);
  }
  return (await resp.json()) as T;
}

export const api = {
  getState: () => request<EngineState>('/api/state'),
  getHardware: () => request<HardwareInfo>('/api/system/hardware'),
  checkStaging: (save_path: string, total_size: number) =>
    request<{ use_staging: boolean; reason: string }>('/api/system/staging-check', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ save_path, total_size }),
    }),
  getConfig: () => request<AppConfig>('/api/config'),
  saveConfig: (cfg: AppConfig) =>
    request<AppConfig>('/api/config', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(cfg),
    }),
  inspectTorrent: (file: File) => {
    const fd = new FormData();
    fd.append('file', file);
    return request<InspectTorrentResult>('/api/torrents/inspect', {
      method: 'POST',
      body: fd,
    });
  },
  addMagnet: (payload: {
    uri: string;
    save_path?: string;
    use_staging?: boolean | null;
    sequential?: boolean;
    prioritize_ends?: boolean;
    start_paused?: boolean;
    boost_trackers?: boolean | null;
  }) =>
    request<TorrentSummary>('/api/torrents/magnet', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),
  addTorrentFile: (params: {
    file: File;
    save_path?: string;
    use_staging?: boolean | null;
    sequential?: boolean;
    prioritize_ends?: boolean;
    start_paused?: boolean;
    boost_trackers?: boolean | null;
    file_priorities?: number[];
  }) => {
    const fd = new FormData();
    fd.append('file', params.file);
    if (params.save_path) fd.append('save_path', params.save_path);
    if (params.use_staging !== undefined && params.use_staging !== null) {
      fd.append('use_staging', String(params.use_staging));
    }
    fd.append('sequential', String(Boolean(params.sequential)));
    fd.append('prioritize_ends', String(Boolean(params.prioritize_ends)));
    fd.append('start_paused', String(Boolean(params.start_paused)));
    if (params.boost_trackers !== undefined && params.boost_trackers !== null) {
      fd.append('boost_trackers', String(params.boost_trackers));
    }
    if (params.file_priorities) {
      fd.append('file_priorities', JSON.stringify(params.file_priorities));
    }
    return request<TorrentSummary>('/api/torrents/file', {
      method: 'POST',
      body: fd,
    });
  },
  pause: (hash: string) => request<{ ok: boolean }>(`/api/torrents/${hash}/pause`, { method: 'POST' }),
  resume: (hash: string) => request<{ ok: boolean }>(`/api/torrents/${hash}/resume`, { method: 'POST' }),
  pauseAll: () => request<{ count: number }>('/api/torrents/pause-all', { method: 'POST' }),
  resumeAll: () => request<{ count: number }>('/api/torrents/resume-all', { method: 'POST' }),
  recheck: (hash: string) => request<{ ok: boolean }>(`/api/torrents/${hash}/recheck`, { method: 'POST' }),
  reannounce: (hash: string) => request<{ ok: boolean }>(`/api/torrents/${hash}/reannounce`, { method: 'POST' }),
  boostTrackers: (hash: string) =>
    request<{ ok: boolean; added: number; reason: string }>(`/api/torrents/${hash}/boost-trackers`, {
      method: 'POST',
    }),
  updateOptions: (
    hash: string,
    opts: {
      sequential?: boolean;
      prioritize_ends?: boolean;
      download_limit_kbps?: number;
      upload_limit_kbps?: number;
    }
  ) =>
    request<{ ok: boolean }>(`/api/torrents/${hash}/options`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(opts),
    }),
  updateFilePriorities: (hash: string, priorities: number[]) =>
    request<{ ok: boolean }>(`/api/torrents/${hash}/files`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ priorities }),
    }),
  remove: (hash: string, deleteFiles: boolean) =>
    request<{ ok: boolean }>(`/api/torrents/${hash}?delete_files=${deleteFiles ? 'true' : 'false'}`, {
      method: 'DELETE',
    }),
  getDetails: (hash: string) => request<TorrentDetails>(`/api/torrents/${hash}/details`),
};
