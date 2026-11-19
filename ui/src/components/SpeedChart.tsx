import { formatSpeed, formatSpeedMbps } from '../format';
import type { SpeedPoint } from '../types';

interface SpeedChartProps {
  history: SpeedPoint[];
  primaryLinkMbps: number;
}

export function SpeedChart({ history, primaryLinkMbps }: SpeedChartProps) {
  const width = 960;
  const height = 88;
  const padTop = 8;
  const padBottom = 6;
  const usableH = height - padTop - padBottom;

  const points = history.length > 1 ? history : [{ t: 0, dl: 0, ul: 0 }, { t: 1, dl: 0, ul: 0 }];
  const maxPeak = Math.max(
    1024 * 1024,
    ...points.map((p) => Math.max(p.dl, p.ul))
  );

  const linkBytesPerSec = primaryLinkMbps * 125_000;
  const showLinkLine = linkBytesPerSec > 0 && maxPeak >= linkBytesPerSec * 0.45;
  const yMax = showLinkLine ? Math.max(maxPeak * 1.12, linkBytesPerSec * 1.06) : maxPeak * 1.15;

  const buildPath = (accessor: (p: SpeedPoint) => number) => {
    const coords = points.map((p, i) => {
      const x = (i / Math.max(1, points.length - 1)) * width;
      const ratio = Math.min(1, Math.max(0, accessor(p) / yMax));
      const y = padTop + usableH * (1 - ratio);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    });
    return `M ${coords.join(' L ')}`;
  };

  const buildArea = (accessor: (p: SpeedPoint) => number) => {
    const line = buildPath(accessor);
    return `${line} L ${width},${height} L 0,${height} Z`;
  };

  const dlPeak = Math.max(0, ...points.map((p) => p.dl));
  const curDl = points[points.length - 1]?.dl ?? 0;
  const curUl = points[points.length - 1]?.ul ?? 0;
  const linkY = padTop + usableH * (1 - Math.min(1, linkBytesPerSec / yMax));

  return (
    <section className="chart-card">
      <div className="chart-header">
        <div className="chart-legend">
          <span className="legend-item tabular">
            <span className="dot" style={{ background: 'var(--cyan)' }} />
            <span>Download: {formatSpeed(curDl)} ({formatSpeedMbps(curDl)})</span>
          </span>
          <span className="legend-item tabular">
            <span className="dot" style={{ background: 'var(--violet)' }} />
            <span>Upload: {formatSpeed(curUl)}</span>
          </span>
        </div>
        <div className="tabular" style={{ display: 'flex', gap: 14 }}>
          <span>Pico recente: {formatSpeed(dlPeak)}</span>
          <span>Link detectado: {primaryLinkMbps} Mbps</span>
        </div>
      </div>

      <svg
        viewBox={`0 0 ${width} ${height}`}
        preserveAspectRatio="none"
        style={{ width: '100%', height: 78, display: 'block' }}
      >
        <defs>
          <linearGradient id="dlGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#22D3EE" stopOpacity="0.34" />
            <stop offset="100%" stopColor="#22D3EE" stopOpacity="0.02" />
          </linearGradient>
          <linearGradient id="ulGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#A78BFA" stopOpacity="0.24" />
            <stop offset="100%" stopColor="#A78BFA" stopOpacity="0.01" />
          </linearGradient>
        </defs>

        <line x1="0" y1={height * 0.33} x2={width} y2={height * 0.33} stroke="#1F2636" strokeDasharray="3 5" />
        <line x1="0" y1={height * 0.66} x2={width} y2={height * 0.66} stroke="#1F2636" strokeDasharray="3 5" />

        {showLinkLine && (
          <line
            x1="0"
            y1={linkY}
            x2={width}
            y2={linkY}
            stroke="#34D399"
            strokeOpacity="0.55"
            strokeDasharray="6 4"
            strokeWidth="1.2"
          />
        )}

        <path d={buildArea((p) => p.ul)} fill="url(#ulGrad)" />
        <path d={buildPath((p) => p.ul)} fill="none" stroke="#A78BFA" strokeWidth="1.5" />

        <path d={buildArea((p) => p.dl)} fill="url(#dlGrad)" />
        <path d={buildPath((p) => p.dl)} fill="none" stroke="#22D3EE" strokeWidth="2" />
      </svg>
    </section>
  );
}
