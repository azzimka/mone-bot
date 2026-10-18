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
  Minus,
  RefreshCw,
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
  demoEntries,
  Entry,
  EntryInput,
  localDay,
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

import { useLanguage } from "../components/language-provider";
import { monthLabel } from "../lib/translations";

import { Brand } from "../components/brand";
import { PeriodPicker } from "../components/period-picker";
import { cashflow, dateText, type DateRange } from "../lib/period";
import { Settings } from "../components/settings";

import { useCategories, demoCategories, type CategoryDetails } from "../components/category-provider";

import { type MoneyAccount } from "../components/finance-tools";
import { PortfolioValuation } from "../components/exchange-rates";

type View = "dashboard" | "transactions" | "analytics" | "settings";
const titles: Record<View, string> = {
  dashboard: "Umumiy ko‘rinish",
  transactions: "Operatsiyalar",
  analytics: "Tahlil va hisobotlar",
  settings: "Sozlamalar",
};
const chartColors = [
  "#147d64",
  "#7bb398",
  "#b0cdb5",
  "#d4b98b",
  "#a1b1c4",
  "#d1d8df",
];


export default function Page() {
  const {catalog,setCatalog}=useCategories();
  const {
    t,
    language,
    locale,
    money,
    categoryLabel,
    descriptionLabel,
    setAccount,
  } = useLanguage();
  const [view, setView] = useState<View>("dashboard");
  const [sidebar, setSidebar] = useState(false);
  const [user, setUser] = useState<Profile | null>(null);
  const [wallets,setWallets]=useState<MoneyAccount[]>([]);
  const [reportCurrency,setReportCurrency]=useState("UZS");
  useEffect(()=>{if(user)setReportCurrency(user.currency);},[user?.currency]);
  const [demo, setDemo] = useState<Entry[]>(demoEntries);
  const [month, setMonth] = useState("2026-10");
  const [range, setRange] = useState<DateRange | null>(null);
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
  const [notice, setNotice] = useState<
    string | { key: string; values: Record<string, string | number> }
  >("");
  const [newKind, setNewKind] = useState<Entry["type"]>("expense");
  const [editor, setEditor] = useState<Entry | "new" | null>(null);
  const [deleting, setDeleting] = useState<Entry | null>(null);
  const [saving, setSaving] = useState(false);
  const [login, setLogin] = useState<{ url: string; code: string } | null>(
    null,
  );
  const [loginBusy, setLoginBusy] = useState(false);
  const [categoryOptions, setCategoryOptions] = useState(categories);
  const [exporting, setExporting] = useState(false);
  const { start, end } = range ?? monthPeriod(month);
  const periodLabel = range ? `${dateText(start)} – ${dateText(end)}` : monthLabel(language, month);

  const reportError = (e: unknown) =>
    setError(e instanceof Error ? e.message : "Xatolik yuz berdi.");
  const refresh = useCallback(() => setRevision((r) => r + 1), []);

  useEffect(() => {
    setAccount(user);
  }, [user, setAccount]);

  useEffect(() => {
    const readView = () => {
      const requested = new URLSearchParams(window.location.search).get("view");
      setView(
        requested === "settings" ||
          requested === "transactions" ||
          requested === "analytics"
          ? requested
          : "dashboard",
      );
      setSidebar(false);
      setPage(0);
      setSearch("");
      setSearchTerm("");
      setKind("");
    };
    readView();
    window.addEventListener("popstate", readView);
    return () => window.removeEventListener("popstate", readView);
  }, []);

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
            setMonth(localDay(authRes.user.timezone).slice(0, 7));
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
        setMonth(localDay(profile.timezone).slice(0, 7));
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
      if (document.visibilityState === "visible") {
        refresh();
        request<Profile>("/me")
          .then((profile) =>
            setUser((current) =>
              current &&
              current.language === profile.language &&
              current.language_url === profile.language_url &&
              current.first_name === profile.first_name &&
              current.currency === profile.currency &&
              current.username === profile.username
                ? current
                : profile,
            ),
          )
          .catch(() => {});
      }
    };
    const timer = setInterval(update, 30000);
    window.addEventListener("focus", update);
    return () => {
      clearInterval(timer);
      window.removeEventListener("focus", update);
    };
  }, [user, refresh]);

  useEffect(() => {
    if (!user) return;
    const controller = new AbortController();
    request<MoneyAccount[]>("/accounts",{signal:controller.signal}).then(setWallets).catch(()=>{});
    request<CategoryDetails[]>("/category-settings", { signal: controller.signal })
      .then(items=>{setCatalog(items);setCategoryOptions(items.filter(item=>!item.archived).map(item=>item.name));})
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
            `${t.description} ${descriptionLabel(t)} ${t.category} ${categoryLabel(t.category)}`
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
      currency:reportCurrency,
      search: searchTerm,
      kind,
      offset: String(page * 20),
      limit: "20",
    });
    Promise.all([
      request<Summary>(`/summary?start=${start}&end=${end}&currency=${reportCurrency}`, {
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
  }, [
    user,
    demo,
    start,
    end,
    kind,
    searchTerm,
    page,
    revision,
    reportCurrency,
    categoryLabel,
    descriptionLabel,
  ]);

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
            setMonth(localDay(profile.timezone).slice(0, 7));
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
      await request("/auth/logout", { method: "POST" });
      localStorage.removeItem("mone_token");
      setCategoryOptions(categories);
      setCatalog(demoCategories);
      setUser(null);
      setMonth("2026-10");
      setRange(null);
      setPage(0);
      setView("dashboard");
      setNotice("Hisobdan chiqdingiz. Namuna rejimi ochildi.");
    } catch (e) {
      reportError(e);
    }
  };

  const flow = useMemo(() => cashflow(summary?.daily ?? [], start, end), [summary, start, end]);


  const openEditor = (
    entry: Entry | "new",
    kind: Entry["type"] = "expense",
  ) => {
    setNewKind(kind);
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
      if(data.account_id){const selected=wallets.find(item=>item.id===data.account_id);if(selected)setReportCurrency(selected.currency);}
      setEditor(null);
      setPage(0);
      if (!range || data.date < range.start || data.date > range.end) { setRange(null); setMonth(data.date.slice(0, 7)); }
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
            `${t.description} ${descriptionLabel(t)} ${t.category} ${categoryLabel(t.category)}`
              .toLocaleLowerCase()
              .includes(searchTerm.toLocaleLowerCase()),
        );
      else {
        for (let offset = 0; ; offset += 100) {
          const params = new URLSearchParams({
            start,
            end,
            currency:reportCurrency,
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
      a.download = `mone-${user ? "" : "namuna-"}${range ? `${start}_${end}` : month}.csv`;
      a.click();
      URL.revokeObjectURL(url);
      setNotice({
        key: "{count} ta operatsiya eksport qilindi.",
        values: { count: rows.length },
      });
    } catch (e) {
      reportError(e);
    } finally {
      setExporting(false);
    }
  }

  const navigate = (next: View) => {
    const url = new URL(window.location.href);
    if (next === "dashboard") url.searchParams.delete("view");
    else url.searchParams.set("view", next);
    url.hash = "";
    if (url.href !== window.location.href)
      window.history.pushState(null, "", url);
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
    <div className={`app-shell view-${view}`}>
      {sidebar && (
        <button
          className="sidebar-overlay"
          aria-label={t("Menyuni yopish")}
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
          <Brand />
        </a>
        <div className="sidebar-account">
          <strong>{user?.first_name ?? t("Namuna rejimi")}</strong>
        </div>
        <nav aria-label={t("Asosiy navigatsiya")}>
          {(
            [
              {
                id: "dashboard",
                icon: LayoutDashboard,
                text: t("Umumiy ko‘rinish"),
              },
              {
                id: "transactions",
                icon: ArrowDownLeft,
                text: t("Operatsiyalar"),
              },
              {
                id: "analytics",
                icon: BarChart3,
                text: t("Tahlil va hisobotlar"),
              },
              {
                id: "settings",
                icon: SlidersHorizontal,
                text: t("Sozlamalar"),
              },
            ] as const
          ).map(({ id, icon: Icon, text }) => (
            <button
              key={id}
              className={`nav-item ${view === id ? "active" : ""}`}
              aria-current={view === id ? "page" : undefined}
              onClick={() => navigate(id)}
            >
              <Icon size={19} strokeWidth={1.7} />
              {text}
              {view === id && <span className="active-dot" />}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="sidebar-profile">
            <span className="avatar">
              {user?.first_name.slice(0, 1) ?? "M"}
            </span>
            <div>
              <strong>{user?.first_name ?? t("Mone bilan tanishing")}</strong>
              <span>{user ? t("Shaxsiy hisob") : t("Namuna rejimi")}</span>
            </div>
            {user ? (
              <button
                className="icon-button"
                onClick={logout}
                aria-label={t("Hisobdan chiqish")}
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
              aria-label={t("Menyuni ochish")}
            >
              <Menu size={21} />
            </button>
            <button
              className="mobile-brand"
              aria-label={t("Bosh sahifa")}
              onClick={() => navigate("dashboard")}
            >
              <Brand />
            </button>
            <span>{t("Shaxsiy moliya")}</span>
            <ChevronRight size={14} />
            <strong>{t(titles[view])}</strong>
          </div>
          <div className="topbar-controls">
          <div className="topbar-actions desktop-connection">
            <span className={`connection ${user ? "connected" : ""}`}>
              <i />
              {user ? t("Telegram ulangan") : t("Namuna rejimi")}
            </span>
          </div>
          <button
            type="button"
            className="icon-button app-refresh"
            aria-label={t("Ilovani yangilash")}
            title={t("Ilovani yangilash")}
            onClick={() => window.location.reload()}
          >
            <RefreshCw size={20} />
          </button>
          </div>
        </header>
        <main>
          <div className="page-heading">
            <div>
              <h1>
                {t(titles[view])}
                <span className="heading-dot">.</span>
              </h1>
            </div>
            <button
              className="button primary"
              onClick={() => openEditor("new")}
              disabled={!!user && !user.language}
            >
              <Plus size={18} />
              {t("Yangi operatsiya")}
            </button>
          </div>

          {!user && (
            <div className="demo-banner">
              <span className="demo-label">{t("Namuna rejimi")}</span>
              <button onClick={beginLogin} disabled={loginBusy}>
                {t(loginBusy ? "Ulanmoqda…" : "Telegram orqali kirish")}
                <ArrowRight size={16} />
              </button>
            </div>
          )}
          {error && (
            <div className="error-banner" role="alert">
              <span>{t(error)}</span>
              <button
                className="icon-button"
                onClick={() => setError("")}
                aria-label={t("Xatolikni yopish")}
              >
                <X size={17} />
              </button>
            </div>
          )}

          {user && !user.language && (
            <div className="account-language-prompt" role="status">
              <h2>{t("Avval botda tilni tanlang")}</h2>
              <p>
                {t(
                  "Til Telegram hisobingizga saqlanadi va barcha qurilmalarda bir xil ishlaydi.",
                )}
              </p>
              {user.language_url ? (
                <a
                  className="button primary"
                  href={user.language_url}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  {t("Botda tilni tanlash")}
                </a>
              ) : (
                <button className="button primary" onClick={beginLogin}>
                  {t("Botda tilni tanlash")}
                </button>
              )}
            </div>
          )}

          {(!user || user.language) && view !== "settings" && (
            <div className="section-toolbar">
              <PeriodPicker
                month={month}
                range={range}
                today={user ? localDay(user.timezone) : "2026-10-18"}
                onChange={(selection) => {
                  setMonth(selection.month);
                  setRange(selection.range);
                  setPage(0);
                }}
              />
              {user&&new Set(wallets.map(item=>item.currency)).size>1&&<select className="report-currency" aria-label={t("Hisobot valyutasi")} value={reportCurrency} onChange={event=>{setReportCurrency(event.target.value);setPage(0);}}>{[...new Set([user.currency,...wallets.map(item=>item.currency)])].map(code=><option key={code} value={code}>{code}</option>)}</select>}
            </div>
          )}
          {(!user || user.language) && view === "dashboard" && (
            <div className="quick-entry-actions">
              <button
                type="button"
                className="quick-income"
                onClick={() => openEditor("new", "income")}
                aria-label={t("Kirim qo‘shish")}
              >
                <Plus size={38} />
                <span>{t("Kirim")}</span>
              </button>
              <button
                type="button"
                className="quick-expense"
                onClick={() => openEditor("new", "expense")}
                aria-label={t("Chiqim qo‘shish")}
              >
                <Minus size={38} />
                <span>{t("Chiqim")}</span>
              </button>
            </div>
          )}

          {loading && view !== "settings" && (
            <div className="loading-panel" role="status">
              <span className="spinner" />
              {t("Ma’lumotlar yuklanmoqda…")}
            </div>
          )}

          {!loading &&
            (!user || user.language) &&
            view !== "settings" &&
            summary && (
              <>
                <section
                  className="stats-grid"
                  aria-label={t("Moliyaviy ko‘rsatkichlar")}
                >
                  <div className="stat-card balance-card">
                    <div className="stat-heading">
                      {t("Joriy balans")}
                      <Wallet size={18} />
                    </div>
                    <div className="stat-value">
                      {money(summary.balance)} <span>{currency}</span>
                    </div>
                    {user&&new Set(wallets.map(item=>item.currency)).size>1&&
                      <PortfolioValuation base={reportCurrency} revision={revision}/>}
                    <div className="stat-foot">
                      <span className="balance-pill">
                        {t("Barcha davrlar")}
                      </span>
                      <span>{t("Jami kirim − jami chiqim")}</span>
                    </div>
                    <div className="balance-decoration" />
                  </div>
                  <div className="stat-card">
                    <div className="stat-heading">
                      {t("Davrdagi kirim")}
                      <span className="stat-icon income">
                        <ArrowDownLeft size={17} />
                      </span>
                    </div>
                    <div className="stat-value">
                      {money(summary.income)} <span>{currency}</span>
                    </div>
                    <div className="stat-foot">
                      <span className="dot green" />
                      {t("Tanlangan davr uchun")}
                    </div>
                  </div>
                  <div className="stat-card">
                    <div className="stat-heading">
                      {t("Davrdagi chiqim")}
                      <span className="stat-icon expense">
                        <ArrowUpRight size={17} />
                      </span>
                    </div>
                    <div className="stat-value">
                      {money(summary.expense)} <span>{currency}</span>
                    </div>
                    <div className="stat-foot">
                      <span className="dot orange" />
                      {t("Tanlangan davr uchun")}
                    </div>
                  </div>
                  <div className="stat-card period-result">
                    <div className="stat-heading">
                      {t("Davrdagi farq")}
                      <span className="stat-icon neutral">
                        <BarChart3 size={17} />
                      </span>
                    </div>
                    <div className="stat-value">
                      {money(income - expense)} <span>{currency}</span>
                    </div>
                    <div className="stat-foot">
                      <span className="result-pill">
                        {t("{count} ta operatsiya", { count: summary.count })}
                      </span>
                      <span>{t("Kirim − chiqim")}</span>
                    </div>
                  </div>
                </section>

                {view === "analytics" && (
                  <div className="charts-grid">
                    <section className="panel cashflow-panel">
                      <div className="panel-heading">
                        <div>
                          <h2>{t("Pul oqimi")}</h2>
                          <p>{t("Kirim va chiqimlaringiz kunlar kesimida")}</p>
                        </div>
                        <div className="chart-legend">
                          <span>
                            <i className="legend-income" />
                            {t("Kirim")}
                          </span>
                          <span>
                            <i className="legend-expense" />
                            {t("Chiqim")}
                          </span>
                        </div>
                      </div>
                      <div
                        className="cashflow-chart"
                        role="img"
                        aria-label={t(
                          flow.monthly ? "{period}: oylik kirim va chiqim, {currency}" : "{period}: kunlik kirim va chiqim, {currency}",
                          { period: periodLabel, currency },
                        )}
                      >
                        <ResponsiveContainer width="100%" height="100%">
                          <AreaChart
                            data={flow.points}
                            margin={{
                              top: 12,
                              right: 12,
                              bottom: 3,
                              left: -12,
                            }}
                          >
                            <CartesianGrid
                              vertical={false}
                              stroke="#edf0ee"
                              strokeDasharray="4 4"
                            />
                            <XAxis
                              dataKey="date"
                              tickLine={false}
                              axisLine={false}
                              minTickGap={22}
                              tick={{ fontSize: 11, fill: "#83908a" }}
                              tickMargin={12}
                            tickFormatter={value => flow.monthly ? `${String(value).slice(5,7)}.${String(value).slice(2,4)}` : dateText(String(value)).slice(0,5)}
                            />
                            <YAxis
                              tickLine={false}
                              axisLine={false}
                              tick={{ fontSize: 11, fill: "#83908a" }}
                              tickFormatter={(v) =>
                                Number(v) >= 1000000
                                  ? `${money(Number(v) / 1000000)} ${t("mln")}`
                                  : `${money(Number(v) / 1000)} ${t("ming")}`
                              }
                            />
                            <Tooltip
                              formatter={(v, name) => [
                                `${money(Number(v))} ${currency}`,
                                name === "income" ? t("Kirim") : t("Chiqim"),
                              ]}
                              labelFormatter={(v) => flow.monthly ? monthLabel(language,String(v)) : dateText(String(v))}
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
                        <span>
                          {t(flow.monthly ? "Oy" : "Kun")} / {periodLabel}
                        </span>
                        <span>
                          {t("Miqdor")} ({currency})
                        </span>
                      </div>
                    </section>
                    <section className="panel category-panel">
                      <div className="panel-heading">
                        <div>
                          <h2>{t("Xarajatlar tarkibi")}</h2>
                          <p>{t("Pulingiz nimalarga sarflandi?")}</p>
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
                              <span>{t("Jami chiqim")}</span>
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
                                    ? new Intl.NumberFormat(locale, {
                                        minimumFractionDigits: 1,
                                        maximumFractionDigits: 1,
                                      }).format((c.value / expense) * 100)
                                    : 0}
                                  %
                                </strong>
                              </div>
                            ))}
                          </div>
                          {pie.length > 4 && (
                            <button
                              className="text-button category-more"
                              onClick={() =>
                                document
                                  .getElementById("category-breakdown")
                                  ?.scrollIntoView({
                                    behavior: "smooth",
                                    block: "start",
                                  })
                              }
                            >
                              {t("Barcha {count} ta kategoriya", {
                                count: pie.length,
                              })}
                              <ArrowRight size={14} />
                            </button>
                          )}
                        </>
                      ) : (
                        <div className="empty-chart">
                          <ShoppingBag size={28} />
                          <p>{t("Bu davrda xarajatlar yo‘q.")}</p>
                        </div>
                      )}
                    </section>
                  </div>
                )}

                {view === "analytics" && (
                  <section className="panel breakdown" id="category-breakdown">
                    <div className="panel-heading">
                      <div>
                        <h2>{t("Kategoriyalar bo‘yicha batafsil")}</h2>
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
                        {t("Tanlangan davrda xarajatlar yo‘q.")}
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
                            ? t("So‘nggi operatsiyalar")
                            : t("Barcha operatsiyalar")}
                          <span className="count-pill">{total}</span>
                        </h2>
                        <p>
                          {view === "dashboard"
                            ? t("Moliyaviy tarixingizga qisqa nazar")
                            : t("Tanlangan davr bo‘yicha yozuvlar")}
                        </p>
                      </div>
                      {view === "dashboard" ? (
                        <button
                          className="text-button"
                          onClick={() => navigate("transactions")}
                        >
                          {t("Barchasi")}
                          <ArrowRight size={15} />
                        </button>
                      ) : (
                        <button
                          className="button secondary compact"
                          onClick={exportCsv}
                          disabled={exporting || !total}
                        >
                          <Download size={16} />
                          {exporting ? t("Tayyorlanmoqda…") : t("CSV eksport")}
                        </button>
                      )}
                    </div>
                    {view === "transactions" && (
                      <div className="table-filters">
                        <label className="search-field">
                          <Search size={16} />
                          <input
                            aria-label={t("Operatsiyalarni qidirish")}
                            placeholder={t(
                              "Tavsif yoki kategoriya bo‘yicha qidirish…",
                            )}
                            value={search}
                            onChange={(e) => setSearch(e.target.value)}
                          />
                        </label>
                        <label className="type-filter">
                          <ListFilter size={15} />
                          <select
                            aria-label={t("Operatsiya turi")}
                            value={kind}
                            onChange={(e) => {
                              setKind(e.target.value);
                              setPage(0);
                            }}
                          >
                            <option value="">{t("Barcha turlar")}</option>
                            <option value="income">{t("Kirimlar")}</option>
                            <option value="expense">{t("Chiqimlar")}</option>
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
                            <th>{t("OPERATSIYA")}</th>
                            <th>{t("KATEGORIYA")}</th>
                            <th>{t("SANA")}</th>
                            <th className="amount-column">{t("SUMMA")}</th>
                            <th>
                              <span className="sr-only">{t("Amallar")}</span>
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
                                        {descriptionLabel(tx) ||
                                          categoryLabel(tx.category)}
                                      </strong>
                                      <span>
                                        {tx.type === "income"
                                          ? t("Kirim")
                                          : t("Chiqim")}
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
                                  {money(tx.amount)}{" "}
                                  <small>{tx.currency}</small>
                                </td>
                                <td>
                                  <div className="row-actions">
                                    <button
                                      className="icon-button"
                                      aria-label={t(
                                        "{name} operatsiyasini tahrirlash",
                                        {
                                          name:
                                            descriptionLabel(tx) ||
                                            categoryLabel(tx.category),
                                        },
                                      )}
                                      onClick={() => openEditor(tx)}
                                    >
                                      <Edit3 size={15} />
                                    </button>
                                    <button
                                      className="icon-button delete-action"
                                      aria-label={t(
                                        "{name} operatsiyasini o‘chirish",
                                        {
                                          name:
                                            descriptionLabel(tx) ||
                                            categoryLabel(tx.category),
                                        },
                                      )}
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
                        <h3>{t("Operatsiyalar topilmadi")}</h3>
                        <p>
                          {t(
                            "Boshqa davr yoki filtrni tanlang.",
                          )}
                        </p>
                        <button
                          className="button secondary compact"
                          onClick={() => openEditor("new")}
                        >
                          <Plus size={15} />
                          {t("Operatsiya qo‘shish")}
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
                          {t("Oldingi")}
                        </button>
                        <button
                          className="button secondary compact"
                          disabled={(page + 1) * 20 >= total}
                          onClick={() => setPage((p) => p + 1)}
                        >
                          {t("Keyingi")}
                          <ChevronRight size={15} />
                        </button>
                      </div>
                    )}
                  </section>
                )}
              </>
            )}

          {(!user || user.language) && view === "settings" && (
            <Settings
              profile={user}
              categories={catalog}
              period={periodLabel}
              exporting={exporting}
              busy={loginBusy}
              onProfile={setUser}
              onCategories={items=>{setCatalog(items);setCategoryOptions(items.filter(item=>!item.archived).map(item=>item.name));refresh();}}
              onLogin={beginLogin}
              onLogout={logout}
              onExport={exportCsv}
              onChanged={refresh}
            />
          )}
        </main>
      </div>

      {(!user || user.language) && view !== "settings" && <div className="mobile-entry-dock"><button type="button" className="quick-income" aria-label={t("Kirim qo‘shish")} onClick={()=>openEditor("new","income")}><Plus size={32}/><span>{t("Kirim")}</span></button><button type="button" className="quick-expense" aria-label={t("Chiqim qo‘shish")} onClick={()=>openEditor("new","expense")}><Minus size={32}/><span>{t("Chiqim")}</span></button></div>}
      {notice && (
        <div className="toast" role="status">
          <span className="toast-check">
            <Check size={16} />
          </span>
          {typeof notice === "string"
            ? t(notice)
            : t(notice.key, notice.values)}
          <button
            className="icon-button"
            onClick={() => setNotice("")}
            aria-label={t("Xabarni yopish")}
          >
            <X size={15} />
          </button>
        </div>
      )}
      {editor && (
        <EntryModal
          entry={editor}
          newType={newKind}
          categories={categoryOptions}
          accounts={wallets}
          quickCategories={user?.quick_categories}
          timeZone={user?.timezone}
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
          title={t("Operatsiyani o‘chirish")}
          onClose={() => {
            if (!saving) setDeleting(null);
          }}
        >
          <p className="modal-copy">
            {t(
              "“{name}” — {amount} {currency} yozuvi o‘chiriladi. Bu amalni ortga qaytarib bo‘lmaydi.",
              {
                name:
                  descriptionLabel(deleting) ||
                  categoryLabel(deleting.category),
                amount: money(deleting.amount),
                currency: deleting.currency,
              },
            )}
          </p>
          <div className="modal-actions">
            <button
              className="button secondary"
              onClick={() => setDeleting(null)}
              disabled={saving}
            >
              {t("Bekor qilish")}
            </button>
            <button
              className="button danger"
              onClick={deleteEntry}
              disabled={saving}
            >
              {saving ? t("O‘chirilmoqda…") : t("O‘chirish")}
            </button>
          </div>
        </Modal>
      )}
      {login && (
        <Modal
          title={t("Telegram orqali kirish")}
          onClose={() => setLogin(null)}
        >
          <div className="login-illustration">
            <Send size={30} />
          </div>
          <p className="modal-copy">
            {t(
              "Botni oching va kirishni tasdiqlang. Botdagi kod bilan quyidagi kod bir xil bo‘lishi kerak.",
            )}
          </p>
          <div className="login-code">{login.code}</div>
          <a
            className="button primary full"
            href={login.url}
            target="_blank"
            rel="noopener noreferrer"
          >
            <Send size={17} />
            {t("Telegram botni ochish")}
            <ArrowUpRight size={16} />
          </a>
          <p className="login-wait">
            <span className="spinner small-spinner" />
            {t("Tasdiqlash kutilmoqda · 5 daqiqa")}
          </p>
        </Modal>
      )}
    </div>
  );
}
