export type DateRange = { start: string; end: string };
const dayMs = 86_400_000;
export const dateText = (date: string) => date.split("-").reverse().join(".");
export function shiftDay(date: string, days: number): string {
  const value = new Date(`${date}T12:00:00Z`);
  value.setUTCDate(value.getUTCDate() + days);
  return value.toISOString().slice(0,10);
}
export function validateRange(range: DateRange): string {
  for(const day of [range.start,range.end]) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(day) || Number.isNaN(Date.parse(`${day}T12:00:00Z`)) || new Date(`${day}T12:00:00Z`).toISOString().slice(0,10)!==day) return "Ikkala sanani ham tanlang.";
    if(day < "2000-01-01" || day > "2100-12-31") return "Sana 2000–2100 yillar orasida bo‘lishi kerak.";
  }
  if(range.end < range.start) return "Tugash sanasi boshlanish sanasidan oldin bo‘lmasligi kerak.";
  if((Date.parse(range.end)-Date.parse(range.start))/dayMs > 3660) return "Interval 10 yildan oshmasligi kerak.";
  return "";
}
export function shiftRange(range: DateRange, direction: number): DateRange | null {
  const length = Math.round((Date.parse(range.end)-Date.parse(range.start))/dayMs)+1;
  const shifted={start:shiftDay(range.start,length*direction),end:shiftDay(range.end,length*direction)};
  return validateRange(shifted) ? null : shifted;
}
export function cashflow(daily: {date:string;income:string;expense:string}[], start:string, end:string) {
  const days=Math.round((Date.parse(end)-Date.parse(start))/dayMs)+1;
  const monthly=days>93;
  const found=new Map(daily.map(row=>[row.date,row]));
  const buckets=new Map<string,{date:string;income:number;expense:number}>();
  if(days<1||days>3661) return {monthly,points:[]};
  for(let offset=0;offset<days;offset++){
    const day=shiftDay(start,offset);const key=monthly?day.slice(0,7):day;
    const item=buckets.get(key)??{date:key,income:0,expense:0};
    const row=found.get(day);item.income+=Number(row?.income??0);item.expense+=Number(row?.expense??0);buckets.set(key,item);
  }
  return {monthly,points:[...buckets.values()]};
}
