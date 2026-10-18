"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import {
  categoryLabel as uzbekCategoryLabel,
  type Entry,
  type Profile,
} from "../lib/api";
import {
  entryDescription,
  formatMoney,
  localeFor,
  normalizeLanguage,
  translate,
  type Language,
} from "../lib/translations";

import { useCategories } from "./category-provider";

const LanguageContext = createContext<ReturnType<
  typeof useLanguageState
> | null>(null);
const storageKey = "mone_language";

function useLanguageState() {
  const {catalog}=useCategories();
  // Keep the initial render identical to the static export, then restore the preference.
  const [previewLanguage, updateLanguage] = useState<Language>("uz");
  const [account, updateAccount] = useState<{
    language: Language | null;
    url: string | null;
  } | null>(null);
  const setAccount = useCallback(
    (profile: Profile | null) =>
      updateAccount(
        profile
          ? {
              language: profile.language ?? null,
              url: profile.language_url ?? null,
            }
          : null,
      ),
    [],
  );
  const language = account ? (account.language ?? "uz") : previewLanguage;
  useEffect(() => {
    try {
      updateLanguage(normalizeLanguage(localStorage.getItem(storageKey)));
    } catch {
      /* The switcher also works when browser storage is unavailable. */
    }
  }, []);
  useEffect(() => {
    document.documentElement.lang = language;
    const title = translate(language, "Mone — shaxsiy moliya kabineti");
    const description = translate(
      language,
      "Kirim, chiqim va moliyaviy odatlaringizni bir joyda boshqaring.",
    );
    const syncMetadata = () => {
      if (document.title !== title) document.title = title;
      const meta = document.querySelector('meta[name="description"]');
      if (meta?.getAttribute("content") !== description)
        meta?.setAttribute("content", description);
    };
    syncMetadata();
    // Next may stream static metadata after the saved language has been restored.
    const observer = new MutationObserver(syncMetadata);
    observer.observe(document.head, {
      childList: true,
      subtree: true,
      characterData: true,
    });
    return () => observer.disconnect();
  }, [language]);
  return useMemo(
    () => ({
      language,
      setAccount,
      accountLanguageLocked: account !== null,
      languageUrl: account?.url ?? null,
      locale: localeFor(language),
      setLanguage: (next: Language) => {
        if (account) return;
        updateLanguage(next);
        try {
          localStorage.setItem(storageKey, next);
        } catch {
          /* In-memory choice remains available. */
        }
      },
      t: (key: string, values?: Record<string, string | number>) =>
        translate(language, key, values),
      money: (amount: number | string) => formatMoney(language, amount),
      categoryLabel: (name: string) => {
        const item=catalog.find(item=>item.name===name);
        return (language==="ru"?item?.name_ru:item?.name_uz) ?? item?.display_name ?? (language === "ru" ? name : uzbekCategoryLabel(name));
      },
      descriptionLabel: (entry: Entry) => entryDescription(language, entry),
    }),
    [language, account, setAccount, catalog],
  );
}

export function LanguageProvider({ children }: { children: ReactNode }) {
  const value = useLanguageState();
  return (
    <LanguageContext.Provider value={value}>
      {children}
    </LanguageContext.Provider>
  );
}

export function useLanguage() {
  const value = useContext(LanguageContext);
  if (!value) throw new Error("LanguageProvider is required");
  return value;
}

export function LanguageSwitcher() {
  const { language, setLanguage, t, accountLanguageLocked, languageUrl } =
    useLanguage();
  if (accountLanguageLocked)
    return languageUrl ? (
      <a
        className="account-language"
        href={languageUrl}
        target="_blank"
        rel="noopener noreferrer"
        title={t("Tilni botda o‘zgartiring")}
      >
        {language === "ru" ? "Русский" : "O‘zbekcha"} · Telegram
      </a>
    ) : (
      <span className="account-language">
        {language === "ru" ? "Русский" : "O‘zbekcha"}
      </span>
    );
  return (
    <label className="language-switcher">
      <span className="sr-only">{t("Interfeys tili")}</span>
      <select
        value={language}
        onChange={(event) => setLanguage(normalizeLanguage(event.target.value))}
      >
        <option value="uz" lang="uz">
          O‘zbekcha
        </option>
        <option value="ru" lang="ru">
          Русский
        </option>
      </select>
    </label>
  );
}
