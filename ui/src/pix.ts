export const PROJECT_GITHUB_URL = 'https://github.com/felipegakkeku/nexo-torrent';

export const PIX_SUPPORT = {
  key: '0a2a3538-4d9e-4eeb-836e-5ee6136ab7ff',
  name: 'NEXO TORRENT',
  city: 'BRASIL',
  txId: '***',
} as const;

export function crc16Ccitt(payload: string): string {
  let crc = 0xffff;
  for (let i = 0; i < payload.length; i += 1) {
    crc ^= payload.charCodeAt(i) << 8;
    for (let j = 0; j < 8; j += 1) {
      if ((crc & 0x8000) !== 0) {
        crc = ((crc << 1) ^ 0x1021) & 0xffff;
      } else {
        crc = (crc << 1) & 0xffff;
      }
    }
  }
  return crc.toString(16).toUpperCase().padStart(4, '0');
}

export function formatEmvField(id: string, value: string): string {
  const len = String(value.length).padStart(2, '0');
  return `${id}${len}${value}`;
}

function sanitizeAsciiUpper(text: string, maxLen: number): string {
  return text
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .toUpperCase()
    .slice(0, maxLen);
}

/**
 * Gera o codigo Pix Copia e Cola no padrao EMV BR Code do Banco Central.
 * Quando o valor e omitido ou nulo, gera um QR estatico reutilizavel de valor livre.
 */
export function generatePixBrCode(amount?: number | null): string {
  const cleanKey = PIX_SUPPORT.key.trim();
  const cleanName = sanitizeAsciiUpper(PIX_SUPPORT.name, 25);
  const cleanCity = sanitizeAsciiUpper(PIX_SUPPORT.city, 15);
  const cleanTxId = PIX_SUPPORT.txId.replace(/[^a-zA-Z0-9*]/g, '').slice(0, 25) || '***';

  const gui = formatEmvField('00', 'br.gov.bcb.pix');
  const keyField = formatEmvField('01', cleanKey);
  const merchantAccount = formatEmvField('26', `${gui}${keyField}`);
  const additionalData = formatEmvField('62', formatEmvField('05', cleanTxId));

  let payload =
    formatEmvField('00', '01') +
    merchantAccount +
    formatEmvField('52', '0000') +
    formatEmvField('53', '986');

  if (typeof amount === 'number' && Number.isFinite(amount) && amount > 0) {
    payload += formatEmvField('54', amount.toFixed(2));
  }

  payload +=
    formatEmvField('58', 'BR') +
    formatEmvField('59', cleanName) +
    formatEmvField('60', cleanCity) +
    additionalData +
    '6304';

  return `${payload}${crc16Ccitt(payload)}`;
}
