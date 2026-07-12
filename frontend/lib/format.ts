const nf = new Intl.NumberFormat("en-US");
const cf = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
});

export const fmtNum = (n: number) => nf.format(n);
export const fmtMoney = (n: number) => cf.format(n);
export const fmtPct = (fraction: number) =>
  `${(fraction * 100).toFixed(fraction * 100 < 10 ? 1 : 0)}%`;

export function fmtDate(iso: string): string {
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

export function fmtDateTime(iso: string): string {
  return new Date(iso).toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export const fmtShortDate = (iso: string) => {
  const [, m, d] = iso.slice(0, 10).split("-").map(Number);
  return `${m}/${d}`;
};
