"use client";
import { createContext, useContext, useState, type ReactNode } from "react";
import { categories } from "../lib/api";

export type CategoryDetails = {
  name: string;
  display_name: string | null;
  icon: string | null;
  parent_name: string | null;
  source: "default" | "custom" | "imported";
};
export const demoCategories: CategoryDetails[] = categories.map(name => ({name, display_name:null, icon:null, parent_name:null, source:"default"}));
const Context = createContext<{catalog:CategoryDetails[];setCatalog:(items:CategoryDetails[])=>void} | null>(null);
export function CategoryProvider({children}:{children:ReactNode}) {
  const [catalog,setCatalog]=useState(demoCategories);
  return <Context.Provider value={{catalog,setCatalog}}>{children}</Context.Provider>;
}
export function useCategories(){const value=useContext(Context);if(!value)throw new Error("CategoryProvider is required");return value;}
