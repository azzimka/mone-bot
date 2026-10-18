"use client";

import { useEffect, useState } from "react";
import { request } from "../lib/api";
import { useLanguage } from "./language-provider";

export type RateMetadata = {
  source: string;
  source_url: string;
  effective_date: string;
  stale: boolean;
};
type Rates = RateMetadata & {base:string;rates:{currency:string;rate:string}[]};
type Valuation = RateMetadata & {base:string;total:string|null;complete:boolean;missing_currencies:string[]};
export type FxQuote = RateMetadata & {
  source_currency:string;destination_currency:string;converted:string;rate:string;
};

export function RateSource({book}:{book:RateMetadata}) {
  const {t}=useLanguage();
  return <small className="fx-source">
    <a href={book.source_url} target="_blank" rel="noopener noreferrer">{t("Markaziy bank")}</a>
    <span> · {book.effective_date}</span>
    {book.stale&&<span className="fx-stale"> · {t("Yangilash vaqtincha ishlamadi. Saqlangan kurs.")}</span>}
  </small>;
}

export function ReferenceRates({base}:{base:string}) {
  const {t,locale}=useLanguage();
  const [book,setBook]=useState<Rates|null>(null),[error,setError]=useState("");
  useEffect(()=>{
    const controller=new AbortController();setBook(null);setError("");
    request<Rates>(`/exchange-rates?base=${encodeURIComponent(base)}`,{signal:controller.signal})
      .then(setBook).catch(error=>{if(!controller.signal.aborted)setError(error.message);});
    return ()=>controller.abort();
  },[base]);
  return <details className="fx-panel">
    <summary>{t("Rasmiy valyuta kurslari")}</summary>
    {error?<p className="fx-error" role="status">{t(error)}</p>:book?<>
      <div className="fx-rate-list">{book.rates.filter(row=>["UZS","USD","EUR","RUB","KZT","GBP"].includes(row.currency)&&row.currency!==base).map(row=><div key={row.currency}><span>1 {row.currency}</span><strong>{new Intl.NumberFormat(locale,{maximumFractionDigits:8}).format(Number(row.rate))} {book.base}</strong></div>)}</div>
      <RateSource book={book}/><p className="finance-hint">{t("Bu rasmiy ma’lumot kursi. Bankingizning ayirboshlash kursi farq qilishi mumkin.")}</p>
    </>:<p role="status">{t("Kurslar olinmoqda…")}</p>}
  </details>;
}

export function PortfolioValuation({base,revision=0}:{base:string;revision?:number|string}) {
  const {t,money}=useLanguage();
  const [book,setBook]=useState<Valuation|null>(null),[error,setError]=useState("");
  useEffect(()=>{
    const controller=new AbortController();setBook(null);setError("");
    request<Valuation>(`/accounts/valuation?base=${encodeURIComponent(base)}`,{signal:controller.signal})
      .then(setBook).catch(error=>{if(!controller.signal.aborted)setError(error.message);});
    return ()=>controller.abort();
  },[base,revision]);
  if(error)return <p className="fx-error" role="status">{t("Taxminiy jami vaqtincha olinmadi.")}</p>;
  if(!book)return null;
  return <div className="fx-valuation">
    {book.complete?<><span>{t("Barcha hisoblar, taxminan")}</span><strong>≈ {money(book.total!)} {book.base}</strong></>:<p>{t("Jami hisoblanmadi: ayrim valyutalar uchun kurs yo‘q.")} {book.missing_currencies.join(", ")}</p>}
    <RateSource book={book}/>
  </div>;
}
