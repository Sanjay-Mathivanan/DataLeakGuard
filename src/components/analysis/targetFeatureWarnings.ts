export interface PotentialTargetDerivedFeature {
  columnName: string;
  signals: string[];
}

const DERIVED_NAME_MARKERS = new Set([
  'after',
  'copied',
  'copy',
  'derived',
  'duplicate',
  'followup',
  'post',
  'proxy',
]);

function nameTokens(name: string): string[] {
  return name
    .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
    .toLocaleLowerCase()
    .split(/[^a-z0-9]+/)
    .filter(Boolean);
}

function canonicalTargetToken(token: string): string {
  if (/^readmi(ssion|tted|t)/.test(token)) return 'readmit';
  return token;
}

export function findPotentialTargetDerivedFeatures(
  targetColumn: string,
  availableColumnNames: string[]
): PotentialTargetDerivedFeature[] {
  const targetName = targetColumn.trim();
  if (!targetName) return [];
  const targetTokens = new Set(nameTokens(targetName).map(canonicalTargetToken));

  return availableColumnNames
    .filter((columnName) => columnName !== targetName)
    .flatMap((columnName) => {
      const tokens = nameTokens(columnName);
      const markers = tokens.filter((token) => DERIVED_NAME_MARKERS.has(token));
      const sharesTargetTerm = tokens.some((token) =>
        targetTokens.has(canonicalTargetToken(token))
      );
      const signals = [
        ...(markers.length > 0
          ? [`Name contains possible derived/post-outcome marker(s): ${[...new Set(markers)].join(', ')}.`]
          : []),
        ...(sharesTargetTerm
          ? ['Name shares a term with the selected target.']
          : []),
      ];
      return signals.length > 0 ? [{ columnName, signals }] : [];
    });
}
