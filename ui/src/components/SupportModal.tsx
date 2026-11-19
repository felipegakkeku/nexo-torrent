import { useEffect, useMemo, useRef, useState } from 'react';
import { Check, Copy, ExternalLink, Heart, X } from 'lucide-react';
import QRCode from 'qrcode';
import { generatePixBrCode, PIX_SUPPORT, PROJECT_GITHUB_URL } from '../pix';

interface SupportModalProps {
  onClose: () => void;
  onNotify: (msg: string, error?: boolean) => void;
}

const AMOUNT_PRESETS: Array<{ label: string; value: number | null }> = [
  { label: 'Livre', value: null },
  { label: 'R$ 5', value: 5 },
  { label: 'R$ 10', value: 10 },
  { label: 'R$ 25', value: 25 },
  { label: 'R$ 50', value: 50 },
];

export function SupportModal({ onClose, onNotify }: SupportModalProps) {
  const [amount, setAmount] = useState<number | null>(null);
  const [qrDataUrl, setQrDataUrl] = useState<string>('');
  const [copiedField, setCopiedField] = useState<'code' | 'key' | null>(null);
  const copyTimerRef = useRef<number | undefined>(undefined);

  const emvCode = useMemo(() => generatePixBrCode(amount), [amount]);

  useEffect(() => {
    let active = true;
    QRCode.toDataURL(emvCode, {
      width: 220,
      margin: 2,
      errorCorrectionLevel: 'M',
      color: { dark: '#080909', light: '#ffffff' },
    })
      .then((url) => {
        if (active) setQrDataUrl(url);
      })
      .catch(() => {
        if (active) setQrDataUrl('');
      });

    return () => {
      active = false;
    };
  }, [emvCode]);

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKeyDown);
    return () => {
      window.removeEventListener('keydown', onKeyDown);
      if (copyTimerRef.current) window.clearTimeout(copyTimerRef.current);
    };
  }, [onClose]);

  const handleCopy = async (field: 'code' | 'key', value: string, successMessage: string) => {
    try {
      await navigator.clipboard.writeText(value);
      setCopiedField(field);
      onNotify(successMessage);
      if (copyTimerRef.current) window.clearTimeout(copyTimerRef.current);
      copyTimerRef.current = window.setTimeout(() => {
        setCopiedField((prev) => (prev === field ? null : prev));
      }, 2000);
    } catch {
      onNotify('Não foi possível copiar para a área de transferência.', true);
    }
  };

  const handleOpenGithub = async () => {
    if (window.nexoTorrent?.openExternal) {
      await window.nexoTorrent.openExternal(PROJECT_GITHUB_URL);
    } else {
      window.open(PROJECT_GITHUB_URL, '_blank', 'noopener,noreferrer');
    }
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div
        className="modal-panel"
        style={{ maxWidth: 540 }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-header">
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <Heart size={16} style={{ color: 'var(--nexo-brand)' }} />
            <span>Apoiar o Nexo Torrent</span>
          </div>
          <button className="btn-icon" onClick={onClose} title="Fechar">
            <X size={16} />
          </button>
        </div>

        <div className="modal-body">
          <p className="support-desc">
            O Nexo Torrent é 100% gratuito, open source (MIT) e sem anúncios nem telemetria.
            Se o projeto acelerou seus downloads, você pode apoiar o desenvolvimento contínuo via Pix.
          </p>

          <div className="field">
            <span className="field-label">Valor sugerido</span>
            <div className="support-presets">
              {AMOUNT_PRESETS.map((preset) => (
                <button
                  key={preset.label}
                  type="button"
                  className={`filter-tab support-preset ${amount === preset.value ? 'active' : ''}`}
                  onClick={() => setAmount(preset.value)}
                >
                  {preset.label}
                </button>
              ))}
            </div>
          </div>

          <div className="support-grid">
            <div className="support-qr-box">
              {qrDataUrl ? (
                <img
                  src={qrDataUrl}
                  alt="QR Code Pix para apoiar o Nexo Torrent"
                  className="support-qr-img"
                />
              ) : (
                <div className="support-qr-placeholder">Gerando QR...</div>
              )}
              <span className="support-qr-hint">Escaneie no app do seu banco</span>
            </div>

            <div className="support-info-col">
              <div className="kv-item">
                <span className="kv-label">Chave Pix (Aleatória)</span>
                <div className="field-row" style={{ marginTop: 2 }}>
                  <code className="support-key tabular">{PIX_SUPPORT.key}</code>
                  <button
                    type="button"
                    className="btn btn-sm"
                    onClick={() =>
                      handleCopy('key', PIX_SUPPORT.key, 'Chave Pix copiada para a área de transferência.')
                    }
                    title="Copiar chave Pix"
                  >
                    {copiedField === 'key' ? <Check size={13} /> : <Copy size={13} />}
                    <span>{copiedField === 'key' ? 'Copiada' : 'Copiar chave'}</span>
                  </button>
                </div>
              </div>

              <button
                type="button"
                className="btn btn-primary"
                onClick={() =>
                  handleCopy('code', emvCode, 'Código Pix Copia e Cola copiado para a área de transferência.')
                }
              >
                {copiedField === 'code' ? <Check size={14} /> : <Copy size={14} />}
                <span>{copiedField === 'code' ? 'Pix Copia e Cola copiado' : 'Copiar Pix Copia e Cola'}</span>
              </button>

              <span className="toggle-desc">
                O app do seu banco identifica o recebedor automaticamente pela chave.
              </span>
            </div>
          </div>

          <div className="field">
            <span className="field-label">Pix Copia e Cola</span>
            <input
              type="text"
              readOnly
              value={emvCode}
              className="support-code-box tabular"
              onClick={(e) => e.currentTarget.select()}
              aria-label="Código Pix Copia e Cola"
            />
          </div>
        </div>

        <div className="modal-footer support-footer">
          <button type="button" className="btn btn-sm" onClick={handleOpenGithub}>
            <ExternalLink size={13} />
            <span>Repositório no GitHub</span>
          </button>
          <button type="button" className="btn btn-sm" onClick={onClose}>
            Fechar
          </button>
        </div>
      </div>
    </div>
  );
}
