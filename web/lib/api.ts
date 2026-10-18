export type Entry = {
  id: number;
  account_id?: number | null;
  date: string;
  type: "income" | "expense";
  amount: string;
  currency: string;
  category: string;
  description: string;
  /** Only synthetic preview descriptions have translation keys. */
  demoDescription?: string;
};
export type Profile = {
  language: "uz" | "ru" | null;
  language_url: string | null;
  bot_url: string | null;
  first_name: string;
  username: string | null;
  currency: string;
  timezone?: string;
  week_start?: number;
  quick_categories?: string[];
};
export type Summary = {
  balance: string;
  income: string;
  expense: string;
  count: number;
  currency: string;
  start: string;
  end: string;
  daily: { date: string; income: string; expense: string }[];
  categories: { name: string; amount: string }[];
};
export type EntryInput = Pick<
  Entry,
  "date" | "type" | "amount" | "category" | "description"
> & {account_id?: number};

export const API = process.env.NEXT_PUBLIC_API_BASE_URL ?? "";

export async function request<T>(
  path: string,
  options?: RequestInit,
): Promise<T> {
  const token =
    typeof window !== "undefined" ? localStorage.getItem("mone_token") : null;
  const initData =
    typeof window !== "undefined"
      ? (window as any).Telegram?.WebApp?.initData
      : null;
  const authHeaders: Record<string, string> = {};
  if (token) authHeaders["Authorization"] = `Bearer ${token}`;
  if (initData) authHeaders["X-Telegram-Init-Data"] = initData;

  const response = await fetch(`${API}/api${path}`, {
    ...options,
    credentials: "include",
    cache: "no-store",
    headers: {
      "Content-Type": "application/json",
      ...authHeaders,
      ...options?.headers,
    },
  });
  if (!response.ok) {
    let message = "Server bilan bog‘lanib bo‘lmadi.";
    try {
      const body = await response.json();
      message =
        typeof body.detail === "string"
          ? body.detail
          : "Kiritilgan ma’lumotlarni tekshiring.";
    } catch {
      /* Keep a useful message for proxy errors. */
    }
    throw new Error(message);
  }
  return response.status === 204 ? (undefined as T) : response.json();
}

export const categories = [
  "Еда",
  "Транспорт",
  "Жильё",
  "Одежда",
  "Развлечения",
  "Здоровье",
  "Образование",
  "Работа",
  "Связь",
  "Подарки",
  "Другое",
  "Зарплата",
  "Инвестиции",
  "Фриланс",
  "Переводы",
  "Сверка",
];
export const labels: Record<string, string> = {
  Еда: "Oziq-ovqat",
  Транспорт: "Transport",
  Жильё: "Uy-joy",
  Жилье: "Uy-joy",
  Одежда: "Kiyim",
  Развлечения: "Hordiq",
  Здоровье: "Salomatlik",
  Образование: "Ta’lim",
  Работа: "Ish",
  Связь: "Aloqa",
  Подарки: "Sovg‘alar",
  Другое: "Boshqa",
  Зарплата: "Maosh",
  Инвестиции: "Investitsiya",
  Фриланс: "Frilans",
  Переводы: "O‘tkazmalar",
  Сверка: "Balansni tekislash",
  Пополнение: "To‘ldirish",
  Кафе: "Kafe",
  Такси: "Taksi",
};
export const categoryLabel = (name: string) => labels[name] ?? name;
export const money = (amount: number | string) =>
  new Intl.NumberFormat("uz-UZ", { maximumFractionDigits: 2 }).format(
    Number(amount),
  );
export const localDay = (timeZone = "Asia/Tashkent") =>
  new Intl.DateTimeFormat("en-CA", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());

export function monthPeriod(month: string) {
  const [year, number] = month.split("-").map(Number);
  const last = new Date(Date.UTC(year, number, 0)).getUTCDate();
  return { start: `${month}-01`, end: `${month}-${last}` };
}

// Synthetic preview records. These never enter PostgreSQL or the user's ledger.
export function demoEntries(): Entry[] {
  const spending = [
    ["Еда", "Korzinka", 185000],
    ["Транспорт", "Yandex Go", 24000],
    ["Еда", "Nonushta va qahva", 42000],
    ["Связь", "Internet uchun to‘lov", 150000],
    ["Развлечения", "Do‘stlar bilan kino", 95000],
    ["Здоровье", "Dorixona", 68000],
    ["Транспорт", "Avtobus va metro", 8000],
    ["Еда", "Haftalik xaridlar", 265000],
    ["Образование", "Kitoblar", 120000],
    ["Жильё", "Kommunal to‘lov", 235000],
    ["Одежда", "Kiyim xaridi", 320000],
    ["Еда", "Tushlik", 55000],
    ["Транспорт", "Taksi", 32000],
    ["Развлечения", "Musiqa obunasi", 35000],
    ["Еда", "Oziq-ovqat", 178000],
    ["Еда", "Qahva", 28000],
    ["Подарки", "Tug‘ilgan kun sovg‘asi", 180000],
    ["Транспорт", "Yandex Go", 26000],
  ] as const;
  const entries: Entry[] = [
    {
      id: 1,
      date: "2026-10-01",
      type: "income",
      amount: "7500000",
      category: "Зарплата",
      description: "Oylik maosh",
      currency: "UZS",
    },
    {
      id: 2,
      date: "2026-10-12",
      type: "income",
      amount: "1200000",
      category: "Фриланс",
      description: "Dizayn loyihasi",
      currency: "UZS",
    },
    ...spending.map(([category, description, amount], i): Entry => ({
      id: i + 3,
      date: `2026-10-${String(i + 1).padStart(2, "0")}`,
      type: "expense",
      amount: String(amount),
      currency: "UZS",
      category,
      description,
    })),
  ];
  return entries.map((entry) => ({
    ...entry,
    demoDescription: entry.description,
  }));
}

export function summarize(
  entries: Entry[],
  start: string,
  end: string,
): Summary {
  const selected = entries.filter((t) => t.date >= start && t.date <= end);
  const sum = (list: Entry[], kind: Entry["type"]) =>
    list
      .filter((t) => t.type === kind)
      .reduce((s, t) => s + Number(t.amount), 0);
  const grouped: Record<string, number> = {};
  const daily: Record<
    string,
    { date: string; income: string; expense: string }
  > = {};
  for (const tx of selected) {
    if (tx.type === "expense")
      grouped[tx.category] = (grouped[tx.category] ?? 0) + Number(tx.amount);
    daily[tx.date] ??= { date: tx.date, income: "0", expense: "0" };
    daily[tx.date][tx.type] = String(
      Number(daily[tx.date][tx.type]) + Number(tx.amount),
    );
  }
  return {
    balance: String(sum(entries, "income") - sum(entries, "expense")),
    income: String(sum(selected, "income")),
    expense: String(sum(selected, "expense")),
    count: selected.length,
    currency: "UZS",
    start,
    end,
    daily: Object.values(daily),
    categories: Object.entries(grouped)
      .sort((a, b) => b[1] - a[1])
      .map(([name, amount]) => ({ name, amount: String(amount) })),
  };
}
