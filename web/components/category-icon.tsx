import {
  BriefcaseBusiness,
  CarFront,
  CircleHelp,
  Gift,
  GraduationCap,
  Heart,
  House,
  Laptop,
  Phone,
  Shirt,
  ShoppingBag,
  TrendingUp,
  Utensils,
  Wallet,
} from "lucide-react";

export function CategoryIcon({
  name,
  size = 20,
}: {
  name: string;
  size?: number;
}) {
  const icons = {
    Еда: Utensils,
    Кафе: Utensils,
    Транспорт: CarFront,
    Такси: CarFront,
    Зарплата: Wallet,
    Пополнение: Wallet,
    Фриланс: Laptop,
    Здоровье: Heart,
    Образование: GraduationCap,
    Жильё: House,
    Жилье: House,
    Одежда: Shirt,
    Связь: Phone,
    Подарки: Gift,
    Инвестиции: TrendingUp,
    Работа: BriefcaseBusiness,
    Другое: CircleHelp,
  };
  const Icon = icons[name as keyof typeof icons] ?? ShoppingBag;
  return <Icon size={size} strokeWidth={1.8} aria-hidden="true" />;
}
