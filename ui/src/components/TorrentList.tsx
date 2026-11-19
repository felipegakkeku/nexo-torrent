import {
  FolderOpen,
  HardDrive,
  Pause,
  Play,
  RefreshCw,
  Search,
  Trash2,
  Zap,
} from 'lucide-react';
import { formatBytes, formatEta, formatSpeed } from '../format';
import type { TorrentSummary } from '../types';

export type FilterKey = 'all' | 'downloading' | 'seeding' | 'paused' | 'finished';

interface TorrentListProps {
  torrents: TorrentSummary[];
  selectedHash: string | null;
  filter: FilterKey;
  search: string;
  onFilterChange: (f: FilterKey) => void;
  onSearchChange: (s: string) => void;
  onSelect: (hash: string) => void;
  onPause: (hash: string) => void;
  onResume: (hash: string) => void;
  onPauseAll: () => void;
  onResumeAll: () => void;
  onReannounce: (hash: string) => void;
  onRemoveRequest: (torrent: TorrentSummary) => void;
  onOpenFolder: (torrent: TorrentSummary) => void;
}

const FILTER_LABELS: Array<{ key: FilterKey; label: string }> = [
  { key: 'all', label: 'Todos' },
  { key: 'downloading', label: 'Baixando' },
  { key: 'seeding', label: 'Semeando' },
  { key: 'paused', label: 'Pausados' },
  { key: 'finished', label: 'Concluídos' },
];

export function TorrentList({
  torrents,
  selectedHash,
  filter,
  search,
  onFilterChange,
  onSearchChange,
  onSelect,
  onPause,
  onResume,
  onPauseAll,
  onResumeAll,
  onReannounce,
  onRemoveRequest,
  onOpenFolder,
}: TorrentListProps) {
  const q = search.trim().toLowerCase();

  const filtered = torrents.filter((t) => {
    if (q && !t.name.toLowerCase().includes(q) && !t.info_hash.includes(q)) {
      return false;
    }
    if (filter === 'downloading') return !t.paused && !t.is_finished;
    if (filter === 'seeding') return !t.paused && t.is_seeding;
    if (filter === 'paused') return t.paused;
    if (filter === 'finished') return t.is_finished;
    return true;
  });

  return (
    <section className="list-card">
      <div className="list-toolbar">
        <div className="filter-tabs">
          {FILTER_LABELS.map((item) => (
            <button
              key={item.key}
              className={`filter-tab ${filter === item.key ? 'active' : ''}`}
              onClick={() => onFilterChange(item.key)}
            >
              {item.label}
            </button>
          ))}
        </div>

        <div className="toolbar-right">
          <div className="search-box">
            <Search size={14} />
            <input
              type="text"
              placeholder="Filtrar torrents..."
              value={search}
              onChange={(e) => onSearchChange(e.target.value)}
            />
          </div>

          <button className="btn btn-sm" onClick={onResumeAll} title="Retomar todos os torrents">
            <Play size={13} />
            <span>Retomar todos</span>
          </button>

          <button className="btn btn-sm" onClick={onPauseAll} title="Pausar todos os torrents">
            <Pause size={13} />
            <span>Pausar todos</span>
          </button>
        </div>
      </div>

      <div className="torrent-rows">
        {filtered.length === 0 ? (
          <div className="empty-state">
            <Zap size={28} style={{ color: 'var(--cyan)', opacity: 0.7 }} />
            <div style={{ fontWeight: 600, color: 'var(--text)' }}>
              Nenhum torrent nesta visualização
            </div>
            <div style={{ fontSize: 12 }}>
              Arraste um arquivo .torrent para esta janela, cole um link magnet com Ctrl+V ou use os botões no topo.
            </div>
          </div>
        ) : (
          filtered.map((t) => {
            const isSelected = selectedHash === t.info_hash;
            const fillClass = t.paused ? 'paused' : t.is_finished ? 'done' : '';
            return (
              <div
                key={t.info_hash}
                className={`torrent-row ${isSelected ? 'selected' : ''}`}
                onClick={() => onSelect(t.info_hash)}
              >
                <div className="torrent-title-col">
                  <div className="torrent-name-line">
                    <span className="torrent-name" title={t.name}>
                      {t.name}
                    </span>
                    {t.staging_active && (
                      <span className="badge badge-nvme" title={t.staging_note}>
                        <Zap size={10} /> NVMe Turbo
                      </span>
                    )}
                    {t.sequential && <span className="badge badge-seq">Seq</span>}
                    {t.is_private && <span className="badge badge-priv">Privado</span>}
                    {t.error && (
                      <span className="badge badge-err" title={t.error}>
                        Erro
                      </span>
                    )}
                  </div>
                  <div className="torrent-subline tabular">
                    <span>{t.state}</span>
                    <span>•</span>
                    <span>
                      <HardDrive size={11} style={{ verticalAlign: 'middle', marginRight: 3 }} />
                      {t.dest_media_type}
                    </span>
                    {t.peak_download_rate > 0 && (
                      <>
                        <span>•</span>
                        <span>Pico: {formatSpeed(t.peak_download_rate)}</span>
                      </>
                    )}
                  </div>
                </div>

                <div className="progress-cell tabular">
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11.5 }}>
                    <span>{t.progress.toFixed(1)}%</span>
                    <span style={{ color: 'var(--text-dim)' }}>{formatBytes(t.total_size)}</span>
                  </div>
                  <div className="progress-track">
                    <div
                      className={`progress-fill ${fillClass}`}
                      style={{ width: `${Math.min(100, Math.max(0, t.progress))}%` }}
                    />
                  </div>
                </div>

                <div className="tabular" style={{ color: 'var(--cyan)', fontWeight: 600 }}>
                  ↓ {formatSpeed(t.download_rate)}
                </div>

                <div className="tabular" style={{ color: 'var(--violet)' }}>
                  ↑ {formatSpeed(t.upload_rate)}
                </div>

                <div className="tabular" style={{ color: 'var(--text-dim)' }}>
                  {t.is_finished ? 'Concluído' : formatEta(t.eta)}
                </div>

                <div className="tabular" style={{ color: 'var(--text-dim)', fontSize: 12 }}>
                  {t.num_seeds}S / {t.num_peers}P
                </div>

                <div className="row-actions" onClick={(e) => e.stopPropagation()}>
                  {t.paused ? (
                    <button
                      className="btn-icon"
                      onClick={() => onResume(t.info_hash)}
                      title="Retomar"
                    >
                      <Play size={14} />
                    </button>
                  ) : (
                    <button
                      className="btn-icon"
                      onClick={() => onPause(t.info_hash)}
                      title="Pausar"
                    >
                      <Pause size={14} />
                    </button>
                  )}
                  <button
                    className="btn-icon"
                    onClick={() => onReannounce(t.info_hash)}
                    title="Forçar reanúncio de trackers e DHT"
                  >
                    <RefreshCw size={14} />
                  </button>
                  <button
                    className="btn-icon"
                    onClick={() => onOpenFolder(t)}
                    title="Abrir pasta de destino"
                  >
                    <FolderOpen size={14} />
                  </button>
                  <button
                    className="btn-icon"
                    onClick={() => onRemoveRequest(t)}
                    title="Remover torrent"
                    style={{ color: 'var(--red)' }}
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
              </div>
            );
          })
        )}
      </div>
    </section>
  );
}
