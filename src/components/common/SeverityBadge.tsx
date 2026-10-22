import React from 'react';

interface SeverityBadgeProps {
  severity: string | null | undefined;
  className?: string;
  size?: 'sm' | 'md';
}

export const SeverityBadge: React.FC<SeverityBadgeProps> = ({ severity, className = '', size = 'md' }) => {
  const isSm = size === 'sm';
  const sizeClasses = isSm ? 'text-[10px] px-1.5 py-0.5' : 'text-xs px-2 py-0.5';
  const normalizedSeverity = severity?.trim().toLowerCase();
  const displaySeverity =
    normalizedSeverity === 'critical' ? 'Critical' :
    normalizedSeverity === 'high' ? 'High' :
    normalizedSeverity === 'medium' ? 'Medium' :
    normalizedSeverity === 'low' ? 'Low' :
    severity?.trim() || 'Unknown';

  switch (normalizedSeverity) {
    case 'critical':
      return (
        <span className={`inline-flex items-center font-mono font-semibold uppercase tracking-wider rounded bg-rose-50 text-rose-800 border border-rose-200 ${sizeClasses} ${className}`}>
          {displaySeverity}
        </span>
      );
    case 'high':
      return (
        <span className={`inline-flex items-center font-mono font-semibold uppercase tracking-wider rounded bg-orange-50 text-orange-800 border border-orange-200 ${sizeClasses} ${className}`}>
          {displaySeverity}
        </span>
      );
    case 'medium':
      return (
        <span className={`inline-flex items-center font-mono font-medium uppercase tracking-wider rounded bg-amber-50 text-amber-800 border border-amber-200 ${sizeClasses} ${className}`}>
          {displaySeverity}
        </span>
      );
    case 'low':
      return (
        <span className={`inline-flex items-center font-mono font-medium uppercase tracking-wider rounded bg-slate-100 text-slate-700 border border-slate-200 ${sizeClasses} ${className}`}>
          {displaySeverity}
        </span>
      );
    default:
      return (
        <span className={`inline-flex items-center font-mono font-medium uppercase tracking-wider rounded bg-slate-100 text-slate-700 border border-slate-200 ${sizeClasses} ${className}`}>
          {displaySeverity}
        </span>
      );
  }
};
