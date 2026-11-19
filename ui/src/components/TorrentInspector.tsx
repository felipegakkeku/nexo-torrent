import { useEffect, useRef, useState } from 'react';
import {
  Activity,
  Cpu,
  FileText,
  Layers,
  Radio,
  RefreshCw,
  Users,
  Zap,
} from 'lucide-react';
import { formatBytes, formatEta, formatSpeed } from '../format';
import type { GlobalStats, TorrentDetails, TorrentSummary } from '../types';

type InspectorTab = 'general' | 'files' | 'peers' | 'trackers' | 'telemetry';

interface TorrentInspectorProps {
  torrent: TorrentSummary | null;
  details: TorrentDetails | null;
  globalStats: GlobalStats;
  onToggleSequential: (hash: string, val: boolean) => void;
  onTogglePrioritizeEnds: (hash: string, val: boolean) => void;
  onUpdateFilePriorities: (hash: string, priorities: number[]) => void;
  onBoostTrackers: (hash: string) => void;
  onRecheck: (hash: string) => void;
}

const PRIO_LABELS: Array<{ value: number; label: string }> = [
  { value: 0, label: 'Ignorar' },
  { value: 4, label: 'Normal' },
  { value: 6, label: 'Alta' },
  { value: 7, label: 'Máxima' },
];

