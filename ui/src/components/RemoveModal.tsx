import { useState } from 'react';
import { Trash2, X } from 'lucide-react';
import type { TorrentSummary } from '../types';

interface RemoveModalProps {
  torrent: TorrentSummary;
  onConfirm: (deleteFiles: boolean) => Promise<void>;
  onClose: () => void;
}

export function RemoveModal({ torrent, onConfirm, onClose }: RemoveModalProps) {
  const [deleteFiles, setDeleteFiles] = useState(false);
  const [busy, setBusy] = useState(false);

  const handleConfirm = async () => {
    setBusy(true);
    try {
      await onConfirm(deleteFiles);
      onClose();
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-panel" style={{ maxWidth: 460 }} onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <span>Remover Torrent</span>
          <button className="btn-icon" onClick={onClose}>
            <X size={16} />
          </button>
        </div>
        <div className="modal-body">
          <div style={{ fontWeight: 600, wordBreak: 'break-word' }}>{torrent.name}</div>
          <label className="toggle-row" style={{ cursor: 'pointer' }}>
            <div className="toggle-info">
              <span className="toggle-title" style={{ color: 'var(--red)' }}>
                Excluir também os arquivos baixados do disco
              </span>
              <span className="toggle-desc">
                Remove dados em disco permanentemente (inclusive pasta de staging).
              </span>
            </div>
            <input
              type="checkbox"
              checked={deleteFiles}
              onChange={(e) => setDeleteFiles(e.target.checked)}
            />
          </label>
        </div>
        <div className="modal-footer">
          <button className="btn" onClick={onClose}>
            Cancelar
          </button>
          <button className="btn btn-danger" disabled={busy} onClick={handleConfirm}>
            <Trash2 size={14} /> {busy ? 'Removendo...' : 'Remover'}
          </button>
        </div>
      </div>
    </div>
  );
}
