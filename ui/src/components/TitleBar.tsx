import {
  Activity,
  ArrowDown,
  ArrowUp,
  FilePlus2,
  Heart,
  Link2,
  Minus,
  Radio,
  Settings,
  Square,
  X,
} from 'lucide-react';
import { formatSpeed } from '../format';
import type { GlobalStats, ProfileType } from '../types';

interface TitleBarProps {
  globalStats: GlobalStats;
  profile: ProfileType;
  onChangeProfile: (profile: ProfileType) => void;
  onOpenMagnet: () => void;
  onOpenTorrentFile: () => void;
  onOpenSupport: () => void;
  onOpenSettings: () => void;
}

export function TitleBar({
  globalStats,
  profile,
  onChangeProfile,
  onOpenMagnet,
  onOpenTorrentFile,
  onOpenSupport,
  onOpenSettings,
}: TitleBarProps) {
  const bottleneck = globalStats.bottleneck;
  const isWarn =
    bottleneck.code === 'disk_queue' ||
    bottleneck.code === 'nat_restricted' ||
    bottleneck.code === 'swarm_limited';

  return (
    <header className="titlebar">
      <div className="titlebar-left">
        <div className="brand">
          <svg width="20" height="20" viewBox="0 0 24 24" aria-hidden="true">
            <defs>
              <radialGradient id="nexoOrbBrand" cx="35%" cy="32%" r="68%">
                <stop offset="0%" stopColor="#ffffff" />
                <stop offset="28%" stopColor="#65b7aa" />
                <stop offset="70%" stopColor="#0a1d12" />
                <stop offset="100%" stopColor="#040505" />
              </radialGradient>
            </defs>
            <circle cx="12" cy="12" r="10" fill="url(#nexoOrbBrand)" stroke="#65b7aa" strokeWidth="1.2" />
            <path d="M12 7v6.5m0 0l-2.6-2.6M12 13.5l2.6-2.6M8.5 16.5h7" stroke="#f6f5f1" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" fill="none" />
          </svg>
          <span>
            NEXO <span className="brand-accent">TORRENT</span>
          </span>
          <span className="brand-oss" title="Open Source (MIT)">OSS</span>
        </div>

        <div className="kpi-strip">
          <div className="kpi-pill tabular" title="Velocidade total de download">
            <ArrowDown size={13} className="kpi-dl" />
            <span className="kpi-dl">{formatSpeed(globalStats.download_rate)}</span>
          </div>

          <div className="kpi-pill tabular" title="Velocidade total de upload">
            <ArrowUp size={13} className="kpi-ul" />
            <span className="kpi-ul">{formatSpeed(globalStats.upload_rate)}</span>
          </div>

          <div className="kpi-pill tabular" title="Nós ativos na rede DHT">
            <Radio size={13} style={{ color: 'var(--text-dim)' }} />
            <span>DHT: {globalStats.dht_nodes}</span>
          </div>

          <div
            className="kpi-pill"
            title={bottleneck.detail}
            style={{ cursor: 'help' }}
          >
            <Activity
              size={13}
              className={isWarn ? 'kpi-warn' : 'kpi-ok'}
            />
            <span className={isWarn ? 'kpi-warn' : 'kpi-ok'}>
              {bottleneck.label}
            </span>
          </div>
        </div>
      </div>

      <div className="titlebar-actions">
        <select
          className="profile-select"
          value={profile}
          onChange={(e) => onChangeProfile(e.target.value as ProfileType)}
          title="Perfil de desempenho do motor C++"
        >
          <option value="turbo_max">Perfil: Turbo Max</option>
          <option value="balanced">Perfil: Balanceado</option>
          <option value="quiet">Perfil: Silencioso</option>
        </select>

        <button className="btn btn-primary btn-sm" onClick={onOpenMagnet} title="Adicionar link magnet (Ctrl+V)">
          <Link2 size={14} />
          <span>Magnet</span>
        </button>

        <button className="btn btn-sm" onClick={onOpenTorrentFile} title="Abrir arquivo .torrent">
          <FilePlus2 size={14} />
          <span>.torrent</span>
        </button>

        <button
          className="btn btn-support btn-sm"
          onClick={onOpenSupport}
          title="Apoiar o Nexo Torrent via Pix"
        >
          <Heart size={13} />
          <span>Apoiar</span>
        </button>

        <button className="btn-icon" onClick={onOpenSettings} title="Configurações">
          <Settings size={16} />
        </button>

        {window.nexoTorrent && (
          <div className="win-controls">
            <button
              className="win-btn"
              onClick={() => window.nexoTorrent?.windowMinimize()}
              title="Minimizar"
            >
              <Minus size={14} />
            </button>
            <button
              className="win-btn"
              onClick={() => window.nexoTorrent?.windowMaximize()}
              title="Maximizar ou restaurar"
            >
              <Square size={12} />
            </button>
            <button
              className="win-btn close"
              onClick={() => window.nexoTorrent?.windowClose()}
              title="Fechar para bandeja"
            >
              <X size={15} />
            </button>
          </div>
        )}
      </div>
    </header>
  );
}
