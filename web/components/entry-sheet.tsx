"use client";

import {
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type CSSProperties,
} from "react";
import {
  ArrowDownLeft,
  ArrowUpRight,
  CalendarDays,
  Check,
  ChevronDown,
  Search,
  ShieldCheck,
  Trash2,
} from "lucide-react";
import {
  categoryLabel,
  type Entry,
  type EntryInput,
  localDay,
} from "../lib/api";
import {
  formatEntryAmount,
  previousDay,
  validateEntryAmount,
} from "../lib/entry";
import { CategoryIcon } from "./category-icon";
import { Modal } from "./dialog";

const priority = {
  expense: ["Еда", "Транспорт", "Жильё", "Здоровье", "Одежда", "Другое"],
  income: ["Зарплата", "Фриланс", "Подарки", "Инвестиции", "Работа", "Другое"],
};

export function EntryModal({
  entry,
  categories,
  currency,
  demo,
  saving,
  error,
  onClose,
  onSave,
  onDelete,
}: {
  entry: Entry | "new";
  categories: string[];
  currency: string;
  demo: boolean;
  saving: boolean;
  error: string;
  onClose: () => void;
  onSave: (data: EntryInput) => Promise<void>;
  onDelete: (entry: Entry) => void;
}) {
  const today = demo ? "2026-10-18" : localDay();
  const initialType = entry === "new" ? "expense" : entry.type;
  const [type, setType] = useState<Entry["type"]>(initialType);
  const [amount, setAmount] = useState(
    entry === "new" ? "" : formatEntryAmount(entry.amount),
  );
  const [date, setDate] = useState(entry === "new" ? today : entry.date);
  const [selected, setSelected] = useState<Record<Entry["type"], string>>({
    expense: "Еда",
    income: "Зарплата",
    ...(entry === "new" ? {} : { [entry.type]: entry.category }),
  });
  const category = selected[type];
  const [description, setDescription] = useState(
    entry === "new" ? "" : entry.description,
  );
  const [expanded, setExpanded] = useState(false);
  const [query, setQuery] = useState("");
  const [touched, setTouched] = useState(false);
  const [discard, setDiscard] = useState(false);
  const [viewport, setViewport] = useState<{
    height: number;
    bottom: number;
  } | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const scroll = useRef<HTMLDivElement>(null);
  const nextCaret = useRef<number | null>(null);
  const submitting = useRef(false);
  const id = useId();
  const validated = validateEntryAmount(amount);
  const order = [...new Set([...priority[type], ...categories, category])];
  const suggestions = priority[type].includes(category)
    ? priority[type]
    : [category, ...priority[type]].slice(0, 6);
  const shown = expanded
    ? order.filter((name) =>
        `${categoryLabel(name)} ${name}`
          .toLocaleLowerCase()
          .includes(query.trim().toLocaleLowerCase()),
      )
    : suggestions;
  const noteSuggestions =
    type === "income"
      ? ["Oylik maosh", "Frilans", "Pul qaytdi"]
      : category === "Еда"
        ? ["Tushlik", "Oziq-ovqat", "Qahva"]
        : category === "Транспорт"
          ? ["Taksi", "Avtobus", "Metro"]
          : [];

  useEffect(() => {
    const visual = window.visualViewport;
    const update = () =>
      setViewport({
        height: visual?.height ?? window.innerHeight,
        bottom: Math.max(
          0,
          window.innerHeight -
            (visual?.height ?? window.innerHeight) -
            (visual?.offsetTop ?? 0),
        ),
      });
    update();
    visual?.addEventListener("resize", update);
    visual?.addEventListener("scroll", update);
    window.addEventListener("resize", update);
    return () => {
      visual?.removeEventListener("resize", update);
      visual?.removeEventListener("scroll", update);
      window.removeEventListener("resize", update);
    };
  }, []);

  useLayoutEffect(() => {
    if (
      nextCaret.current !== null &&
      input.current === document.activeElement
    ) {
      input.current?.setSelectionRange(nextCaret.current, nextCaret.current);
      nextCaret.current = null;
    }
  }, [amount]);

  function changeAmount(value: string, position: number) {
    const significant = value.slice(0, position).replace(/\s/g, "").length;
    const formatted = formatEntryAmount(value);
    let index = 0,
      count = 0;
    while (index < formatted.length && count < significant) {
      if (!/\s/.test(formatted[index])) count++;
      index++;
    }
    nextCaret.current = index;
    setAmount(formatted);
  }

  function requestClose() {
    if (saving || submitting.current) return;
    const changed =
      entry === "new"
        ? !!(amount.trim() || description.trim())
        : amount !== formatEntryAmount(entry.amount) ||
          date !== entry.date ||
          category !== entry.category ||
          type !== entry.type ||
          description !== entry.description;
    if (changed) {
      setDiscard(true);
      scroll.current?.scrollTo({ top: 0 });
    } else onClose();
  }

  const style = viewport
    ? ({
        "--entry-height": `${viewport.height - 12}px`,
        "--entry-bottom": `${viewport.bottom}px`,
      } as CSSProperties)
    : undefined;

  return (
    <Modal
      title={
        entry === "new"
          ? "Kirim yoki chiqim qo‘shish"
          : "Operatsiyani tahrirlash"
      }
      className={`entry-sheet ${type}`}
      style={style}
      onClose={requestClose}
    >
      <form
        className="entry-form"
        noValidate
        onSubmit={async (event) => {
          event.preventDefault();
          setTouched(true);
          if (saving || submitting.current) return;
          if (validated.error) {
            input.current?.focus();
            return;
          }
          if (!date) {
            document.getElementById(`${id}-date`)?.focus();
            return;
          }
          if (!category) return;
          submitting.current = true;
          try {
            await onSave({
              type,
              amount: validated.value,
              date,
              category,
              description: description.trim(),
            });
          } finally {
            submitting.current = false;
          }
        }}
      >
        <div className="entry-scroll" ref={scroll}>
          {demo && (
            <p className="entry-demo">
              <ShieldCheck size={15} />
              Namuna rejimi — haqiqiy hisobingiz o‘zgarmaydi.
            </p>
          )}
          {discard && (
            <div className="entry-discard" role="alert">
              <strong>Yozuv hali saqlanmagan.</strong>
              <p>Kiritgan ma’lumotlaringizni saqlamasdan chiqasizmi?</p>
              <div>
                <button type="button" onClick={() => setDiscard(false)}>
                  Yozishni davom ettirish
                </button>
                <button type="button" onClick={onClose}>
                  Saqlamasdan chiqish
                </button>
              </div>
            </div>
          )}
          <fieldset className="entry-fields" disabled={saving}>
            <legend className="sr-only">Operatsiya ma’lumotlari</legend>
            <div
              className="entry-type"
              role="group"
              aria-label="Kirim yoki chiqim"
            >
              <button
                type="button"
                aria-pressed={type === "expense"}
                className={type === "expense" ? "chosen" : ""}
                onClick={() => {
                  setType("expense");
                  setExpanded(false);
                  setQuery("");
                }}
              >
                <span>
                  <ArrowUpRight size={22} />
                </span>
                <span>
                  <strong>Chiqim</strong>
                  <small>Pul sarfladim</small>
                </span>
                {type === "expense" && <Check size={17} />}
              </button>
              <button
                type="button"
                aria-pressed={type === "income"}
                className={type === "income" ? "chosen" : ""}
                onClick={() => {
                  setType("income");
                  setExpanded(false);
                  setQuery("");
                }}
              >
                <span>
                  <ArrowDownLeft size={22} />
                </span>
                <span>
                  <strong>Kirim</strong>
                  <small>Pul oldim</small>
                </span>
                {type === "income" && <Check size={17} />}
              </button>
            </div>
            <div
              className={`entry-amount ${touched && validated.error ? "invalid" : ""} ${amount.replace(/\D/g, "").length > 10 ? "long" : ""}`}
            >
              <label htmlFor={`${id}-amount`}>
                Qancha {type === "expense" ? "sarfladingiz" : "pul oldingiz"}?
              </label>
              <div>
                <input
                  ref={input}
                  id={`${id}-amount`}
                  type="text"
                  inputMode="decimal"
                  enterKeyHint="next"
                  autoComplete="off"
                  spellCheck={false}
                  maxLength={32}
                  placeholder="0"
                  value={amount}
                  aria-label={`Summa (${currency})`}
                  aria-invalid={touched && !!validated.error}
                  aria-describedby={`${id}-amount-hint`}
                  onChange={(event) =>
                    changeAmount(
                      event.target.value,
                      event.target.selectionStart ?? event.target.value.length,
                    )
                  }
                  onKeyDown={(event) => {
                    if (event.key === "Enter") {
                      event.preventDefault();
                      document.getElementById(`${id}-note`)?.focus();
                    }
                  }}
                  onBlur={() => setTouched(true)}
                />
                <span>{currency}</span>
              </div>
              <p
                id={`${id}-amount-hint`}
                role={touched && validated.error ? "alert" : undefined}
              >
                {touched && validated.error
                  ? validated.error
                  : "Masalan: 25 000 yoki 25 000,50"}
              </p>
            </div>

            <section
              className="entry-categories"
              aria-labelledby={`${id}-category-label`}
            >
              <div className="entry-section-heading">
                <h3 id={`${id}-category-label`}>Kategoriya</h3>
                <span>
                  <Check size={13} />
                  {categoryLabel(category)}
                </span>
              </div>
              {expanded && (
                <label className="entry-category-search">
                  <Search size={18} />
                  <input
                    type="search"
                    placeholder="Kategoriyani qidirish"
                    aria-label="Kategoriyani qidirish"
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                  />
                </label>
              )}
              <div
                className="entry-category-grid"
                role="group"
                aria-label="Kategoriya tanlash"
              >
                {shown.map((name) => (
                  <button
                    key={name}
                    type="button"
                    aria-pressed={category === name}
                    className={category === name ? "chosen" : ""}
                    onClick={() =>
                      setSelected((current) => ({ ...current, [type]: name }))
                    }
                  >
                    <CategoryIcon name={name} />
                    <span>{categoryLabel(name)}</span>
                    {category === name && (
                      <Check className="category-check" size={13} />
                    )}
                  </button>
                ))}
              </div>
              {!shown.length && (
                <p className="entry-search-empty">
                  Kategoriya topilmadi. Qidiruvni o‘zgartiring.
                </p>
              )}
              <button
                type="button"
                className="entry-category-expand"
                aria-expanded={expanded}
                onClick={() => {
                  setExpanded((value) => !value);
                  setQuery("");
                }}
              >
                {expanded ? "Qisqartirish" : "Barcha kategoriyalar"}
                <ChevronDown size={16} className={expanded ? "rotated" : ""} />
              </button>
            </section>

            <div className="entry-note">
              <label htmlFor={`${id}-note`}>
                Izoh <span>ixtiyoriy</span>
              </label>
              <textarea
                id={`${id}-note`}
                rows={2}
                maxLength={2000}
                placeholder={
                  type === "expense"
                    ? "Nimaga sarfladingiz? Masalan, ishga taksi."
                    : "Pul qayerdan keldi? Masalan, oylik maosh."
                }
                value={description}
                onChange={(e) => setDescription(e.target.value)}
              />
              {!description && !!noteSuggestions.length && (
                <div className="entry-note-suggestions">
                  {noteSuggestions.map((note) => (
                    <button
                      type="button"
                      key={note}
                      onClick={() => setDescription(note)}
                    >
                      {note}
                    </button>
                  ))}
                </div>
              )}
              {description.length > 1800 && (
                <span className="entry-note-count">
                  {description.length}/2000
                </span>
              )}
            </div>

            <div className="entry-date">
              <div className="entry-section-heading">
                <h3>Sana</h3>
              </div>
              <div className="entry-date-controls">
                <button
                  type="button"
                  aria-pressed={date === today}
                  onClick={() => setDate(today)}
                >
                  Bugun
                </button>
                <button
                  type="button"
                  aria-pressed={date === previousDay(today)}
                  onClick={() => setDate(previousDay(today))}
                >
                  Kecha
                </button>
                <label>
                  <CalendarDays size={17} />
                  <input
                    id={`${id}-date`}
                    type="date"
                    required
                    aria-label="Operatsiya sanasi"
                    value={date}
                    onChange={(e) => setDate(e.target.value)}
                  />
                </label>
              </div>
              {!date && (
                <p className="entry-field-error">
                  Operatsiya sanasini tanlang.
                </p>
              )}
            </div>
          </fieldset>
          {error && (
            <p className="entry-field-error entry-server-error" role="alert">
              {error}
            </p>
          )}
        </div>
        <div className="entry-save-bar">
          {entry !== "new" && (
            <button
              type="button"
              className="entry-delete"
              onClick={() => onDelete(entry)}
              disabled={saving}
              aria-label="Operatsiyani o‘chirish"
            >
              <Trash2 size={20} />
            </button>
          )}
          <button
            className="button primary entry-save"
            type="submit"
            disabled={saving}
          >
            {saving ? (
              <span className="spinner small-spinner" />
            ) : (
              <Check size={20} />
            )}
            {saving
              ? "Saqlanmoqda…"
              : type === "expense"
                ? "Chiqimni saqlash"
                : "Kirimni saqlash"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
