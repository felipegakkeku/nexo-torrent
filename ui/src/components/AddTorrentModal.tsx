import { useEffect, useState } from 'react';
import { FolderOpen, HardDrive, Link2, Lock, X, Zap } from 'lucide-react';
import { api } from '../api';
import { formatBytes } from '../format';
import type { AppConfig, HardwareInfo, InspectTorrentResult } from '../types';

export interface AddModalInitial {
  mode: 'magnet' | 'file';
  magnetUri?: string;
  file?: File;
}

interface AddTorrentModalProps {
  initial: AddModalInitial;
  config: AppConfig;
  hardware: HardwareInfo | null;
  onClose: () => void;
  onAdded: (infoHash: string) => void;
  onError: (msg: string) => void;
}

export function AddTorrentModal({
  initial,
  config,
  hardware,
  onClose,
  onAdded,
  onError,
}: AddTorrentModalProps) {
  const [mode, setMode] = useState<'magnet' | 'file'>(initial.mode);
  const [magnetUri, setMagnetUri] = useState(initial.magnetUri ?? '');
  const [file, setFile] = useState<File | null>(initial.file ?? null);
  const [inspect, setInspect] = useState<InspectTorrentResult | null>(null);
  const [selectedFiles, setSelectedFiles] = useState<boolean[]>([]);
  const [savePath, setSavePath] = useState(config.default_save_path);
  const [useStaging, setUseStaging] = useState<boolean>(config.nvme_staging_enabled);
  const [stagingReason, setStagingReason] = useState<string>('');
  const [sequential, setSequential] = useState(false);
  const [prioritizeEnds, setPrioritizeEnds] = useState(false);
  const [boostTrackers, setBoostTrackers] = useState(config.auto_boost_public_trackers);
  const [startPaused, setStartPaused] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (mode !== 'file' || !file) {
      setInspect(null);
      return;
    }
    let active = true;
    api
      .inspectTorrent(file)
      .then((res) => {
        if (!active) return;
        setInspect(res);
        setSelectedFiles(res.files.map(() => true));
        if (res.is_private) {
          setBoostTrackers(false);
        }
      })
      .catch((err) => {
        if (active) onError(err.message);
      });
    return () => {
      active = false;
    };
  }, [file, mode, onError]);

  useEffect(() => {
    let active = true;
    const size = inspect?.total_size ?? 0;
    api
      .checkStaging(savePath, size)
      .then((res) => {
        if (!active) return;
        setUseStaging(res.use_staging);
        setStagingReason(res.reason);
      })
      .catch(() => {});
    return () => {
      active = false;
    };
  }, [savePath, inspect?.total_size]);

  const driveLetter = savePath.trim().slice(0, 1).toUpperCase();
  const driveInfo = hardware?.drives.find((d) => d.drive.toUpperCase() === driveLetter);

  const handleBrowseFolder = async () => {
    if (window.vortex) {
      const chosen = await window.vortex.selectFolder(savePath);
      if (chosen) setSavePath(chosen);
    }
  };

  const handleChooseTorrentFile = async () => {
    if (window.vortex) {
      const res = await window.vortex.selectTorrentFile();
      if (res) {
        const bin = atob(res.base64);
        const bytes = new Uint8Array(bin.length);
        for (let i = 0; i < bin.length; i += 1) bytes[i] = bin.charCodeAt(i);
        setFile(new File([bytes], res.name, { type: 'application/x-bittorrent' }));
        setMode('file');
      }
    }
  };

  const handleSubmit = async () => {
    setSubmitting(true);
    try {
      if (mode === 'magnet') {
        if (!magnetUri.trim().toLowerCase().startsWith('magnet:?')) {
          throw new Error('Cole um link magnet válido começando com magnet:?');
        }
        const added = await api.addMagnet({
          uri: magnetUri.trim(),
          save_path: savePath.trim(),
          use_staging: useStaging,
          sequential,
          prioritize_ends: prioritizeEnds,
          start_paused: startPaused,
          boost_trackers: boostTrackers,
        });
        onAdded(added.info_hash);
      } else {
        if (!file) throw new Error('Selecione um arquivo .torrent.');
        const prios =
          inspect && selectedFiles.length === inspect.files.length
            ? selectedFiles.map((checked) => (checked ? 4 : 0))
            : undefined;
        const added = await api.addTorrentFile({
          file,
          save_path: savePath.trim(),
          use_staging: useStaging,
          sequential,
          prioritize_ends: prioritizeEnds,
          start_paused: startPaused,
          boost_trackers: inspect?.is_private ? false : boostTrackers,
          file_priorities: prios,
        });
        onAdded(added.info_hash);
      }
      onClose();
    } catch (err: unknown) {
      onError(err instanceof Error ? err.message : 'Falha ao adicionar torrent.');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-panel" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <span>{mode === 'magnet' ? 'Adicionar Link Magnet' : 'Adicionar Arquivo .torrent'}</span>
          <button className="btn-icon" onClick={onClose}>
            <X size={16} />
          </button>
        </div>

        <div className="modal-body">
          {mode === 'magnet' ? (
            <div className="field">
              <label className="field-label">Link Magnet</label>
              <div className="field-row">
                <Link2 size={15} style={{ color: 'var(--cyan)', flexShrink: 0 }} />
                <input
                  type="text"
                  style={{ flex: 1 }}
                  placeholder="magnet:?xt=urn:btih:..."
                  value={magnetUri}
                  onChange={(e) => setMagnetUri(e.target.value)}
                  autoFocus
                />
              </div>
            </div>
          ) : (
            <div className="field">
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <label className="field-label">Arquivo .torrent</label>
                <button className="btn btn-sm" onClick={handleChooseTorrentFile}>
                  Trocar arquivo
                </button>
              </div>
              <div style={{ padding: '8px 10px', background: 'var(--surface-2)', borderRadius: 6, border: '1px solid var(--border)' }}>
                <div style={{ fontWeight: 600 }}>{inspect?.name || file?.name || 'Nenhum arquivo'}</div>
                {inspect && (
                  <div className="tabular" style={{ fontSize: 11.5, color: 'var(--text-dim)', marginTop: 3 }}>
                    {formatBytes(inspect.total_size)} • {inspect.files.length} arquivo(s) • {inspect.num_pieces} peças
                    {inspect.is_private && (
                      <span className="badge badge-priv" style={{ marginLeft: 8 }}>
                        <Lock size={10} /> Privado
                      </span>
                    )}
                  </div>
                )}
              </div>

              {inspect && inspect.files.length > 0 && (
                <div style={{ maxHeight: 150, overflowY: 'auto', border: '1px solid var(--border)', borderRadius: 6, marginTop: 4 }}>
                  <table className="data-table tabular">
                    <thead>
                      <tr>
                        <th style={{ width: 32 }}>
                          <input
                            type="checkbox"
                            checked={selectedFiles.every(Boolean)}
                            onChange={(e) => setSelectedFiles(selectedFiles.map(() => e.target.checked))}
                          />
                        </th>
                        <th>Arquivo</th>
                        <th style={{ width: 90 }}>Tamanho</th>
                      </tr>
                    </thead>
                    <tbody>
                      {inspect.files.map((f, i) => (
                        <tr key={f.index}>
                          <td>
                            <input
                              type="checkbox"
                              checked={selectedFiles[i] ?? true}
                              onChange={(e) => {
                                const copy = [...selectedFiles];
                                copy[i] = e.target.checked;
                                setSelectedFiles(copy);
                              }}
                            />
                          </td>
                          <td style={{ maxWidth: 360, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                            {f.path}
                          </td>
                          <td>{formatBytes(f.size)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}

          <div className="field">
            <label className="field-label">Pasta de Destino</label>
            <div className="field-row">
              <input
                type="text"
                style={{ flex: 1 }}
                value={savePath}
                onChange={(e) => setSavePath(e.target.value)}
              />
              {driveInfo && (
                <span className="badge badge-nvme tabular" title={driveInfo.disk_model}>
                  <HardDrive size={11} /> {driveInfo.drive}: {driveInfo.media_type} ({driveInfo.free_gb} GB livres)
                </span>
              )}
              <button className="btn" onClick={handleBrowseFolder}>
                <FolderOpen size={14} /> Escolher
              </button>
            </div>
          </div>

          <div className="toggle-row">
            <div className="toggle-info">
              <span className="toggle-title">
                <Zap size={13} style={{ color: 'var(--cyan)', verticalAlign: 'middle', marginRight: 5 }} />
                Turbo Staging em NVMe
              </span>
              <span className="toggle-desc">
                {stagingReason || 'Baixa em SSD/NVMe sem travar o HDD e move para o destino ao concluir.'}
              </span>
            </div>
            <input
              type="checkbox"
              checked={useStaging}
              onChange={(e) => setUseStaging(e.target.checked)}
            />
          </div>

          <div className="toggle-row">
            <div className="toggle-info">
              <span className="toggle-title">Modo Sequencial + Priorizar Início e Fim</span>
              <span className="toggle-desc">Permite pré-visualizar mídia enquanto o download avança.</span>
            </div>
            <input
              type="checkbox"
              checked={sequential}
              onChange={(e) => {
                setSequential(e.target.checked);
                setPrioritizeEnds(e.target.checked);
              }}
            />
          </div>

          <div className="toggle-row">
            <div className="toggle-info">
              <span className="toggle-title">Boost de Trackers Públicos</span>
              <span className="toggle-desc">
                {inspect?.is_private
                  ? 'Bloqueado automaticamente em torrents privados.'
                  : 'Injeta trackers públicos rápidos para acelerar descoberta de peers.'}
              </span>
            </div>
            <input
              type="checkbox"
              disabled={Boolean(inspect?.is_private)}
              checked={boostTrackers}
              onChange={(e) => setBoostTrackers(e.target.checked)}
            />
          </div>

          <div className="toggle-row">
            <div className="toggle-info">
              <span className="toggle-title">Iniciar Pausado</span>
              <span className="toggle-desc">Adiciona na fila sem iniciar transferências imediatamente.</span>
            </div>
            <input
              type="checkbox"
              checked={startPaused}
              onChange={(e) => setStartPaused(e.target.checked)}
            />
          </div>
        </div>

        <div className="modal-footer">
          <button className="btn" onClick={onClose}>
            Cancelar
          </button>
          <button className="btn btn-primary" disabled={submitting} onClick={handleSubmit}>
            {submitting ? 'Adicionando...' : 'Iniciar Download'}
          </button>
        </div>
      </div>
    </div>
  );
}
