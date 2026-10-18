"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  ArrowDownLeft,
  ArrowRight,
  ArrowUpRight,
  BarChart3,
  CalendarDays,
  Check,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  CircleHelp,
  Download,
  Edit3,
  LayoutDashboard,
  ListFilter,
  LogOut,
  Menu,
  Plus,
  Search,
  Send,
  ShoppingBag,
  SlidersHorizontal,
  Sparkles,
  Trash2,
  Wallet,
  X,
} from "lucide-react";
import {
  categories,
  categoryLabel,
  demoEntries,
  Entry,
  EntryInput,
  localDay,
  money,
  monthPeriod,
  Profile,
  request,
  Summary,
  summarize,
} from "../lib/api";

import { CategoryIcon } from "../components/category-icon";
import { EntryModal } from "../components/entry-sheet";
import { Modal } from "../components/dialog";
import { MobileTransactions } from "../components/mobile-transactions";

type View = "dashboard" | "transactions" | "analytics" | "settings";
const titles: Record<View, string> = {
  dashboard: "Umumiy ko‘rinish",
  transactions: "Operatsiyalar",
  analytics: "Tahlil va hisobotlar",
  settings: "Sozlamalar",
};
const months = [
  "Yanvar",
  "Fevral",
  "Mart",
  "Aprel",
  "May",
  "Iyun",
  "Iyul",
  "Avgust",
  "Sentabr",
  "Oktabr",
  "Noyabr",
  "Dekabr",
];
const chartColors = [
  "#147d64",
  "#7bb398",
  "#b0cdb5",
  "#d4b98b",
  "#a1b1c4",
  "#d1d8df",
];

