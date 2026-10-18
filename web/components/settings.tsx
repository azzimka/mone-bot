"use client";
import { useState } from "react";
import { Check, Download, LogOut, Send } from "lucide-react";
import { type Profile, request } from "../lib/api";
import { useLanguage } from "./language-provider";
import { FinanceTools } from "./finance-tools";
import { CategoryManager } from "./category-manager";
import { type CategoryDetails } from "./category-provider";
import { type Language } from "../lib/translations";

export function Settings({
  profile,
  categories,
  period,
  exporting,
  busy,
  onProfile,
  onCategories,
  onLogin,
  onLogout,
  onExport,
  onChanged,
}: {
  profile: Profile | null;
  categories: CategoryDetails[];
  period: string;
  exporting: boolean;
  busy: boolean;
  onProfile: (profile: Profile) => void;
  onCategories: (items: CategoryDetails[]) => void;
  onLogin: () => void;
  onLogout: () => void;
  onExport: () => void;
  onChanged: () => void;
}) {
  const { t, language, setLanguage } = useLanguage();
  const [languageBusy, setLanguageBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  async function changeLanguage(next: Language) {
    setError("");
    setNotice("");
    if (!profile) {
      setLanguage(next);
      return;
    }
    setLanguageBusy(true);
    try {
      const updated = await request<Profile>("/preferences", {
        method: "PATCH",
        body: JSON.stringify({ language: next }),
      });
      onProfile(updated);
      setNotice("Saqlandi.");
    } catch (error) {
      setError(error instanceof Error ? error.message : "Xatolik yuz berdi.");
    } finally {
      setLanguageBusy(false);
    }
  }
  return (
    <div className="preferences-layout">
      <section className="settings-section" id="preferences">
        <h2>{t("Til")}</h2>
        <label className="preference-row">
          <span>{t("Bot va website tili")}</span>
          <select
            aria-label={t("Bot va website tili")}
            value={language}
            disabled={languageBusy}
            onChange={(event) => changeLanguage(event.target.value as Language)}
          >
            <option value="uz">O‘zbekcha</option>
            <option value="ru">Русский</option>
          </select>
        </label>
        {!profile && (
          <p className="settings-hint">
            {t("Namuna sozlamasi. Hisobingiz uchun Telegram orqali kiring.")}
          </p>
        )}
      </section>
      <FinanceTools profile={profile} onProfile={onProfile} onChanged={onChanged} onLogin={onLogin}/>
      <CategoryManager categories={categories} authenticated={Boolean(profile)} onChange={onCategories}/>
      {error && (
        <p className="settings-feedback error" role="alert">
          {t(error)}
        </p>
      )}
      {notice && (
        <p className="settings-feedback" role="status">
          <Check size={16} />
          {t(notice)}
        </p>
      )}
      <section className="settings-section">
        <h2>{t("Ma’lumotlar")}</h2>
        <button
          className="settings-action"
          onClick={onExport}
          disabled={exporting}
        >
          <span>
            <Download size={20} />
            <span>
              <strong>{t("CSV eksport")}</strong>
              <small>{period}</small>
            </span>
          </span>
          <span>{t(exporting ? "Tayyorlanmoqda…" : "Yuklash")}</span>
        </button>
        <details className="settings-details">
          <summary>{t("CSV import")}</summary>
          <p>{t("Botga /import yuboring va CSV faylni yuklang.")}</p>
        </details>
        <details className="settings-details">
          <summary>{t("Telefonga o‘rnatish")}</summary>
          <p>
            {t(
              "iPhone: Safari → Ulashish → Bosh ekranga qo‘shish. Android: Chrome → Ilovani o‘rnatish.",
            )}
          </p>
        </details>
      </section>
      {profile && (
        <section className="settings-section">
          <h2>{t("Hisob")}</h2>
          <div className="preference-row">
            <span>{profile?.first_name ?? t("Namuna rejimi")}</span>
            <strong>{profile?.currency ?? "UZS"}</strong>
          </div>
          {profile?.bot_url && (
            <a
              className="settings-action"
              href={profile.bot_url}
              target="_blank"
              rel="noopener noreferrer"
            >
              <span>
                <Send size={20} />
                {t("Botni ochish")}
              </span>
            </a>
          )}
          <button
            className={`settings-action ${profile ? "logout-action" : ""}`}
            disabled={busy}
            onClick={profile ? onLogout : onLogin}
          >
            <span>
              {profile ? <LogOut size={20} /> : <Send size={20} />}{" "}
              {t(profile ? "Hisobdan chiqish" : "Telegram orqali kirish")}
            </span>
          </button>
        </section>
      )}
    </div>
  );
}
