import { Dataset } from '../../types';

export type ProfileColumn = NonNullable<Dataset['columns']>[number];
export type ProfileColumnKind = 'numeric' | 'categorical' | 'datetime' | 'other';
export type ProfileSortKey = 'name' | 'type' | 'missing' | 'missingPercent' | 'unique';

export function classifyProfileColumn(column: ProfileColumn): ProfileColumnKind {
  const type = column.type.trim().toLowerCase();
  if (/(datetime|timestamp|date)/.test(type)) return 'datetime';
  if (/^(u?int|float|double|decimal|numeric|number)/.test(type)) return 'numeric';
  if (
    column.statistics?.kind === 'categorical'
    || /^(object|string|str|bool|boolean|category)/.test(type)
  ) return 'categorical';
  return 'other';
}

export function isHighCardinality(
  column: ProfileColumn,
  rowCount: number | null | undefined
): boolean | null {
  if (typeof column.uniqueCount !== 'number' || typeof rowCount !== 'number' || rowCount <= 0) {
    return null;
  }
  return column.uniqueCount > 20 && column.uniqueCount / rowCount >= 0.5;
}

export function filterAndSortFeatureColumns(
  columns: ProfileColumn[],
  options: {
    search?: string;
    kind?: ProfileColumnKind | '';
    missing?: 'with' | 'without' | '';
    cardinality?: 'high' | 'normal' | '';
    rowCount?: number | null;
    sortBy?: ProfileSortKey;
    direction?: 'asc' | 'desc';
  } = {}
): ProfileColumn[] {
  const search = options.search?.trim().toLocaleLowerCase() ?? '';
  const result = columns.filter((column) => {
    if (search && !column.name.toLocaleLowerCase().includes(search)) return false;
    if (options.kind && classifyProfileColumn(column) !== options.kind) return false;
    if (options.missing === 'with' && !(typeof column.missingCount === 'number' && column.missingCount > 0)) return false;
    if (options.missing === 'without' && !(column.missingCount === 0)) return false;
    if (options.cardinality) {
      const high = isHighCardinality(column, options.rowCount);
      if (high === null || (options.cardinality === 'high' ? !high : high)) return false;
    }
    return true;
  });

  const key = options.sortBy ?? 'name';
  const direction = options.direction === 'desc' ? -1 : 1;
  return result.sort((left, right) => {
    let comparison = 0;
    if (key === 'missingPercent') {
      const leftValue = typeof left.missingCount === 'number' && options.rowCount
        ? left.missingCount / options.rowCount
        : null;
      const rightValue = typeof right.missingCount === 'number' && options.rowCount
        ? right.missingCount / options.rowCount
        : null;
      comparison = compareNullableNumbers(leftValue, rightValue);
    } else if (key === 'missing') {
      comparison = compareNullableNumbers(
        typeof left.missingCount === 'number' ? left.missingCount : null,
        typeof right.missingCount === 'number' ? right.missingCount : null,
      );
    } else if (key === 'unique') {
      comparison = compareNullableNumbers(
        typeof left.uniqueCount === 'number' ? left.uniqueCount : null,
        typeof right.uniqueCount === 'number' ? right.uniqueCount : null,
      );
    } else if (key === 'type') {
      comparison = classifyProfileColumn(left).localeCompare(classifyProfileColumn(right));
    } else {
      comparison = left.name.localeCompare(right.name, undefined, { sensitivity: 'base' });
    }
    return comparison * direction || left.name.localeCompare(right.name);
  });
}

function compareNullableNumbers(left: number | null, right: number | null): number {
  if (left === null && right === null) return 0;
  if (left === null) return 1;
  if (right === null) return -1;
  return left - right;
}

export function summarizeFeatureColumns(
  columns: ProfileColumn[],
  rowCount: number | null | undefined
) {
  const count = (kind: ProfileColumnKind) =>
    columns.filter((column) => classifyProfileColumn(column) === kind).length;
  const missingAvailable = columns.every((column) => typeof column.missingCount === 'number');
  return {
    totalColumns: columns.length,
    numericColumns: count('numeric'),
    categoricalColumns: count('categorical'),
    datetimeColumns: count('datetime'),
    totalMissing: missingAvailable
      ? columns.reduce((total, column) => total + column.missingCount, 0)
      : null,
    columnsWithMissing: missingAvailable
      ? columns.filter((column) => column.missingCount > 0).length
      : null,
    rowCount: typeof rowCount === 'number' ? rowCount : null,
  };
}
