"use client";
import {
  Baby, BriefcaseBusiness, CarFront, CircleHelp, Coffee, Dog, Dumbbell,
  Gamepad2, Gift, GraduationCap, Heart, House, Laptop, Music, Phone,
  Plane, Scale, Shirt, ShoppingBag, ShoppingCart, TrendingUp, Utensils,
  Wallet, Wrench, ArrowLeftRight,
} from "lucide-react";
import { useCategories } from "./category-provider";

export const categoryIcons = {
  food: {Icon:Utensils,label:"Oziq-ovqat"}, car:{Icon:CarFront,label:"Transport"},
  home:{Icon:House,label:"Uy-joy"}, shirt:{Icon:Shirt,label:"Kiyim"},
  game:{Icon:Gamepad2,label:"Hordiq"}, heart:{Icon:Heart,label:"Salomatlik"},
  book:{Icon:GraduationCap,label:"Ta’lim"}, work:{Icon:BriefcaseBusiness,label:"Ish"},
  phone:{Icon:Phone,label:"Aloqa"}, gift:{Icon:Gift,label:"Sovg‘alar"},
  wallet:{Icon:Wallet,label:"Hamyon"}, trend:{Icon:TrendingUp,label:"Investitsiya"},
  laptop:{Icon:Laptop,label:"Frilans"}, transfer:{Icon:ArrowLeftRight,label:"O‘tkazmalar"},
  scale:{Icon:Scale,label:"Balans"}, sport:{Icon:Dumbbell,label:"Sport"},
  coffee:{Icon:Coffee,label:"Qahva"}, plane:{Icon:Plane,label:"Sayohat"},
  pet:{Icon:Dog,label:"Uy hayvonlari"}, cart:{Icon:ShoppingCart,label:"Xaridlar"},
  baby:{Icon:Baby,label:"Bolalar"}, music:{Icon:Music,label:"Musiqa"},
  tools:{Icon:Wrench,label:"Ta’mirlash"}, other:{Icon:CircleHelp,label:"Boshqa"},
};
const defaults: Record<string,string>={Еда:"food",Кафе:"coffee",Транспорт:"car",Такси:"car",Зарплата:"wallet",Пополнение:"wallet",Фриланс:"laptop",Здоровье:"heart",Образование:"book",Жильё:"home",Жилье:"home",Одежда:"shirt",Связь:"phone",Подарки:"gift",Инвестиции:"trend",Работа:"work",Другое:"other",Развлечения:"game",Переводы:"transfer",Сверка:"scale"};
export function defaultCategoryIcon(name:string){return defaults[name]??"cart";}
export function CategoryGlyph({icon,size=20}:{icon:string;size?:number}){const Icon=categoryIcons[icon as keyof typeof categoryIcons]?.Icon??ShoppingBag;return <Icon size={size} strokeWidth={1.8} aria-hidden="true"/>;}
export function CategoryIcon({name,size=20}:{name:string;size?:number}){
  const {catalog}=useCategories();
  const record=catalog.find(item=>item.name===name);
  return <CategoryGlyph icon={record?.icon??defaultCategoryIcon(name)} size={size}/>;
}
