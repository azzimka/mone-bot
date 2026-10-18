/** Locale-friendly entry without rounding or converting financial values to Number. */
export function formatEntryAmount(input: string): string {
  const compact = input.replace(/[\s\u00a0\u202f]/g, "");
  const match = /^(\d*)([.,]?)(\d*)$/.exec(compact);
  if (!match) return input;
  const [, whole, separator, fraction] = match;
  return whole.replace(/\B(?=(\d{3})+(?!\d))/g, " ") + separator + fraction;
}

export function validateEntryAmount(input: string): {
  value: string;
  error: string;
} {
  const normalized = input.replace(/[\s\u00a0\u202f]/g, "").replace(",", ".");
  if (!normalized) return { value: "", error: "Summani kiriting." };
  if (!/^\d+(?:\.\d{1,2})?$/.test(normalized)) {
    return {
      value: "",
      error: "Musbat summa yozing. Masalan: 25 000 yoki 25 000,50.",
    };
  }
  const [rawWhole, fraction] = normalized.split(".");
  const whole = rawWhole.replace(/^0+(?=\d)/, "");
  if (whole.length > 13)
    return {
      value: "",
      error: "Summa 9 999 999 999 999,99 dan oshmasligi kerak.",
    };
  if (!/[1-9]/.test(whole + (fraction ?? "")))
    return { value: "", error: "Summa noldan katta bo‘lishi kerak." };
  return { value: fraction ? `${whole}.${fraction}` : whole, error: "" };
}

export function previousDay(day: string): string {
  const value = new Date(`${day}T12:00:00Z`);
  value.setUTCDate(value.getUTCDate() - 1);
  return value.toISOString().slice(0, 10);
}
