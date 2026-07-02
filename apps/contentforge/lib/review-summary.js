export function costLabelFromSpend(spend) {
  if (!spend || spend.available !== true) return null;
  var value = Number(spend.todayUsd);
  if (!Number.isFinite(value)) return null;
  return formatUsd(value);
}

export function formatUsd(value) {
  var amount = Number(value);
  if (!Number.isFinite(amount)) return null;
  var digits = amount >= 10 || amount === 0 ? 0 : 2;
  return "$" + amount.toFixed(digits).replace(/\.00$/, "");
}

export function showSummarySkeleton({ scanPending, files }) {
  return scanPending === true && (!Array.isArray(files) || files.length === 0);
}
