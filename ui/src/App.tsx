import { useCallback, useEffect, useRef, useState } from 'react';
import { UploadCloud } from 'lucide-react';
import { api, setEngineConnection } from './api';
import { AddTorrentModal, type AddModalInitial } from './components/AddTorrentModal';
import { RemoveModal } from './components/RemoveModal';
import { SettingsModal } from './components/SettingsModal';
import { SpeedChart } from './components/SpeedChart';
import { SupportModal } from './components/SupportModal';
import { TitleBar } from './components/TitleBar';
import { TorrentInspector } from './components/TorrentInspector';
import { TorrentList, type FilterKey } from './components/TorrentList';
import { base64ToFile, formatSpeed } from './format';
import type {
  AppConfig,
  EngineState,
  ExternalTorrentPayload,
  HardwareInfo,
  ProfileType,
  TorrentDetails,
  TorrentSummary,
} from './types';

const INITIAL_STATE: EngineState = {
  torrents: [],
  global: {
    download_rate: 0,
    upload_rate: 0,
    dht_nodes: 0,
    peers_connected: 0,
    peers_half_open: 0,
    queued_write_bytes: 0,
    payload_efficiency: 100,
    primary_link_mbps: 1000,
    profile: 'turbo_max',
    bottleneck: {
      code: 'idle',
      label: 'Ocioso',
      detail: 'Nenhum download ativo no momento.',
    },
  },
  history: [],
};

