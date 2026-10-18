import { ChevronRight } from "lucide-react";
import { categoryLabel, type Entry, money } from "../lib/api";
import { CategoryIcon } from "./category-icon";

export function MobileTransactions({
  items,
  onEdit,
}: {
  items: Entry[];
  onEdit: (entry: Entry) => void;
}) {
  if (!items.length) return null;
  return (
    <div className="mobile-transactions">
      <p className="mobile-list-hint">
        Ko‘rish yoki tahrirlash uchun yozuvni bosing.
      </p>
      {items.map((entry) => (
        <button
          type="button"
          className={`mobile-entry-card ${entry.type}`}
          key={entry.id}
          onClick={() => onEdit(entry)}
          aria-label={`${entry.description || categoryLabel(entry.category)}, ${entry.type === "income" ? "kirim" : "chiqim"}, ${money(entry.amount)} ${entry.currency}, ${entry.date.split("-").reverse().join(".")}. Ko‘rish va tahrirlash`}
        >
          <span className="mobile-entry-icon">
            <CategoryIcon name={entry.category} />
          </span>
          <span className="mobile-entry-content">
            <span className="mobile-entry-heading">
              <strong>{categoryLabel(entry.category)}</strong>
              <span>{entry.type === "income" ? "Kirim" : "Chiqim"}</span>
            </span>
            {entry.description && (
              <span className="mobile-entry-note">{entry.description}</span>
            )}
            <span className="mobile-entry-date">
              {entry.date.split("-").reverse().join(".")}
            </span>
            <span className="mobile-entry-amount">
              {entry.type === "income" ? "+" : "−"}
              {money(entry.amount)} <small>{entry.currency}</small>
            </span>
          </span>
          <ChevronRight size={18} className="mobile-entry-chevron" />
        </button>
      ))}
    </div>
  );
}