export function TorrentInspector({
  torrent,
  details,
  globalStats,
  onToggleSequential,
  onTogglePrioritizeEnds,
  onUpdateFilePriorities,
  onBoostTrackers,
  onRecheck,
}: TorrentInspectorProps) {
  const [tab, setTab] = useState<InspectorTab>('general');
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || tab !== 'general') return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    const w = Math.max(200, Math.floor(rect.width));
    const h = 24;
    canvas.width = w * dpr;
    canvas.height = h * dpr;
    ctx.scale(dpr, dpr);

    ctx.fillStyle = '#0D1119';
    ctx.fillRect(0, 0, w, h);

    const map = details?.piece_map ?? [];
    if (map.length === 0) {
      ctx.fillStyle = '#1F2636';
      ctx.fillRect(0, 0, w, h);
      return;
    }

    const cellW = w / map.length;
    for (let i = 0; i < map.length; i += 1) {
      const state = map[i];
      if (state === 2) ctx.fillStyle = '#22D3EE';
      else if (state === 1) ctx.fillStyle = '#FBBF24';
      else ctx.fillStyle = '#1A2233';
      const x = Math.floor(i * cellW);
      const cw = Math.max(1, Math.ceil(cellW) - (cellW > 3 ? 1 : 0));
      ctx.fillRect(x, 2, cw, h - 4);
    }
  }, [details?.piece_map, tab]);

  if (!torrent) {
    return (
      <section className="inspector-card">
        <div className="inspector-tabs">
          <div className="tab-list">
            <span className="inspector-tab active">
              <Layers size={13} /> Inspetor
            </span>
          </div>
        </div>
        <div className="empty-state" style={{ padding: 12 }}>
          <span style={{ fontSize: 12 }}>
            Selecione um torrent na lista acima para visualizar mapa de peças, arquivos, peers, trackers e telemetria.
          </span>
        </div>
      </section>
    );
  }

  const handleFileCheck = (idx: number, checked: boolean) => {
    if (!details) return;
    const next = details.files.map((f) => (f.index === idx ? (checked ? 4 : 0) : f.priority));
    onUpdateFilePriorities(torrent.info_hash, next);
  };

  const handleFilePrio = (idx: number, prio: number) => {
    if (!details) return;
    const next = details.files.map((f) => (f.index === idx ? prio : f.priority));
    onUpdateFilePriorities(torrent.info_hash, next);
  };

  return (
    <section className="inspector-card">
      <div className="inspector-tabs">
        <div className="tab-list">
          <button
            className={`inspector-tab ${tab === 'general' ? 'active' : ''}`}
            onClick={() => setTab('general')}
          >
            <Layers size={13} /> Geral
          </button>
          <button
            className={`inspector-tab ${tab === 'files' ? 'active' : ''}`}
            onClick={() => setTab('files')}
          >
            <FileText size={13} /> Arquivos ({details?.files.length ?? 0})
          </button>
          <button
            className={`inspector-tab ${tab === 'peers' ? 'active' : ''}`}
            onClick={() => setTab('peers')}
          >
            <Users size={13} /> Peers ({details?.peers.length ?? torrent.num_peers})
          </button>
          <button
            className={`inspector-tab ${tab === 'trackers' ? 'active' : ''}`}
            onClick={() => setTab('trackers')}
          >
            <Radio size={13} /> Trackers ({details?.trackers.length ?? 0})
          </button>
          <button
            className={`inspector-tab ${tab === 'telemetry' ? 'active' : ''}`}
            onClick={() => setTab('telemetry')}
          >
            <Activity size={13} /> Telemetria
          </button>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <label style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 12, cursor: 'pointer' }}>
            <input
              type="checkbox"
              checked={torrent.sequential}
              onChange={(e) => onToggleSequential(torrent.info_hash, e.target.checked)}
            />
            <span>Sequencial</span>
          </label>
          <label style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 12, cursor: 'pointer' }}>
            <input
              type="checkbox"
              checked={torrent.prioritize_ends}
              onChange={(e) => onTogglePrioritizeEnds(torrent.info_hash, e.target.checked)}
            />
            <span>Priorizar início e fim</span>
          </label>
          <button
            className="btn btn-sm"
            onClick={() => onRecheck(torrent.info_hash)}
            title="Verificar integridade SHA das peças em disco"
          >
            <RefreshCw size={12} /> Verificar
          </button>
        </div>
      </div>

      <div className="inspector-body">
        {tab === 'general' && (
          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6, fontSize: 11.5, color: 'var(--text-dim)' }}>
              <span>
                Mapa de peças ({details?.num_pieces ?? 0} peças de {formatBytes(details?.piece_length ?? 0)})
              </span>
              <span style={{ display: 'flex', gap: 12 }}>
                <span>
                  <span style={{ color: 'var(--cyan)' }}>■</span> Baixada
                </span>
                <span>
                  <span style={{ color: 'var(--amber)' }}>■</span> Em transferência
                </span>
                <span>
                  <span style={{ color: '#334155' }}>■</span> Pendente
                </span>
              </span>
            </div>

            <canvas
              ref={canvasRef}
              style={{
                width: '100%',
                height: 24,
                borderRadius: 6,
                border: '1px solid var(--border)',
                display: 'block',
              }}
            />

            <div className="kv-grid tabular">
              <div className="kv-item">
                <span className="kv-label">Info Hash</span>
                <span className="kv-val" title={torrent.info_hash}>{torrent.info_hash}</span>
              </div>
              <div className="kv-item">
                <span className="kv-label">Destino Final</span>
                <span className="kv-val" title={torrent.final_save_path}>
                  {torrent.final_save_path} ({torrent.dest_media_type})
                </span>
              </div>
              <div className="kv-item">
                <span className="kv-label">Gravação Atual</span>
                <span className="kv-val" title={torrent.save_path}>
                  {torrent.staging_active ? `NVMe Staging: ${torrent.save_path}` : torrent.save_path}
                </span>
              </div>
              <div className="kv-item">
                <span className="kv-label">Velocidade / Pico</span>
                <span className="kv-val">
                  {formatSpeed(torrent.download_rate)} / Pico {formatSpeed(torrent.peak_download_rate)}
                </span>
              </div>
              <div className="kv-item">
                <span className="kv-label">Transferido / Razão</span>
                <span className="kv-val">
                  ↓ {formatBytes(torrent.downloaded)} / ↑ {formatBytes(torrent.uploaded)} (Razão {torrent.ratio})
                </span>
              </div>
              <div className="kv-item">
                <span className="kv-label">Tempo Restante</span>
                <span className="kv-val">
                  {torrent.is_finished ? 'Concluído' : formatEta(torrent.eta)}
                </span>
              </div>
            </div>
          </div>
        )}

        {tab === 'files' && (
          <table className="data-table tabular">
            <thead>
              <tr>
                <th style={{ width: 32 }}>Baixar</th>
                <th>Arquivo</th>
                <th style={{ width: 95 }}>Tamanho</th>
                <th style={{ width: 120 }}>Progresso</th>
                <th style={{ width: 110 }}>Prioridade</th>
              </tr>
            </thead>
            <tbody>
              {(details?.files ?? []).map((f) => (
                <tr key={f.index}>
                  <td>
                    <input
                      type="checkbox"
                      checked={f.priority > 0}
                      onChange={(e) => handleFileCheck(f.index, e.target.checked)}
                    />
                  </td>
                  <td style={{ maxWidth: 340, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={f.path}>
                    {f.path}
                  </td>
                  <td>{formatBytes(f.size)}</td>
                  <td>{f.progress.toFixed(1)}%</td>
                  <td>
                    <select
                      value={f.priority === 0 ? 0 : f.priority >= 7 ? 7 : f.priority >= 6 ? 6 : 4}
                      onChange={(e) => handleFilePrio(f.index, Number(e.target.value))}
                      style={{ padding: '2px 6px', fontSize: 11.5 }}
                    >
                      {PRIO_LABELS.map((opt) => (
                        <option key={opt.value} value={opt.value}>
                          {opt.label}
                        </option>
                      ))}
                    </select>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        {tab === 'peers' && (
          <table className="data-table tabular">
            <thead>
              <tr>
                <th>IP:Porta</th>
                <th>Cliente</th>
                <th>Proto</th>
                <th>Download</th>
                <th>Upload</th>
                <th>Progresso</th>
                <th>RTT</th>
                <th>Estado</th>
              </tr>
            </thead>
            <tbody>
              {(details?.peers ?? []).map((p) => (
                <tr key={p.endpoint}>
                  <td>{p.endpoint}</td>
                  <td>{p.client}</td>
                  <td>
                    <span className="badge" style={{ background: p.proto === 'TCP' ? 'var(--cyan-dim)' : 'var(--violet-dim)', color: p.proto === 'TCP' ? 'var(--cyan)' : 'var(--violet)' }}>
                      {p.proto}
                    </span>
                  </td>
                  <td style={{ color: 'var(--cyan)' }}>{formatSpeed(p.down_speed)}</td>
                  <td style={{ color: 'var(--violet)' }}>{formatSpeed(p.up_speed)}</td>
                  <td>{p.progress.toFixed(1)}%</td>
                  <td>{p.rtt} ms</td>
                  <td style={{ color: 'var(--text-dim)' }}>{p.flags}</td>
                </tr>
              ))}
              {(details?.peers.length ?? 0) === 0 && (
                <tr>
                  <td colSpan={8} style={{ color: 'var(--text-muted)', textAlign: 'center', padding: 14 }}>
                    Nenhum peer conectado no momento.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        )}

        {tab === 'trackers' && (
          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
              <span style={{ fontSize: 12, color: 'var(--text-dim)' }}>
                {torrent.is_private
                  ? 'Torrent privado: injeção de trackers públicos bloqueada para proteger sua conta.'
                  : 'Trackers públicos ativos para acelerar descoberta de peers.'}
              </span>
              <button
                className="btn btn-primary btn-sm"
                disabled={torrent.is_private}
                onClick={() => onBoostTrackers(torrent.info_hash)}
              >
                <Zap size={12} /> Injetar Trackers Públicos
              </button>
            </div>
            <table className="data-table tabular">
              <thead>
                <tr>
                  <th>URL</th>
                  <th>Tier</th>
                  <th>Status</th>
                  <th>Seeds</th>
                  <th>Leeches</th>
                </tr>
              </thead>
              <tbody>
                {(details?.trackers ?? []).map((tr, i) => (
                  <tr key={`${tr.url}-${i}`}>
                    <td style={{ maxWidth: 380, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={tr.url}>
                      {tr.url}
                    </td>
                    <td>{tr.tier}</td>
                    <td>{tr.status}</td>
                    <td>{tr.seeds >= 0 ? tr.seeds : '-'}</td>
                    <td>{tr.leeches >= 0 ? tr.leeches : '-'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {tab === 'telemetry' && (
          <div className="kv-grid tabular">
            <div className="kv-item">
              <span className="kv-label">Diagnóstico de Gargalo</span>
              <span className="kv-val" style={{ color: 'var(--cyan)' }}>
                <Cpu size={12} style={{ verticalAlign: 'middle', marginRight: 4 }} />
                {globalStats.bottleneck.label}: {globalStats.bottleneck.detail}
              </span>
            </div>
            <div className="kv-item">
              <span className="kv-label">Fila de Escrita em Disco</span>
              <span className="kv-val">{formatBytes(globalStats.queued_write_bytes)}</span>
            </div>
            <div className="kv-item">
              <span className="kv-label">Eficiência Payload vs Overhead</span>
              <span className="kv-val">{globalStats.payload_efficiency.toFixed(2)}%</span>
            </div>
            <div className="kv-item">
              <span className="kv-label">Conexões Globais</span>
              <span className="kv-val">
                {globalStats.peers_connected} conectadas ({globalStats.peers_half_open} meio-abertas)
              </span>
            </div>
            <div className="kv-item">
              <span className="kv-label">Mídia de Destino</span>
              <span className="kv-val">{torrent.dest_media_type}</span>
            </div>
            <div className="kv-item">
              <span className="kv-label">Staging NVMe</span>
              <span className="kv-val">{torrent.staging_note || (torrent.staging_active ? 'Ativo' : 'Direto')}</span>
            </div>
            <div className="kv-item">
              <span className="kv-label">Tabela DHT</span>
              <span className="kv-val">
                {globalStats.dht_state_loaded ? 'Pré-aquecida (cache)' : 'Bootstrap inicial'}
              </span>
            </div>
            <div className="kv-item">
              <span className="kv-label">Interfaces de Escuta</span>
              <span className="kv-val" title={globalStats.listen_interfaces || ''}>
                {globalStats.listen_interfaces || 'Automático'}
              </span>
            </div>
            <div className="kv-item">
              <span className="kv-label">Limite de Fila em RAM</span>
              <span className="kv-val">{globalStats.max_queued_disk_mb ?? 512} MB</span>
            </div>
          </div>
        )}
      </div>
    </section>
  );
}