export default function App() {
  const [ready, setReady] = useState(false);
  const [state, setState] = useState<EngineState>(INITIAL_STATE);
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [hardware, setHardware] = useState<HardwareInfo | null>(null);
  const [selectedHash, setSelectedHash] = useState<string | null>(null);
  const [details, setDetails] = useState<TorrentDetails | null>(null);
  const [filter, setFilter] = useState<FilterKey>('all');
  const [search, setSearch] = useState('');
  const [addModal, setAddModal] = useState<AddModalInitial | null>(null);
  const [showSettings, setShowSettings] = useState(false);
  const [showSupport, setShowSupport] = useState(false);
  const [removeTarget, setRemoveTarget] = useState<TorrentSummary | null>(null);
  const [dragging, setDragging] = useState(false);
  const [toast, setToast] = useState<{ msg: string; error: boolean } | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const selectedHashRef = useRef<string | null>(null);
  selectedHashRef.current = selectedHash;

  const notify = useCallback((msg: string, error = false) => {
    setToast({ msg, error });
    window.setTimeout(() => {
      setToast((prev) => (prev?.msg === msg ? null : prev));
    }, 3600);
  }, []);

  const handleExternalPayload = useCallback((payload: ExternalTorrentPayload) => {
    if (payload.kind === 'magnet' && payload.uri) {
      setAddModal({ mode: 'magnet', magnetUri: payload.uri });
    } else if (payload.kind === 'file' && payload.base64) {
      const f = base64ToFile(payload.base64, payload.name || 'arquivo.torrent');
      setAddModal({ mode: 'file', file: f });
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    let reconnectTimer: number | undefined;

    async function bootstrap() {
      let wsUrl = 'ws://127.0.0.1:19742/ws';
      let token = '';
      if (window.nexoTorrent) {
        const info = await window.nexoTorrent.getEngineConfig();
        setEngineConnection(info);
        wsUrl = info.wsUrl;
        token = info.token;
      }

      const [cfg, hw, initial] = await Promise.all([
        api.getConfig(),
        api.getHardware(),
        api.getState(),
      ]);
      if (cancelled) return;
      setConfig(cfg);
      setHardware(hw);
      setState(initial);
      setReady(true);

      if (window.nexoTorrent) {
        const pending = await window.nexoTorrent.consumePendingExternal();
        if (pending.length > 0) {
          handleExternalPayload(pending[pending.length - 1]);
        }
      }

      const connectWs = () => {
        if (cancelled) return;
        const url = token ? `${wsUrl}?token=${encodeURIComponent(token)}` : wsUrl;
        const ws = new WebSocket(url);
        wsRef.current = ws;

        ws.onopen = () => {
          if (selectedHashRef.current) {
            ws.send(JSON.stringify({ subscribe: selectedHashRef.current }));
          }
        };

        ws.onmessage = (ev) => {
          try {
            const msg = JSON.parse(ev.data);
            if (msg.type === 'state' && msg.data) {
              setState(msg.data);
              if (msg.details !== undefined) {
                setDetails(msg.details);
              }
              if (Array.isArray(msg.events)) {
                for (const evt of msg.events) {
                  if (evt.type === 'torrent_finished') {
                    window.nexoTorrent?.notifyFinished({
                      name: evt.name,
                      final_save_path: evt.final_save_path,
                    });
                    notify(`Download concluído: ${evt.name}`);
                  }
                }
              }
              const dl = msg.data.global?.download_rate ?? 0;
              const ul = msg.data.global?.upload_rate ?? 0;
              window.nexoTorrent?.updateTrayTooltip(
                `Nexo Torrent: ↓ ${formatSpeed(dl)} | ↑ ${formatSpeed(ul)}`
              );
            } else if (msg.type === 'details') {
              setDetails(msg.details ?? null);
            }
          } catch {
            // ignora frame malformado
          }
        };

        ws.onclose = () => {
          if (!cancelled) {
            reconnectTimer = window.setTimeout(connectWs, 1200);
          }
        };
      };

      connectWs();
    }

    bootstrap().catch((err) => {
      notify(err instanceof Error ? err.message : 'Falha ao conectar ao motor.', true);
    });

    return () => {
      cancelled = true;
      if (reconnectTimer) window.clearTimeout(reconnectTimer);
      wsRef.current?.close();
    };
  }, [handleExternalPayload, notify]);

  useEffect(() => {
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ subscribe: selectedHash }));
    }
    if (!selectedHash) {
      setDetails(null);
    }
  }, [selectedHash]);

  useEffect(() => {
    if (!window.nexoTorrent) return;
    const unsubExt = window.nexoTorrent.onOpenExternalTorrent(handleExternalPayload);
    const unsubTray = window.nexoTorrent.onTrayAction((action) => {
      if (action === 'pause_all') api.pauseAll().catch(() => {});
      if (action === 'resume_all') api.resumeAll().catch(() => {});
    });
    return () => {
      unsubExt();
      unsubTray();
    };
  }, [handleExternalPayload]);

  // Ctrl+V global para link magnet quando nenhum modal estiver aberto
  useEffect(() => {
    const onPaste = (e: ClipboardEvent) => {
      if (addModal || showSettings || showSupport || removeTarget) return;
      const target = e.target as HTMLElement | null;
      if (target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA')) return;
      const text = e.clipboardData?.getData('text')?.trim() ?? '';
      if (text.toLowerCase().startsWith('magnet:?')) {
        e.preventDefault();
        setAddModal({ mode: 'magnet', magnetUri: text });
      }
    };
    window.addEventListener('paste', onPaste);
    return () => window.removeEventListener('paste', onPaste);
  }, [addModal, showSettings, showSupport, removeTarget]);

  const handleOpenTorrentFile = async () => {
    if (window.nexoTorrent) {
      const picked = await window.nexoTorrent.selectTorrentFile();
      if (picked) {
        const f = base64ToFile(picked.base64, picked.name);
        setAddModal({ mode: 'file', file: f });
      }
    } else {
      const inp = document.createElement('input');
      inp.type = 'file';
      inp.accept = '.torrent';
      inp.onchange = () => {
        const f = inp.files?.[0];
        if (f) setAddModal({ mode: 'file', file: f });
      };
      inp.click();
    }
  };

  const handleChangeProfile = async (profile: ProfileType) => {
    if (!config) return;
    try {
      const updated = await api.saveConfig({ ...config, profile });
      setConfig(updated);
      notify(`Perfil alterado para ${profile === 'turbo_max' ? 'Turbo Max' : profile === 'balanced' ? 'Balanceado' : 'Silencioso'}.`);
    } catch (err: unknown) {
      notify(err instanceof Error ? err.message : 'Erro ao alterar perfil.', true);
    }
  };

  const selectedTorrent = state.torrents.find((t) => t.info_hash === selectedHash) ?? null;

  if (!ready || !config) {
    return (
      <div className="app-shell" style={{ alignItems: 'center', justifyContent: 'center' }}>
        <div style={{ color: 'var(--nexo-brand-strong)', fontWeight: 600 }}>
          Iniciando núcleo C++ libtorrent 2.1.1...
        </div>
      </div>
    );
  }

  return (
    <div
      className="app-shell"
      onDragOver={(e) => {
        e.preventDefault();
        setDragging(true);
      }}
      onDragLeave={(e) => {
        if (e.currentTarget.contains(e.relatedTarget as Node)) return;
        setDragging(false);
      }}
      onDrop={(e) => {
        e.preventDefault();
        setDragging(false);
        const f = Array.from(e.dataTransfer.files).find((item) =>
          item.name.toLowerCase().endsWith('.torrent')
        );
        if (f) {
          setAddModal({ mode: 'file', file: f });
        } else {
          const text = e.dataTransfer.getData('text/plain')?.trim() ?? '';
          if (text.toLowerCase().startsWith('magnet:?')) {
            setAddModal({ mode: 'magnet', magnetUri: text });
          }
        }
      }}
    >
      <TitleBar
        globalStats={state.global}
        profile={config.profile}
        onChangeProfile={handleChangeProfile}
        onOpenMagnet={() => setAddModal({ mode: 'magnet', magnetUri: '' })}
        onOpenTorrentFile={handleOpenTorrentFile}
        onOpenSupport={() => setShowSupport(true)}
        onOpenSettings={() => setShowSettings(true)}
      />

      <main className="workspace">
        <SpeedChart history={state.history} primaryLinkMbps={state.global.primary_link_mbps} />

        <TorrentList
          torrents={state.torrents}
          selectedHash={selectedHash}
          filter={filter}
          search={search}
          onFilterChange={setFilter}
          onSearchChange={setSearch}
          onSelect={setSelectedHash}
          onPause={(h) => api.pause(h).catch((e) => notify(e.message, true))}
          onResume={(h) => api.resume(h).catch((e) => notify(e.message, true))}
          onPauseAll={() => api.pauseAll().catch((e) => notify(e.message, true))}
          onResumeAll={() => api.resumeAll().catch((e) => notify(e.message, true))}
          onReannounce={(h) =>
            api
              .reannounce(h)
              .then(() => notify('Reanúncio enviado aos trackers e DHT.'))
              .catch((e) => notify(e.message, true))
          }
          onRemoveRequest={setRemoveTarget}
          onOpenFolder={(t) => {
            const target = t.staging_active ? t.save_path : t.final_save_path;
            window.nexoTorrent?.openPath(target);
          }}
        />

        <TorrentInspector
          torrent={selectedTorrent}
          details={details}
          globalStats={state.global}
          onToggleSequential={(h, val) =>
            api.updateOptions(h, { sequential: val }).catch((e) => notify(e.message, true))
          }
          onTogglePrioritizeEnds={(h, val) =>
            api.updateOptions(h, { prioritize_ends: val }).catch((e) => notify(e.message, true))
          }
          onUpdateFilePriorities={(h, prios) =>
            api.updateFilePriorities(h, prios).catch((e) => notify(e.message, true))
          }
          onBoostTrackers={(h) =>
            api
              .boostTrackers(h)
              .then((res) => notify(res.reason, !res.ok))
              .catch((e) => notify(e.message, true))
          }
          onRecheck={(h) =>
            api
              .recheck(h)
              .then(() => notify('Verificação SHA iniciada.'))
              .catch((e) => notify(e.message, true))
          }
        />
      </main>

      {dragging && (
        <div className="drop-overlay">
          <UploadCloud size={44} style={{ color: 'var(--nexo-brand)' }} />
          <div style={{ fontSize: 16, fontWeight: 600 }}>Solte o arquivo .torrent aqui</div>
          <div style={{ fontSize: 12.5, color: 'var(--text-dim)' }}>
            Ou solte um link magnet para iniciar imediatamente
          </div>
        </div>
      )}

      {addModal && (
        <AddTorrentModal
          initial={addModal}
          config={config}
          hardware={hardware}
          onClose={() => setAddModal(null)}
          onAdded={(ih) => {
            setSelectedHash(ih);
            notify('Torrent adicionado ao motor Nexo.');
          }}
          onError={(msg) => notify(msg, true)}
        />
      )}

      {showSettings && (
        <SettingsModal
          config={config}
          hardware={hardware}
          onClose={() => setShowSettings(false)}
          onNotify={notify}
          onSave={async (nextCfg) => {
            const saved = await api.saveConfig(nextCfg);
            setConfig(saved);
            const hw = await api.getHardware();
            setHardware(hw);
            notify('Configurações aplicadas em tempo real.');
          }}
        />
      )}

      {showSupport && (
        <SupportModal
          onClose={() => setShowSupport(false)}
          onNotify={notify}
        />
      )}

      {removeTarget && (
        <RemoveModal
          torrent={removeTarget}
          onClose={() => setRemoveTarget(null)}
          onConfirm={async (deleteFiles) => {
            await api.remove(removeTarget.info_hash, deleteFiles);
            if (selectedHash === removeTarget.info_hash) {
              setSelectedHash(null);
            }
            notify('Torrent removido.');
          }}
        />
      )}

      {toast && <div className={`toast ${toast.error ? 'error' : ''}`}>{toast.msg}</div>}
    </div>
  );
}