export default function Page() {
  const [view, setView] = useState<View>("dashboard");
  const [sidebar, setSidebar] = useState(false);
  const [user, setUser] = useState<Profile | null>(null);
  const [demo, setDemo] = useState<Entry[]>(demoEntries);
  const [month, setMonth] = useState("2026-10");
  const [summary, setSummary] = useState<Summary | null>(null);
  const [items, setItems] = useState<Entry[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(0);
  const [search, setSearch] = useState("");
  const [searchTerm, setSearchTerm] = useState("");
  const [kind, setKind] = useState("");
  const [loading, setLoading] = useState(false);
  const [revision, setRevision] = useState(0);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [editor, setEditor] = useState<Entry | "new" | null>(null);
  const [deleting, setDeleting] = useState<Entry | null>(null);
  const [saving, setSaving] = useState(false);
  const [login, setLogin] = useState<{ url: string; code: string } | null>(
    null,
  );
  const [loginBusy, setLoginBusy] = useState(false);
  const [categoryOptions, setCategoryOptions] = useState(categories);
  const [exporting, setExporting] = useState(false);
  const { start, end } = monthPeriod(month);
  const [year, monthNumber] = month.split("-").map(Number);
  const periodLabel = `${months[monthNumber - 1]}, ${year}`;

  const reportError = (e: unknown) =>
    setError(e instanceof Error ? e.message : "Xatolik yuz berdi.");
  const refresh = useCallback(() => setRevision((r) => r + 1), []);

  useEffect(() => {
    const controller = new AbortController();
    const tg =
      typeof window !== "undefined"
        ? (window as any).Telegram?.WebApp
        : undefined;

    if (tg) {
      try {
        tg.ready();
        tg.expand();
      } catch {}
    }

    const init = async () => {
      if (tg?.initData) {
        try {
          const authRes = await request<{
            status: string;
            token: string;
            user: Profile;
          }>("/auth/telegram/webapp", {
            method: "POST",
            body: JSON.stringify({ init_data: tg.initData }),
            signal: controller.signal,
          });
          if (authRes?.token) {
            localStorage.setItem("mone_token", authRes.token);
          }
          if (authRes?.user) {
            setUser(authRes.user);
            setMonth(localDay().slice(0, 7));
            return;
          }
        } catch (e) {
          console.error("TMA auth error:", e);
        }
      }

      try {
        const profile = await request<Profile>("/me", {
          signal: controller.signal,
        });
        setUser(profile);
        setMonth(localDay().slice(0, 7));
      } catch {
        /* Unauthenticated visitors remain in explicitly labelled demo mode. */
      }
    };

    init();
    return () => controller.abort();
  }, []);

  useEffect(() => {
    const id = setTimeout(() => {
      setSearchTerm(search);
      setPage(0);
    }, 250);
    return () => clearTimeout(id);
  }, [search]);
  useEffect(() => {
    if (!notice) return;
    const id = setTimeout(() => setNotice(""), 4500);
    return () => clearTimeout(id);
  }, [notice]);

  useEffect(() => {
    if (!user) return;
    const update = () => {
      if (document.visibilityState === "visible") refresh();
    };
    const timer = setInterval(update, 30000);
    window.addEventListener("focus", update);
    return () => {
      clearInterval(timer);
      window.removeEventListener("focus", update);
    };
  }, [user, refresh]);

  useEffect(() => {
    if (!user) {
      setCategoryOptions(categories);
      return;
    }
    const controller = new AbortController();
    request<string[]>("/categories", { signal: controller.signal })
      .then(setCategoryOptions)
      .catch(() => {});
    return () => controller.abort();
  }, [user, revision]);

  useEffect(() => {
    if (!user) {
      const filtered = demo
        .filter(
          (t) =>
            t.date >= start &&
            t.date <= end &&
            (!kind || t.type === kind) &&
            `${t.description} ${t.category} ${categoryLabel(t.category)}`
              .toLocaleLowerCase()
              .includes(searchTerm.toLocaleLowerCase()),
        )
        .sort((a, b) => b.date.localeCompare(a.date) || b.id - a.id);
      setSummary(summarize(demo, start, end));
      setItems(filtered.slice(page * 20, page * 20 + 20));
      setTotal(filtered.length);
      setLoading(false);
      return;
    }
    const controller = new AbortController();
    setLoading(true);
    setError("");
    const params = new URLSearchParams({
      start,
      end,
      search: searchTerm,
      kind,
      offset: String(page * 20),
      limit: "20",
    });
    Promise.all([
      request<Summary>(`/summary?start=${start}&end=${end}`, {
        signal: controller.signal,
      }),
      request<{ items: Entry[]; total: number }>(`/transactions?${params}`, {
        signal: controller.signal,
      }),
    ])
      .then(([nextSummary, nextItems]) => {
        setSummary(nextSummary);
        setItems(nextItems.items);
        setTotal(nextItems.total);
      })
      .catch((e) => {
        if (!controller.signal.aborted) {
          reportError(e);
          setSummary(null);
          setItems([]);
          setTotal(0);
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [user, demo, start, end, kind, searchTerm, page, revision]);

  useEffect(() => {
    if (!login) return;
    let active = true;
    let timeout: ReturnType<typeof setTimeout>;
    const deadline = Date.now() + 300000;
    const poll = async () => {
      try {
        const result = await request<{ status: string; token?: string }>(
          "/auth/telegram/poll",
          { method: "POST" },
        );
        if (!active) return;
        if (result.status === "approved") {
          if (result.token) {
            localStorage.setItem("mone_token", result.token);
          }
          const profile = await request<Profile>("/me");
          if (active) {
            setUser(profile);
            setMonth(localDay().slice(0, 7));
            setLogin(null);
            setNotice("Telegram hisobingiz ulandi.");
          }
          return;
        }
        if (result.status === "expired" || Date.now() >= deadline) {
          setLogin(null);
          setError("Kirish so‘rovi eskirdi. Qayta urinib ko‘ring.");
          return;
        }
        timeout = setTimeout(poll, 2000);
      } catch (e) {
        if (active) {
          setLogin(null);
          reportError(e);
        }
      }
    };
    timeout = setTimeout(poll, 1500);
    return () => {
      active = false;
      clearTimeout(timeout);
    };
  }, [login]);

  const beginLogin = async () => {
    setLoginBusy(true);
    setError("");
    try {
      setLogin(await request("/auth/telegram/request", { method: "POST" }));
    } catch (e) {
      reportError(e);
    } finally {
      setLoginBusy(false);
    }
  };

  const logout = async () => {
    try {
      localStorage.removeItem("mone_token");
      await request("/auth/logout", { method: "POST" });
      setUser(null);
      setMonth("2026-10");
      setPage(0);
      setView("dashboard");
      setNotice("Hisobdan chiqdingiz. Namuna rejimi ochildi.");
    } catch (e) {
      reportError(e);
    }
  };

  function changeMonth(delta: number) {
    const next = new Date(Date.UTC(year, monthNumber - 1 + delta, 1));
    setMonth(next.toISOString().slice(0, 7));
    setPage(0);
  }

  const daily = useMemo(() => {
    const found = new Map(summary?.daily.map((day) => [day.date, day]) ?? []);
    const days = Number(end.slice(-2));
    return Array.from({ length: days }, (_, i) => {
      const date = `${month}-${String(i + 1).padStart(2, "0")}`;
      const entry = found.get(date);
      return {
        day: String(i + 1),
        income: Number(entry?.income ?? 0),
        expense: Number(entry?.expense ?? 0),
      };
    });
  }, [summary, month, end]);

  const openEditor = (entry: Entry | "new") => {
    setError("");
    setEditor(entry);
  };

  const saveEntry = async (data: EntryInput) => {
    setSaving(true);
    setError("");
    try {
      if (user)
        await request(
          editor !== "new" && editor
            ? `/transactions/${editor.id}`
            : "/transactions",
          {
            method: editor === "new" ? "POST" : "PATCH",
            body: JSON.stringify(data),
          },
        );
      else
        setDemo((current) =>
          editor === "new"
            ? [
                ...current,
                {
                  ...data,
                  id: Math.max(0, ...current.map((t) => t.id)) + 1,
                  currency: "UZS",
                },
              ]
            : current.map((t) =>
                t.id === (editor as Entry).id ? { ...t, ...data } : t,
              ),
        );
      setEditor(null);
      setPage(0);
      setMonth(data.date.slice(0, 7));
      setSearch("");
      setSearchTerm("");
      setKind("");
      refresh();
      setNotice(
        user
          ? "Operatsiya saqlandi."
          : "Namuna operatsiyasi saqlandi. Baza o‘zgarmadi.",
      );
    } catch (e) {
      reportError(e);
    } finally {
      setSaving(false);
    }
  };

  const deleteEntry = async () => {
    if (!deleting) return;
    setSaving(true);
    try {
      if (user)
        await request(`/transactions/${deleting.id}`, { method: "DELETE" });
      else setDemo((current) => current.filter((t) => t.id !== deleting.id));
      setDeleting(null);
      setPage(0);
      refresh();
      setNotice("Operatsiya o‘chirildi.");
    } catch (e) {
      reportError(e);
    } finally {
      setSaving(false);
    }
  };

  async function exportCsv() {
    setExporting(true);
    try {
      let rows: Entry[] = [];
      if (!user)
        rows = demo.filter(
          (t) =>
            t.date >= start &&
            t.date <= end &&
            (!kind || t.type === kind) &&
            `${t.description} ${t.category} ${categoryLabel(t.category)}`
              .toLocaleLowerCase()
              .includes(searchTerm.toLocaleLowerCase()),
        );
      else {
        for (let offset = 0; ; offset += 100) {
          const params = new URLSearchParams({
            start,
            end,
            search: searchTerm,
            kind,
            offset: String(offset),
            limit: "100",
          });
          const result = await request<{ items: Entry[]; total: number }>(
            `/transactions?${params}`,
          );
          rows.push(...result.items);
          if (rows.length >= result.total || !result.items.length) break;
        }
      }
      const field = (value: string) => `"${value.replaceAll('"', '""')}"`;
      const csv = [
        ["date", "type", "amount", "currency", "category", "description"],
        ...rows.map((t) => [
          t.date,
          t.type,
          t.amount,
          t.currency,
          t.category,
          t.description,
        ]),
      ]
        .map((row) => row.map(field).join(","))
        .join("\r\n");
      const url = URL.createObjectURL(
        new Blob(["\uFEFF", csv], { type: "text/csv;charset=utf-8" }),
      );
      const a = document.createElement("a");
      a.href = url;
      a.download = `mone-${user ? "" : "namuna-"}${month}.csv`;
      a.click();
      URL.revokeObjectURL(url);
      setNotice(`${rows.length} ta operatsiya eksport qilindi.`);
    } catch (e) {
      reportError(e);
    } finally {
      setExporting(false);
    }
  }

  const navigate = (next: View) => {
    setView(next);
    setSidebar(false);
    setPage(0);
    setSearch("");
    setSearchTerm("");
    setKind("");
  };
  const expense = Number(summary?.expense ?? 0);
  const income = Number(summary?.income ?? 0);
  const currency = summary?.currency ?? user?.currency ?? "UZS";
  const pie = (summary?.categories ?? []).map((c) => ({
    name: categoryLabel(c.name),
    value: Number(c.amount),
  }));

  return (
    <div className="app-shell">
      {sidebar && (
        <button
          className="sidebar-overlay"
          aria-label="Menyuni yopish"
          onClick={() => setSidebar(false)}
        />
      )}
      <aside className={`sidebar ${sidebar ? "open" : ""}`}>
        <a
          className="brand"
          href="#"
          onClick={(e) => {
            e.preventDefault();
            navigate("dashboard");
          }}
        >
          <span className="brand-mark">
            <span />
            <span />
            <span />
          </span>
          mone<span className="brand-dot">.</span>
        </a>
        <div className="workspace">
          <span className="workspace-icon">
            <Wallet size={18} />
          </span>
          <div>
            <strong>Shaxsiy kabinet</strong>
            <span>{user ? user.first_name : "Namuna ma’lumotlari"}</span>
          </div>
          <ChevronDown size={15} />
        </div>
        <span className="nav-label">ASOSIY MENYU</span>
        <nav aria-label="Asosiy navigatsiya">
          {(
            [
              {
                id: "dashboard",
                icon: LayoutDashboard,
                text: "Umumiy ko‘rinish",
              },
              {
                id: "transactions",
                icon: ArrowDownLeft,
                text: "Operatsiyalar",
              },
              {
                id: "analytics",
                icon: BarChart3,
                text: "Tahlil va hisobotlar",
              },
              { id: "settings", icon: SlidersHorizontal, text: "Sozlamalar" },
            ] as const
          ).map(({ id, icon: Icon, text }) => (
            <button
              key={id}
              className={`nav-item ${view === id ? "active" : ""}`}
              onClick={() => navigate(id)}
            >
              <Icon size={19} strokeWidth={1.7} />
              {text}
              {id === "dashboard" && <span className="active-dot" />}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="telegram-card">
            <span className="telegram-icon">
              <Send size={19} />
            </span>
            <strong>Har doim yoningizda</strong>
            <p>
              Xarajatni botga yozing.
              <br />
              Natijani bu yerda ko‘ring.
            </p>
            <button
              onClick={() => (user ? navigate("settings") : beginLogin())}
              disabled={loginBusy}
            >
              {user ? "Ulanishni ko‘rish" : "Telegram bilan ulash"}
              <ArrowUpRight size={15} />
            </button>
          </div>
          <button className="help-link" onClick={() => navigate("settings")}>
            <CircleHelp size={17} />
            Yordam va ma’lumot
          </button>
          <div className="sidebar-profile">
            <span className="avatar">
              {user?.first_name.slice(0, 1) ?? "M"}
            </span>
            <div>
              <strong>{user?.first_name ?? "Mone bilan tanishing"}</strong>
              <span>{user ? "Shaxsiy hisob" : "Namuna rejimi"}</span>
            </div>
            {user ? (
              <button
                className="icon-button"
                onClick={logout}
                aria-label="Hisobdan chiqish"
              >
                <LogOut size={17} />
              </button>
            ) : (
              <span className="small-badge">DEMO</span>
            )}
          </div>
        </div>
      </aside>

      <div className="main-shell">
        <header className="topbar">
          <div className="breadcrumb">
            <button
              className="icon-button mobile-menu"
              onClick={() => setSidebar(true)}
              aria-label="Menyuni ochish"
            >
              <Menu size={21} />
            </button>
            <span>Shaxsiy moliya</span>
            <ChevronRight size={14} />
            <strong>{titles[view]}</strong>
          </div>
          <div className="topbar-actions">
            <span className={`connection ${user ? "connected" : ""}`}>
              <i />
              {user ? "Telegram ulangan" : "Namuna rejimi"}
            </span>
            <span className="topbar-divider" />
            <span className="language" aria-label="Interfeys tili: o‘zbekcha">
              UZ
            </span>
            <span className="avatar small">
              {user?.first_name.slice(0, 1) ?? "M"}
            </span>
          </div>
        </header>
        <main>
          <div className="page-heading">
            <div>
              <div className="eyebrow">MOLIYANGIZ, O‘Z NAZORATINGIZDA</div>
              <h1>
                {titles[view]}
                <span className="heading-dot">.</span>
              </h1>
              <p>
                {view === "dashboard"
                  ? "Kichik odatlar. Katta imkoniyatlar. Pulingiz qayerga ketayotganini biling."
                  : view === "transactions"
                    ? "Har bir kirim va chiqim — barchasi bir joyda."
                    : view === "analytics"
                      ? "Raqamlar ortidagi moliyaviy odatlaringizni kashf eting."
                      : "Shaxsiy kabinetingiz va Telegram bilan ulanish."}
              </p>
            </div>
            <button
              className="button primary"
              onClick={() => openEditor("new")}
            >
              <Plus size={18} />
              Yangi operatsiya
            </button>
          </div>

          {!user && (
            <div className="demo-banner">
              <span>
                <Sparkles size={16} />
                <strong>Namuna rejimi.</strong> Bu haqiqiy hisobingiz emas. O‘z
                ma’lumotlaringiz uchun Telegram orqali kiring.
              </span>
              <button onClick={beginLogin} disabled={loginBusy}>
                {loginBusy ? "Ulanmoqda…" : "Hisobni ulash"}
                <ArrowRight size={15} />
              </button>
            </div>
          )}
          {error && (
            <div className="error-banner" role="alert">
              <span>{error}</span>
              <button
                className="icon-button"
                onClick={() => setError("")}
                aria-label="Xatolikni yopish"
              >
                <X size={17} />
              </button>
            </div>
          )}

          {view !== "settings" && (
            <div className="section-toolbar">
              <div className="period-control">
                <CalendarDays size={16} />
                <label className="sr-only" htmlFor="month">
                  Hisobot oyi
                </label>
                <input
                  id="month"
                  aria-label="Hisobot oyi"
                  type="month"
                  value={month}
                  min="2000-01"
                  max="2100-12"
                  onChange={(e) => {
                    if (e.target.value) {
                      setMonth(e.target.value);
                      setPage(0);
                    }
                  }}
                />
                <span>{periodLabel}</span>
                <ChevronDown size={14} />
              </div>
              <div className="period-nav">
                <button
                  className="icon-button"
                  onClick={() => changeMonth(-1)}
                  aria-label="Oldingi oy"
                >
                  <ChevronLeft size={17} />
                </button>
                <button
                  className="icon-button"
                  onClick={() => {
                    setMonth(user ? localDay().slice(0, 7) : "2026-10");
                    setPage(0);
                  }}
                >
                  Bugun
                </button>
                <button
                  className="icon-button"
                  onClick={() => changeMonth(1)}
                  aria-label="Keyingi oy"
                >
                  <ChevronRight size={17} />
                </button>
              </div>
              <span className="toolbar-note">
                {user
                  ? "Bot bilan umumiy ma’lumotlar"
                  : "2026-yil oktabr uchun sintetik namuna"}
              </span>
            </div>
          )}

          {loading && (
            <div className="loading-panel" role="status">
              <span className="spinner" />
              Ma’lumotlar yuklanmoqda…
            </div>
          )}

          {!loading && view !== "settings" && summary && (
            <>
              <section
                className="stats-grid"
                aria-label="Moliyaviy ko‘rsatkichlar"
              >
                <div className="stat-card balance-card">
                  <div className="stat-heading">
                    Joriy balans
                    <Wallet size={18} />
                  </div>
                  <div className="stat-value">
                    {money(summary.balance)} <span>{currency}</span>
                  </div>
                  <div className="stat-foot">
                    <span className="balance-pill">Barcha davrlar</span>
                    <span>Jami kirim − jami chiqim</span>
                  </div>
                  <div className="balance-decoration" />
                </div>
                <div className="stat-card">
                  <div className="stat-heading">
                    Davrdagi kirim
                    <span className="stat-icon income">
                      <ArrowDownLeft size={17} />
                    </span>
                  </div>
                  <div className="stat-value">
                    {money(summary.income)} <span>{currency}</span>
                  </div>
                  <div className="stat-foot">
                    <span className="dot green" />
                    Tanlangan oy uchun
                  </div>
                </div>
                <div className="stat-card">
                  <div className="stat-heading">
                    Davrdagi chiqim
                    <span className="stat-icon expense">
                      <ArrowUpRight size={17} />
                    </span>
                  </div>
                  <div className="stat-value">
                    {money(summary.expense)} <span>{currency}</span>
                  </div>
                  <div className="stat-foot">
                    <span className="dot orange" />
                    Tanlangan oy uchun
                  </div>
                </div>
                <div className="stat-card">
                  <div className="stat-heading">
                    Davr natijasi
                    <span className="stat-icon neutral">
                      <BarChart3 size={17} />
                    </span>
                  </div>
                  <div className="stat-value">
                    {money(income - expense)} <span>{currency}</span>
                  </div>
                  <div className="stat-foot">
                    <span className="result-pill">
                      {summary.count} ta operatsiya
                    </span>
                    <span>Kirim − chiqim</span>
                  </div>
                </div>
              </section>

              {(view === "dashboard" || view === "analytics") && (
                <div className="charts-grid">
                  <section className="panel cashflow-panel">
                    <div className="panel-heading">
                      <div>
                        <h2>Pul oqimi</h2>
                        <p>Kirim va chiqimlaringiz kunlar kesimida</p>
                      </div>
                      <div className="chart-legend">
                        <span>
                          <i className="legend-income" />
                          Kirim
                        </span>
                        <span>
                          <i className="legend-expense" />
                          Chiqim
                        </span>
                      </div>
                    </div>
                    <div
                      className="cashflow-chart"
                      role="img"
                      aria-label={`${periodLabel}: kunlik kirim va chiqim, ${currency}`}
                    >
                      <ResponsiveContainer width="100%" height="100%">
                        <AreaChart
                          data={daily}
                          margin={{ top: 12, right: 12, bottom: 3, left: -12 }}
                        >
                          <CartesianGrid
                            vertical={false}
                            stroke="#edf0ee"
                            strokeDasharray="4 4"
                          />
                          <XAxis
                            dataKey="day"
                            tickLine={false}
                            axisLine={false}
                            minTickGap={22}
                            tick={{ fontSize: 11, fill: "#83908a" }}
                            tickMargin={12}
                          />
                          <YAxis
                            tickLine={false}
                            axisLine={false}
                            tick={{ fontSize: 11, fill: "#83908a" }}
                            tickFormatter={(v) =>
                              Number(v) >= 1000000
                                ? `${Number(v) / 1000000} mln`
                                : `${Number(v) / 1000} ming`
                            }
                          />
                          <Tooltip
                            formatter={(v, name) => [
                              `${money(Number(v))} ${currency}`,
                              name === "income" ? "Kirim" : "Chiqim",
                            ]}
                            labelFormatter={(v) =>
                              `${v}-${months[monthNumber - 1].toLowerCase()}`
                            }
                            contentStyle={{
                              borderRadius: 12,
                              border: "1px solid #e6ebe8",
                              fontSize: 12,
                            }}
                          />
                          <Area
                            type="monotone"
                            dataKey="income"
                            stroke="#24896c"
                            fill="#e4f2eb"
                            strokeWidth={2.5}
                          />
                          <Area
                            type="monotone"
                            dataKey="expense"
                            stroke="#d3a165"
                            fill="#faf2e6"
                            strokeWidth={2}
                          />
                        </AreaChart>
                      </ResponsiveContainer>
                    </div>
                    <div className="chart-caption">
                      <span>Kun / {periodLabel}</span>
                      <span>Miqdor ({currency})</span>
                    </div>
                  </section>
                  <section className="panel category-panel">
                    <div className="panel-heading">
                      <div>
                        <h2>Xarajatlar tarkibi</h2>
                        <p>Pulingiz nimalarga sarflandi?</p>
                      </div>
                      <ShoppingBag size={18} className="muted-icon" />
                    </div>
                    {pie.length ? (
                      <>
                        <div className="donut-chart">
                          <ResponsiveContainer width="100%" height="100%">
                            <PieChart>
                              <Pie
                                data={pie}
                                dataKey="value"
                                innerRadius={67}
                                outerRadius={87}
                                paddingAngle={3}
                                stroke="none"
                              >
                                {pie.map((_, i) => (
                                  <Cell
                                    key={i}
                                    fill={
                                      chartColors[
                                        Math.min(i, chartColors.length - 1)
                                      ]
                                    }
                                  />
                                ))}
                              </Pie>
                              <Tooltip
                                formatter={(v) =>
                                  `${money(Number(v))} ${currency}`
                                }
                              />
                            </PieChart>
                          </ResponsiveContainer>
                          <div className="donut-label">
                            <span>Jami chiqim</span>
                            <strong>{money(expense)}</strong>
                            <small>{currency}</small>
                          </div>
                        </div>
                        <div className="category-legend">
                          {pie.slice(0, 4).map((c, i) => (
                            <div key={c.name}>
                              <span>
                                <i style={{ background: chartColors[i] }} />
                                {c.name}
                              </span>
                              <strong>
                                {expense
                                  ? ((c.value / expense) * 100).toFixed(1)
                                  : 0}
                                %
                              </strong>
                            </div>
                          ))}
                        </div>
                        {pie.length > 4 && (
                          <button
                            className="text-button category-more"
                            onClick={() => navigate("analytics")}
                          >
                            Barcha {pie.length} ta kategoriya
                            <ArrowRight size={14} />
                          </button>
                        )}
                      </>
                    ) : (
                      <div className="empty-chart">
                        <ShoppingBag size={28} />
                        <p>Bu davrda xarajatlar yo‘q.</p>
                      </div>
                    )}
                  </section>
                </div>
              )}

              {view === "analytics" && (
                <section className="panel breakdown">
                  <div className="panel-heading">
                    <div>
                      <h2>Kategoriyalar bo‘yicha batafsil</h2>
                      <p>
                        {periodLabel} · {currency}
                      </p>
                    </div>
                  </div>
                  {summary.categories.length ? (
                    summary.categories.map((cat, i) => (
                      <div className="breakdown-row" key={cat.name}>
                        <span className="category-bubble">
                          <CategoryIcon name={cat.name} />
                        </span>
                        <span>{categoryLabel(cat.name)}</span>
                        <div className="bar-track">
                          <div
                            style={{
                              width: `${expense ? (Number(cat.amount) / expense) * 100 : 0}%`,
                              background:
                                chartColors[
                                  Math.min(i, chartColors.length - 1)
                                ],
                            }}
                          />
                        </div>
                        <strong>
                          {money(cat.amount)} <small>{currency}</small>
                        </strong>
                      </div>
                    ))
                  ) : (
                    <p className="empty-copy">
                      Tanlangan davrda xarajatlar yo‘q.
                    </p>
                  )}
                </section>
              )}

              {(view === "dashboard" || view === "transactions") && (
                <section className="panel transactions-panel">
                  <div className="panel-heading">
                    <div>
                      <h2>
                        {view === "dashboard"
                          ? "So‘nggi operatsiyalar"
                          : "Barcha operatsiyalar"}
                        <span className="count-pill">{total}</span>
                      </h2>
                      <p>
                        {view === "dashboard"
                          ? "Moliyaviy tarixingizga qisqa nazar"
                          : "Tanlangan davr bo‘yicha yozuvlar"}
                      </p>
                    </div>
                    {view === "dashboard" ? (
                      <button
                        className="text-button"
                        onClick={() => navigate("transactions")}
                      >
                        Barchasini ko‘rish
                        <ArrowRight size={15} />
                      </button>
                    ) : (
                      <button
                        className="button secondary compact"
                        onClick={exportCsv}
                        disabled={exporting || !total}
                      >
                        <Download size={16} />
                        {exporting ? "Tayyorlanmoqda…" : "CSV eksport"}
                      </button>
                    )}
                  </div>
                  {view === "transactions" && (
                    <div className="table-filters">
                      <label className="search-field">
                        <Search size={16} />
                        <input
                          aria-label="Operatsiyalarni qidirish"
                          placeholder="Tavsif yoki kategoriya bo‘yicha qidirish…"
                          value={search}
                          onChange={(e) => setSearch(e.target.value)}
                        />
                      </label>
                      <label className="type-filter">
                        <ListFilter size={15} />
                        <select
                          aria-label="Operatsiya turi"
                          value={kind}
                          onChange={(e) => {
                            setKind(e.target.value);
                            setPage(0);
                          }}
                        >
                          <option value="">Barcha turlar</option>
                          <option value="income">Kirimlar</option>
                          <option value="expense">Chiqimlar</option>
                        </select>
                      </label>
                    </div>
                  )}
                  <MobileTransactions
                    items={items.slice(0, view === "dashboard" ? 5 : 20)}
                    onEdit={openEditor}
                  />
                  <div className="table-scroll">
                    <table>
                      <thead>
                        <tr>
                          <th>OPERATSIYA</th>
                          <th>KATEGORIYA</th>
                          <th>SANA</th>
                          <th className="amount-column">SUMMA</th>
                          <th>
                            <span className="sr-only">Amallar</span>
                          </th>
                        </tr>
                      </thead>
                      <tbody>
                        {items
                          .slice(0, view === "dashboard" ? 5 : 20)
                          .map((tx) => (
                            <tr key={tx.id}>
                              <td>
                                <div className="transaction-name">
                                  <span
                                    className={`category-bubble ${tx.type === "income" ? "income-bubble" : ""}`}
                                  >
                                    <CategoryIcon name={tx.category} />
                                  </span>
                                  <div>
                                    <strong>
                                      {tx.description ||
                                        categoryLabel(tx.category)}
                                    </strong>
                                    <span>
                                      {tx.type === "income"
                                        ? "Kirim"
                                        : "Chiqim"}
                                    </span>
                                  </div>
                                </div>
                              </td>
                              <td>
                                <span className="category-tag">
                                  {categoryLabel(tx.category)}
                                </span>
                              </td>
                              <td className="date-cell">
                                {tx.date.split("-").reverse().join(".")}
                              </td>
                              <td
                                className={`amount-cell ${tx.type === "income" ? "positive" : ""}`}
                              >
                                {tx.type === "income" ? "+" : "−"}
                                {money(tx.amount)} <small>{tx.currency}</small>
                              </td>
                              <td>
                                <div className="row-actions">
                                  <button
                                    className="icon-button"
                                    aria-label={`${tx.description || tx.category} operatsiyasini tahrirlash`}
                                    onClick={() => openEditor(tx)}
                                  >
                                    <Edit3 size={15} />
                                  </button>
                                  <button
                                    className="icon-button delete-action"
                                    aria-label={`${tx.description || tx.category} operatsiyasini o‘chirish`}
                                    onClick={() => setDeleting(tx)}
                                  >
                                    <Trash2 size={15} />
                                  </button>
                                </div>
                              </td>
                            </tr>
                          ))}
                      </tbody>
                    </table>
                  </div>
                  {!items.length && (
                    <div className="empty-state">
                      <Wallet size={30} />
                      <h3>Operatsiyalar topilmadi</h3>
                      <p>
                        Boshqa oy yoki filtrni tanlang. Yangi yozuv ham
                        qo‘shishingiz mumkin.
                      </p>
                      <button
                        className="button secondary compact"
                        onClick={() => openEditor("new")}
                      >
                        <Plus size={15} />
                        Operatsiya qo‘shish
                      </button>
                    </div>
                  )}
                  {view === "transactions" && total > 20 && (
                    <div className="pagination">
                      <span>
                        {page * 20 + 1}–{Math.min((page + 1) * 20, total)} /{" "}
                        {total}
                      </span>
                      <button
                        className="button secondary compact"
                        disabled={!page}
                        onClick={() => setPage((p) => p - 1)}
                      >
                        <ChevronLeft size={15} />
                        Oldingi
                      </button>
                      <button
                        className="button secondary compact"
                        disabled={(page + 1) * 20 >= total}
                        onClick={() => setPage((p) => p + 1)}
                      >
                        Keyingi
                        <ChevronRight size={15} />
                      </button>
                    </div>
                  )}
                </section>
              )}

              {view === "dashboard" && (
                <div className="bottom-note">
                  <span className="note-icon">
                    <Sparkles size={20} />
                  </span>
                  <div>
                    <strong>
                      Har bir yozuv — moliyaviy aniqlik sari bir qadam.
                    </strong>
                    <p>
                      Telegram botga matn yoki ovoz yuboring. Tasdiqlangan
                      operatsiyalar kabinetingizda ham ko‘rinadi.
                    </p>
                  </div>
                  <button
                    className="text-button"
                    onClick={() => navigate("settings")}
                  >
                    Batafsil
                    <ArrowRight size={15} />
                  </button>
                </div>
              )}
            </>
          )}

          {view === "settings" && (
            <div className="settings-grid">
              <section className="panel settings-panel">
                <div className="settings-icon">
                  <Send size={25} />
                </div>
                <h2>Telegram bilan bitta hisob</h2>
                <p>
                  Botda qo‘shilgan operatsiyalar website’da ko‘rinadi.
                  Website’da kiritilgan o‘zgarishlar bot hisobotlariga ham
                  ta’sir qiladi.
                </p>
                <dl>
                  <div>
                    <dt>Holat</dt>
                    <dd>{user ? "Ulangan" : "Ulanmagan"}</dd>
                  </div>
                  <div>
                    <dt>Foydalanuvchi</dt>
                    <dd>{user?.first_name ?? "Namuna rejimi"}</dd>
                  </div>
                  <div>
                    <dt>Asosiy valyuta</dt>
                    <dd>{user?.currency ?? "UZS"}</dd>
                  </div>
                  <div>
                    <dt>Vaqt zonasi</dt>
                    <dd>Asia/Tashkent</dd>
                  </div>
                </dl>
                <button
                  className="button primary"
                  onClick={user ? logout : beginLogin}
                  disabled={loginBusy}
                >
                  {user ? <LogOut size={17} /> : <Send size={17} />}
                  {user ? "Hisobdan chiqish" : "Telegram orqali kirish"}
                </button>
              </section>
              <section className="panel settings-panel">
                <div className="settings-icon light">
                  <Download size={24} />
                </div>
                <h2>Mavjud tarixni ko‘chirish</h2>
                <p>
                  CSV import hozir Telegram botda mavjud. Botga{" "}
                  <code>/import</code> yuboring, CSV faylni yuklang va oldindan
                  ko‘rish natijasini tasdiqlang.
                </p>
                <ul className="settings-list">
                  <li>
                    <Check size={16} />
                    Asl sanalar va summalar saqlanadi
                  </li>
                  <li>
                    <Check size={16} />
                    Kategoriyalar fayldan olinadi
                  </li>
                  <li>
                    <Check size={16} />
                    Tasdiqlashdan oldin tekshirish mumkin
                  </li>
                  <li>
                    <Check size={16} />
                    Bir faylni takror import qilish bloklanadi
                  </li>
                </ul>
                <p className="settings-fine">
                  Limit: 1 MB, 2000 ta operatsiya, asosiy valyuta. Website’dan
                  import keyingi bosqichda qo‘shiladi.
                </p>
              </section>
              <section className="panel settings-panel wide">
                <h2>Birinchi versiya haqida</h2>
                <p>
                  Hozir dashboard, operatsiyalar, tahlil, CSV eksport va
                  Telegram orqali kirish ishlaydi. Budjetlar, alohida karta
                  hisoblari va jamg‘arma maqsadlari keyingi bosqichga
                  rejalashtirilgan.
                </p>
                <p className="settings-fine">
                  Balans mavjud botdagi barcha kirim va chiqimlardan
                  hisoblanadi. Balansni tekislash yozuvlari ham shu tarixga
                  kiradi. Namuna rejimidagi o‘zgarishlar sahifa yangilanganda
                  tiklanadi.
                </p>
              </section>
            </div>
          )}
          <footer>
            <span className="footer-brand">mone.</span>
            <span>Moliyaviy xotirjamlik sari.</span>
            <span className="footer-right">
              {user
                ? "Shaxsiy moliya kabineti"
                : "Namuna · ma’lumotlar bazasiga yozilmaydi"}
            </span>
          </footer>
        </main>
      </div>

      <button
        type="button"
        className="mobile-add-entry"
        onClick={() => openEditor("new")}
      >
        <Plus size={21} />
        Kirim yoki chiqim qo‘shish
      </button>
      {notice && (
        <div className="toast" role="status">
          <span className="toast-check">
            <Check size={16} />
          </span>
          {notice}
          <button
            className="icon-button"
            onClick={() => setNotice("")}
            aria-label="Xabarni yopish"
          >
            <X size={15} />
          </button>
        </div>
      )}
      {editor && (
        <EntryModal
          entry={editor}
          categories={categoryOptions}
          currency={currency}
          demo={!user}
          saving={saving}
          error={error}
          onClose={() => {
            if (!saving) setEditor(null);
          }}
          onSave={saveEntry}
          onDelete={(entry) => {
            setEditor(null);
            setDeleting(entry);
          }}
        />
      )}
      {deleting && (
        <Modal
          title="Operatsiyani o‘chirish"
          onClose={() => {
            if (!saving) setDeleting(null);
          }}
        >
          <p className="modal-copy">
            “{deleting.description || categoryLabel(deleting.category)}” —{" "}
            {money(deleting.amount)} {deleting.currency} yozuvi o‘chiriladi. Bu
            amalni ortga qaytarib bo‘lmaydi.
          </p>
          <div className="modal-actions">
            <button
              className="button secondary"
              onClick={() => setDeleting(null)}
              disabled={saving}
            >
              Bekor qilish
            </button>
            <button
              className="button danger"
              onClick={deleteEntry}
              disabled={saving}
            >
              {saving ? "O‘chirilmoqda…" : "O‘chirish"}
            </button>
          </div>
        </Modal>
      )}
      {login && (
        <Modal title="Telegram orqali kirish" onClose={() => setLogin(null)}>
          <div className="login-illustration">
            <Send size={30} />
          </div>
          <p className="modal-copy">
            Botni oching va kirishni tasdiqlang. Botdagi kod bilan quyidagi kod
            bir xil bo‘lishi kerak.
          </p>
          <div className="login-code">{login.code}</div>
          <a
            className="button primary full"
            href={login.url}
            target="_blank"
            rel="noopener noreferrer"
          >
            <Send size={17} />
            Telegram botni ochish
            <ArrowUpRight size={16} />
          </a>
          <p className="login-wait">
            <span className="spinner small-spinner" />
            Tasdiqlash kutilmoqda · 5 daqiqa
          </p>
        </Modal>
      )}
    </div>
  );
}
