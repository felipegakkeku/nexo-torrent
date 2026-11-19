export type ProfileType = 'turbo_max' | 'balanced' | 'quiet';
export type MediaType = 'NVMe' | 'SSD' | 'HDD' | 'Unknown';

export interface DriveInfo {
  drive: string;
  media_type: MediaType;
  disk_model: string;
  bus_type: string;
  free_gb: number;
  total_gb: number;
  free_bytes: number;
  total_bytes: number;
}

export interface NetworkInterfaceInfo {
  name: string;
  description: string;
  ip: string;
  link_speed_mbps: number;
  is_vpn: boolean;
  is_virtual?: boolean;
}

export interface HardwareInfo {
  cpu_count: number;
  ram_total_gb: number;
  drives: DriveInfo[];
  interfaces: NetworkInterfaceInfo[];
  primary_link_mbps: number;
  suggested_staging_path: string;
}

export interface AppConfig {
  profile: ProfileType;
  default_save_path: string;
  nvme_staging_enabled: boolean;
  staging_path: string;
  staging_min_free_gb: number;
  staging_min_size_gb: number;
  listen_port: number;
  random_port: boolean;
  network_interface: string;
  prefer_tcp: boolean;
  enable_utp: boolean;
  enable_dht: boolean;
  enable_lsd: boolean;
  enable_upnp: boolean;
  auto_boost_public_trackers: boolean;
  anti_stall_enabled: boolean;
  download_limit_kbps: number;
  upload_limit_kbps: number;
  max_active_downloads: number;
  max_active_seeds: number;
  preallocate_files: boolean;
  minimize_to_tray: boolean;
  client_fingerprint: string;
}

export interface TorrentSummary {
  info_hash: string;
  name: string;
  state: string;
  raw_state: string;
  paused: boolean;
  progress: number;
  total_size: number;
  downloaded: number;
  uploaded: number;
  download_rate: number;
  upload_rate: number;
  peak_download_rate: number;
  eta: number;
  num_peers: number;
  num_seeds: number;
  list_peers: number;
  list_seeds: number;
  ratio: number;
  sequential: boolean;
  prioritize_ends: boolean;
  staging_active: boolean;
  moving_storage: boolean;
  staging_note: string;
  save_path: string;
  final_save_path: string;
  dest_media_type: MediaType;
  boosted_trackers: boolean;
  is_private: boolean;
  has_metadata: boolean;
  has_incoming: boolean;
  is_finished: boolean;
  is_seeding: boolean;
  error: string;
  added_at: number;
  download_limit_kbps: number;
  upload_limit_kbps: number;
}

export interface BottleneckInfo {
  code: 'idle' | 'saturating_link' | 'disk_queue' | 'swarm_limited' | 'nat_restricted' | 'optimal';
  label: string;
  detail: string;
}

export interface GlobalStats {
  download_rate: number;
  upload_rate: number;
  dht_nodes: number;
  dht_state_loaded?: boolean;
  listen_interfaces?: string;
  max_queued_disk_mb?: number;
  peers_connected: number;
  peers_half_open: number;
  queued_write_bytes: number;
  payload_efficiency: number;
  primary_link_mbps: number;
  profile: ProfileType;
  bottleneck: BottleneckInfo;
}

export interface SpeedPoint {
  t: number;
  dl: number;
  ul: number;
}

export interface EngineState {
  torrents: TorrentSummary[];
  global: GlobalStats;
  history: SpeedPoint[];
}

export interface TorrentFileItem {
  index: number;
  path: string;
  size: number;
  done: number;
  progress: number;
  priority: number;
}

export interface PeerItem {
  endpoint: string;
  client: string;
  proto: 'TCP' | 'uTP';
  down_speed: number;
  up_speed: number;
  progress: number;
  flags: string;
  rtt: number;
}

export interface TrackerItem {
  url: string;
  tier: number;
  status: string;
  seeds: number;
  leeches: number;
}

export interface TorrentDetails {
  summary: TorrentSummary;
  files: TorrentFileItem[];
  peers: PeerItem[];
  trackers: TrackerItem[];
  piece_map: number[];
  num_pieces: number;
  piece_length: number;
}

export interface InspectTorrentResult {
  info_hash: string;
  name: string;
  total_size: number;
  num_pieces: number;
  piece_length: number;
  is_private: boolean;
  trackers: string[];
  files: Array<{ index: number; path: string; size: number }>;
}

export interface ExternalTorrentPayload {
  kind: 'magnet' | 'file';
  uri?: string;
  path?: string;
  name?: string;
  base64?: string;
}

export interface EngineConnectionInfo {
  baseUrl: string;
  wsUrl: string;
  token: string;
}

export interface NexoTorrentBridge {
  getEngineConfig: () => Promise<EngineConnectionInfo>;
  selectFolder: (defaultPath?: string) => Promise<string | null>;
  selectTorrentFile: () => Promise<{ path: string; name: string; base64: string } | null>;
  openPath: (targetPath: string) => Promise<void>;
  showInFolder: (targetPath: string) => Promise<void>;
  openExternal: (url: string) => Promise<boolean>;
  windowMinimize: () => void;
  windowMaximize: () => void;
  windowClose: () => void;
  updateTrayTooltip: (text: string) => void;
  notifyFinished: (payload: { name: string; final_save_path: string }) => void;
  registerOsHandlers: () => Promise<{ ok: boolean; message: string }>;
  unregisterOsHandlers: () => Promise<{ ok: boolean; message: string }>;
  getOsHandlersStatus: () => Promise<{ magnet: boolean; torrent: boolean }>;
  onOpenExternalTorrent: (cb: (payload: ExternalTorrentPayload) => void) => () => void;
  onTrayAction: (cb: (action: 'pause_all' | 'resume_all') => void) => () => void;
  consumePendingExternal: () => Promise<ExternalTorrentPayload[]>;
}

declare global {
  interface Window {
    nexoTorrent?: NexoTorrentBridge;
  }
}
