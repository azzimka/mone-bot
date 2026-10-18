"use client";
import { useState } from "react";
import { CalendarDays, ChevronLeft, ChevronRight } from "lucide-react";
import { Modal } from "./dialog";
import { useLanguage } from "./language-provider";
import { monthLabel } from "../lib/translations";
import { monthPeriod } from "../lib/api";
import { dateText, shiftDay, shiftRange, validateRange, type DateRange } from "../lib/period";

type Selection = {month:string;range:DateRange|null};
export function PeriodPicker({ month, range, today, onChange }: Selection & {today:string;onChange:(selection:Selection)=>void}) {
  const { t, language } = useLanguage();
  const [open,setOpen]=useState(false);
  const [year,setYear]=useState(Number(month.slice(0,4)));
  const [mode,setMode]=useState<"month"|"range">("month");
  const [draft,setDraft]=useState<DateRange>(range??monthPeriod(month));
  const [error,setError]=useState("");
  function selectMonth(next:string){onChange({month:next,range:null});setOpen(false);}
  function apply(next:DateRange){const error=validateRange(next);setError(error);if(!error){onChange({month:next.start.slice(0,7),range:next});setOpen(false);}}
  function move(delta:number){
    if(range){const shifted=shiftRange(range,delta);if(shifted)onChange({month:shifted.start.slice(0,7),range:shifted});return;}
    const date=new Date(`${month}-01T12:00:00Z`);date.setUTCMonth(date.getUTCMonth()+delta);const next=date.toISOString().slice(0,7);
    if(next>="2000-01"&&next<="2100-12")onChange({month:next,range:null});
  }
  const label=range?`${dateText(range.start)} – ${dateText(range.end)}`:monthLabel(language,month);
  return <div className="month-control" aria-label={t("Hisobot davri")}>
    <button type="button" onClick={()=>move(-1)} disabled={range?!shiftRange(range,-1):month==="2000-01"} aria-label={t("Oldingi davr")}><ChevronLeft size={20}/></button>
    <button type="button" className={`month-open ${range?"range-open":""}`} aria-haspopup="dialog" aria-expanded={open} onClick={()=>{setYear(Number(month.slice(0,4)));setDraft(range??monthPeriod(month));setMode(range?"range":"month");setError("");setOpen(true);}}><CalendarDays size={18}/><span>{label}</span></button>
    <button type="button" onClick={()=>move(1)} disabled={range?!shiftRange(range,1):month==="2100-12"} aria-label={t("Keyingi davr")}><ChevronRight size={20}/></button>
    {open&&<Modal title={t("Davrni tanlang")} className="month-dialog period-dialog" onClose={()=>setOpen(false)}>
      <div className="period-mode" role="group" aria-label={t("Davr turi")}><button type="button" aria-pressed={mode==="month"} onClick={()=>{setMode("month");setError("");}}>{t("Oy")}</button><button type="button" aria-pressed={mode==="range"} onClick={()=>{setMode("range");setError("");}}>{t("Interval")}</button></div>
      {mode==="month"?<><div className="month-year"><button type="button" aria-label={t("Oldingi yil")} disabled={year<=2000} onClick={()=>setYear(year-1)}><ChevronLeft size={22}/></button><strong>{year}</strong><button type="button" aria-label={t("Keyingi yil")} disabled={year>=2100} onClick={()=>setYear(year+1)}><ChevronRight size={22}/></button></div><div className="month-grid">{Array.from({length:12},(_,index)=>{const value=`${year}-${String(index+1).padStart(2,"0")}`;const label=monthLabel(language,value);return <button type="button" key={value} aria-label={label} aria-pressed={!range&&value===month} onClick={()=>selectMonth(value)}>{label.replace(/,?\s*\d{4}.*$/,"")}</button>;})}</div><button type="button" className="button secondary full" onClick={()=>selectMonth(today.slice(0,7))}>{t("Hozirgi oy")}</button></>:<form className="date-range-form" onInput={()=>setError("")} noValidate onSubmit={event=>{event.preventDefault();const data=new FormData(event.currentTarget);apply({start:String(data.get("start")??""),end:String(data.get("end")??"")});}}>
        <div className="range-presets"><button type="button" onClick={()=>apply({start:today,end:today})}>{t("Bugun")}</button><button type="button" onClick={()=>apply({start:shiftDay(today,-6),end:today})}>{t("Oxirgi 7 kun")}</button><button type="button" onClick={()=>apply({start:today.slice(0,7)+"-01",end:today})}>{t("Oy boshidan")}</button></div>
        <label>{t("Boshlanish sanasi")}<input name="start" type="date" min="2000-01-01" max="2100-12-31" required defaultValue={draft.start}/></label><label>{t("Tugash sanasi")}<input name="end" type="date" min="2000-01-01" max="2100-12-31" required defaultValue={draft.end}/></label>
        {error&&<p className="range-error" role="alert">{t(error)}</p>}<button type="submit" className="button primary full">{t("Qo‘llash")}</button>
      </form>}
    </Modal>}
  </div>;
}
