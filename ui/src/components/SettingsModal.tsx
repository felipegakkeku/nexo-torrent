import { useEffect, useState } from 'react';
import { FolderOpen, ShieldCheck, X } from 'lucide-react';
import type { AppConfig, HardwareInfo, ProfileType } from '../types';

interface SettingsModalProps {
  config: AppConfig;
  hardware: HardwareInfo | null;
  onSave: (cfg: AppConfig) => Promise<void>;
  onClose: () => void;
  onNotify: (msg: string, isError?: boolean) => void;
}

export function SettingsModal({
  config,
  hardware,
  onSave,
  onClose,
  onNotify,
}: SettingsModalProps) {
  const [draft, setDraft] = useState<AppConfig>(config);
  const [saving, setSaving] = useState(false);
  const [osStatus, setOsStatus] = useState<{ magnet: boolean; torrent: boolean }>({
    magnet: false,
    torrent: false,
  });

  useEffect(() => {
    window.vortex?.getOsHandlersStatus().then(setOsStatus).catch(() => {});
  }, []);

  const pickFolder = async (current: string, field: 'default_save_path' | 'staging_path') => {
    const chosen = await window.vortex?.selectFolder(current);
    if (chosen) {
      setDraft({ ...draft, [field]: chosen });
    }
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      await onSave(draft);
      onClose();
    } finally {
      setSaving(false);
    }
  };

  const handleRegisterOs = async () => {
    if (!window.vortex) return;
    const res = await window.vortex.registerOsHandlers();
    onNotify(res.message, !res.ok);
    const st = await window.vortex.getOsHandlersStatus();
    setOsStatus(st);
  };

  const handleUnregisterOs = async () => {
    if (!window.vortex) return;
    const res = await window.vortex.unregisterOsHandlers();
    onNotify(res.message, !res.ok);
    const st = await window.vortex.getOsHandlersStatus();
    setOsStatus(st);
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-panel" style={{ maxWidth: 720 }} onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <span>Configurações do VortexTorrent</span>
          <button className="btn-icon" onClick={onClose}>
            <X size={16} />
          </button>
        </div>

        <div className="modal-body">
          <div className="field">
            <label className="field-label">Perfil de Desempenho (libtorrent 2.1.1)</label>
            <select
              value={draft.profile}
              onChange={(e) => setDraft({ ...draft, profile: e.target.value as ProfileType })}
            >
              <option value="turbo_max">
                Turbo Max (500 conexões/s, 1200 conexões globais, fila 2500, SHA-NI paralelo)
              </option>
              <option value="balanced">
                Balanceado (200 conexões/s, 500 conexões globais, menor uso de RAM)
              </option>
              <option value="quiet">
                Silencioso (80 conexões/s, 220 conexões globais, navegação leve)
              </option>
            </select>
          </div>

          <div className="field">
            <label className="field-label">Pasta Padrão de Downloads</label>
            <div className="field-row">
              <input
                type="text"
                style={{ flex: 1 }}
                value={draft.default_save_path}
                onChange={(e) => setDraft({ ...draft, default_save_path: e.target.value })}
              />
              <button
                className="btn"
                onClick={() => pickFolder(draft.default_save_path, 'default_save_path')}
              >
                <FolderOpen size={14} /> Escolher
              </button>
            </div>
          </div>

          <div className="field">
            <label className="field-label">Pasta de Turbo Staging (SSD/NVMe)</label>
            <div className="field-row">
              <input
                type="text"
                style={{ flex: 1 }}
                value={draft.staging_path}
                onChange={(e) => setDraft({ ...draft, staging_path: e.target.value })}
              />
              <button
                className="btn"
                onClick={() => pickFolder(draft.staging_path, 'staging_path')}
              >
                <FolderOpen size={14} /> Escolher
              </button>
            </div>
          </div>

          <div className="toggle-row">
            <div className="toggle-info">
              <span className="toggle-title">Turbo Staging Automático em SSD/NVMe</span>
              <span className="toggle-desc">
                Quando o destino for HDD, baixa no SSD/NVMe e move sequencialmente ao concluir (reserva mínima: {draft.staging_min_free_gb} GB).
              </span>
            </div>
            <input
              type="checkbox"
              checked={draft.nvme_staging_enabled}
              onChange={(e) => setDraft({ ...draft, nvme_staging_enabled: e.target.checked })}
            />
          </div>

          <div className="toggle-row">
            <div className="toggle-info">
              <span className="toggle-title">Pré-alocação Contígua em NTFS</span>
              <span className="toggle-desc">Reserva o espaço dos arquivos no início para reduzir fragmentação em disco.</span>
            </div>
            <input
              type="checkbox"
              checked={draft.preallocate_files}
              onChange={(e) => setDraft({ ...draft, preallocate_files: e.target.checked })}
            />
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
            <div className="field">
              <label className="field-label">Porta de Escuta</label>
              <input
                type="number"
                min={1024}
                max={65535}
                value={draft.listen_port}
                onChange={(e) => setDraft({ ...draft, listen_port: Number(e.target.value) || 51413 })}
              />
            </div>

            <div className="field">
              <label className="field-label">Bind de Interface de Rede (VPN / Placa)</label>
              <select
                value={draft.network_interface}
                onChange={(e) => setDraft({ ...draft, network_interface: e.target.value })}
              >
                <option value="">Todas as interfaces disponíveis</option>
                {(hardware?.interfaces ?? []).map((iface) => (
                  <option key={`${iface.name}-${iface.ip}`} value={iface.name}>
                    {iface.name} {iface.ip ? `(${iface.ip})` : ''} {iface.is_vpn ? '[VPN]' : ''}
                  </option>
                ))}
              </select>
            </div>

            <div className="field">
              <label className="field-label">Limite de Download (KB/s, 0 = ilimitado)</label>
              <input
                type="number"
                min={0}
                value={draft.download_limit_kbps}
                onChange={(e) => setDraft({ ...draft, download_limit_kbps: Math.max(0, Number(e.target.value) || 0) })}
              />
            </div>

            <div className="field">
              <label className="field-label">Limite de Upload (KB/s, 0 = ilimitado)</label>
              <input
                type="number"
                min={0}
                value={draft.upload_limit_kbps}
                onChange={(e) => setDraft({ ...draft, upload_limit_kbps: Math.max(0, Number(e.target.value) || 0) })}
              />
            </div>
          </div>

          <div className="toggle-row">
            <div className="toggle-info">
              <span className="toggle-title">Priorizar TCP sobre uTP (Velocidade Pura)</span>
              <span className="toggle-desc">Evita que o controle de latência do uTP reduza a banda de download em TCP.</span>
            </div>
            <input
              type="checkbox"
              checked={draft.prefer_tcp}
              onChange={(e) => setDraft({ ...draft, prefer_tcp: e.target.checked })}
            />
          </div>

          <div className="toggle-row">
            <div className="toggle-info">
              <span className="toggle-title">Anti-Stall Endgame Booster</span>
              <span className="toggle-desc">Acelera os blocos finais nos últimos 8% e evita travamento em 99%.</span>
            </div>
            <input
              type="checkbox"
              checked={draft.anti_stall_enabled}
              onChange={(e) => setDraft({ ...draft, anti_stall_enabled: e.target.checked })}
            />
          </div>

          <div className="toggle-row">
            <div className="toggle-info">
              <span className="toggle-title">Boost Automático de Trackers Públicos</span>
              <span className="toggle-desc">Adiciona trackers rápidos apenas em torrents públicos (nunca em privados).</span>
            </div>
            <input
              type="checkbox"
              checked={draft.auto_boost_public_trackers}
              onChange={(e) => setDraft({ ...draft, auto_boost_public_trackers: e.target.checked })}
            />
          </div>

          <div className="toggle-row">
            <div className="toggle-info">
              <span className="toggle-title">DHT, Descoberta Local (LSD) e UPnP/NAT-PMP</span>
              <span className="toggle-desc">Descoberta descentralizada de peers e abertura automática de porta no roteador.</span>
            </div>
            <input
              type="checkbox"
              checked={draft.enable_dht && draft.enable_upnp}
              onChange={(e) =>
                setDraft({
                  ...draft,
                  enable_dht: e.target.checked,
                  enable_lsd: e.target.checked,
                  enable_upnp: e.target.checked,
                })
              }
            />
          </div>

          <div className="toggle-row">
            <div className="toggle-info">
              <span className="toggle-title">Minimizar para Bandeja do Sistema ao Fechar</span>
              <span className="toggle-desc">Mantém downloads ativos em segundo plano no ícone do relógio.</span>
            </div>
            <input
              type="checkbox"
              checked={draft.minimize_to_tray}
              onChange={(e) => setDraft({ ...draft, minimize_to_tray: e.target.checked })}
            />
          </div>

          {window.vortex && (
            <div className="toggle-row">
              <div className="toggle-info">
                <span className="toggle-title">
                  <ShieldCheck size={13} style={{ color: 'var(--cyan)', verticalAlign: 'middle', marginRight: 5 }} />
                  Integração Windows (magnet: e .torrent)
                </span>
                <span className="toggle-desc">
                  Status atual: magnet ({osStatus.magnet ? 'registrado' : 'inativo'}), .torrent ({osStatus.torrent ? 'registrado' : 'inativo'}).
                </span>
              </div>
              <div style={{ display: 'flex', gap: 6 }}>
                <button className="btn btn-primary btn-sm" onClick={handleRegisterOs}>
                  Registrar no Windows
                </button>
                <button className="btn btn-sm" onClick={handleUnregisterOs}>
                  Remover
                </button>
              </div>
            </div>
          )}
        </div>

        <div className="modal-footer">
          <button className="btn" onClick={onClose}>
            Cancelar
          </button>
          <button className="btn btn-primary" disabled={saving} onClick={handleSave}>
            {saving ? 'Aplicando...' : 'Salvar e Aplicar'}
          </button>
        </div>
      </div>
    </div>
  );
}
