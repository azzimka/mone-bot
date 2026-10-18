"""Per-account category presentation; ledger category keys remain stable."""
import unicodedata
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from bot.models import Category, Transaction
from bot.database.repositories import DEFAULT_CATEGORIES
from bot.services.i18n import CATEGORY_LABELS

ICON_KEYS = {"food", "car", "home", "shirt", "game", "heart", "book", "work", "phone", "gift", "other", "wallet", "trend", "laptop", "transfer", "scale", "sport", "coffee", "plane", "pet", "cart", "baby", "music", "tools"}


def normalized(value: str) -> str:
    return unicodedata.normalize("NFKC", value).strip().casefold()


async def category_catalog(session: AsyncSession, user_id: int) -> list[dict]:
    defaults = {name for _, name in DEFAULT_CATEGORIES}
    historical = set((await session.execute(select(Transaction.category).where(
        Transaction.user_id == user_id, Transaction.category.is_not(None)).distinct())).scalars())
    records = (await session.execute(select(Category).where(Category.user_id == user_id))).scalars().all()
    by_name = {item.name: item for item in records}
    result = []
    for name in sorted(defaults | historical | set(by_name)):
        record = by_name.get(name)
        result.append({"name": name, "display_name": record.display_name if record else None,
                       "icon": record.icon if record and record.icon in ICON_KEYS else None,
                       "parent_name": record.parent_name if record else None,
                       "source": "default" if name in defaults else "custom" if record else "imported"})
    return result


def validate_category(catalog: list[dict], name: str, parent: str | None, key: str | None = None) -> None:
    """Validate names across both languages and enforce a two-level, acyclic tree."""
    names = set()
    for item in catalog:
        if item["name"] == key:
            continue
        names.update(normalized(value) for value in (
            item["name"], item["display_name"] or item["name"], CATEGORY_LABELS.get(item["name"], item["name"])) )
    if normalized(name) in names:
        raise ValueError("Bunday kategoriya mavjud.")
    if parent:
        found = next((item for item in catalog if item["name"] == parent), None)
        if not found or found["parent_name"] or parent == key:
            raise ValueError("Asosiy kategoriyani tanlang.")
        if key and any(item["parent_name"] == key for item in catalog):
            raise ValueError("Subkategoriyali kategoriya asosiy bo‘lib qolishi kerak.")
