"use client";

import { useState } from "react";
import { Archive, ArchiveRestore, Check, ChevronDown, ChevronRight, Pencil, Plus, Search } from "lucide-react";
import { request } from "../lib/api";
import { type CategoryDetails } from "./category-provider";
import { CategoryGlyph, CategoryIcon, categoryIcons, defaultCategoryIcon } from "./category-icon";
import { Modal } from "./dialog";
import { useLanguage } from "./language-provider";

type Editor = { key: string | null; name: string; icon: string; parent: string; originalLabel: string; nameUz:string; nameRu:string };
export function CategoryManager({categories, authenticated, onChange}: {
  categories: CategoryDetails[];
  authenticated: boolean;
  onChange: (items:CategoryDetails[])=>void;
}) {
  const { t, categoryLabel, language } = useLanguage();
  const [query,setQuery]=useState("");
  const [showArchived,setShowArchived]=useState(false);
  const [expanded,setExpanded]=useState<string[]>([]);
  const [editor,setEditor]=useState<Editor|null>(null);
  const [iconsOpen,setIconsOpen]=useState(false);
  const [iconQuery,setIconQuery]=useState("");
  const [iconTopic,setIconTopic]=useState("");
  const [saving,setSaving]=useState(false);
  const [error,setError]=useState("");
  const [notice,setNotice]=useState("");
  const visibleIcons=Object.entries(categoryIcons).filter(([key,{label,topic}])=>(!iconTopic||topic===iconTopic)&&`${key} ${label} ${t(label)} ${t(topic)}`.toLocaleLowerCase().includes(iconQuery.toLocaleLowerCase()));
  const roots=categories.filter(item=>!item.parent_name);
  const matches=(item:CategoryDetails)=>`${item.name} ${categoryLabel(item.name)}`.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase());
  const visible=roots.filter(root=>(Boolean(root.archived)===showArchived||categories.some(item=>item.parent_name===root.name&&Boolean(item.archived)===showArchived))&&(matches(root)||categories.some(item=>item.parent_name===root.name&&Boolean(item.archived)===showArchived&&matches(item))));
  async function archive(){
    if(!editor?.key||saving)return;
    setSaving(true);setError("");
    const item=categories.find(item=>item.name===editor.key)!;
    try{
      const updated=authenticated?await request<CategoryDetails[]>("/category-settings/archive",{method:"POST",body:JSON.stringify({key:item.name,archived:!item.archived})}):categories.map(row=>row.name===item.name||row.parent_name===item.name?{...row,archived:!item.archived}:row);
      onChange(updated);setEditor(null);setNotice(item.archived?"Arxivdan tiklandi.":"Kategoriya arxivlandi.");
    }catch(error){setError(error instanceof Error?error.message:"Xatolik yuz berdi.");}finally{setSaving(false);}
  }
  function begin(item?:CategoryDetails,parent?:CategoryDetails) {
    setError("");setNotice("");setIconsOpen(false);setIconQuery("");setIconTopic("");
    setEditor({key:item?.name??null,name:item?categoryLabel(item.name):"",originalLabel:item?categoryLabel(item.name):"",icon:item?.icon??parent?.icon??defaultCategoryIcon(item?.name??parent?.name??""),parent:item?.parent_name??parent?.name??"",nameUz:item?.name_uz??"",nameRu:item?.name_ru??""});
  }
  async function save(event:React.FormEvent) {
    event.preventDefault();
    if(!editor||saving)return;
    const name=editor.name.trim();
    if(!name){setError("Kategoriya nomini kiriting.");return;}
    const normalize=(value:string)=>value.normalize("NFKC").trim().toLocaleLowerCase();
    if(categories.some(item=>item.name!==editor.key&&[item.name,categoryLabel(item.name)].some(label=>normalize(label)===normalize(name)))){
      setError("Bunday kategoriya mavjud.");return;
    }
    setSaving(true);setError("");
    try {
      const original=categories.find(item=>item.name===editor.key);
      // Editing only the icon must not freeze a translated built-in label in one language.
      const label=original&&name===editor.originalLabel?(original.display_name??original.name):name;
      const payload={name:label,icon:editor.icon,parent_name:editor.parent||null,name_uz:editor.nameUz.trim()||null,name_ru:editor.nameRu.trim()||null};
      let updated:CategoryDetails[];
      if(authenticated){
        if(editor.key) updated=await request<CategoryDetails[]>("/category-settings",{method:"PATCH",body:JSON.stringify({...payload,key:editor.key})});
        else {
          await request("/categories",{method:"POST",body:JSON.stringify(payload)});
          updated=await request<CategoryDetails[]>("/category-settings");
        }
      } else {
        updated=original?categories.map(item=>item.name===editor.key?{...item,display_name:label===item.name?null:label,name_uz:editor.nameUz.trim()||null,name_ru:editor.nameRu.trim()||null,icon:editor.icon,parent_name:editor.parent||null}:item):[...categories,{name,display_name:null,name_uz:editor.nameUz.trim()||null,name_ru:editor.nameRu.trim()||null,icon:editor.icon,parent_name:editor.parent||null,source:"custom"}];
      }
      onChange(updated);
      if(editor.parent)setExpanded(current=>[...new Set([...current,editor.parent])]);
      setEditor(null);setNotice(authenticated?"Saqlandi.":"Namuna sozlamasi saqlandi.");
    } catch(error){setError(error instanceof Error?error.message:"Xatolik yuz berdi.");}
    finally {setSaving(false);}
  }
  return <section className="settings-section category-manager" id="categories">
    <div className="category-manager-heading"><div><h2>{t("Kategoriyalar")}</h2><p>{t("{count} ta kategoriya",{count:roots.length})} · {t("{count} ta subkategoriya",{count:categories.length-roots.length})}</p></div><button className="button primary" onClick={()=>begin()}><Plus size={18}/>{t("Yangi kategoriya")}</button></div>
    <div className="category-state-filter" role="group" aria-label={t("Kategoriya holati")}><button type="button" aria-pressed={!showArchived} onClick={()=>setShowArchived(false)}>{t("Faol")}</button><button type="button" aria-pressed={showArchived} onClick={()=>setShowArchived(true)}>{t("Arxiv")}</button></div>
    <label className="category-manager-search"><Search size={18}/><input type="search" aria-label={t("Kategoriyani qidirish")} placeholder={t("Kategoriyani qidirish")} value={query} onChange={event=>setQuery(event.target.value)}/></label>
    <div className="category-tree">
      {visible.map(root=>{
        const children=categories.filter(item=>item.parent_name===root.name&&Boolean(item.archived)===showArchived);
        const open=expanded.includes(root.name)||Boolean(query.trim());
        return <div className="category-tree-group" key={root.name}>
          <div className="category-tree-row">
            <span className="category-tree-icon"><CategoryIcon name={root.name}/></span>
            <div className="category-tree-name">{children.length>0?<button type="button" className="category-tree-toggle" aria-label={t("{name}: subkategoriyalar",{name:categoryLabel(root.name)})} aria-expanded={open} aria-controls={`children-${encodeURIComponent(root.name)}`} onClick={()=>{if(query.trim())setQuery("");setExpanded(current=>open?current.filter(name=>name!==root.name):[...current,root.name]);}}><strong>{categoryLabel(root.name)}</strong>{open?<ChevronDown size={16}/>:<ChevronRight size={16}/>}</button>:<strong>{categoryLabel(root.name)}</strong>}{children.length>0&&<small>{t("{count} ta subkategoriya",{count:children.length})}</small>}</div>
            <div className="category-tree-actions">
              <button type="button" disabled={Boolean(root.archived)} className="icon-button" aria-label={t("{name}: subkategoriya qo‘shish",{name:categoryLabel(root.name)})} title={t("Subkategoriya qo‘shish")} onClick={()=>begin(undefined,root)}><Plus size={18}/></button>
              <button type="button" className="icon-button" aria-label={t("{name}: tahrirlash",{name:categoryLabel(root.name)})} title={t("Tahrirlash")} onClick={()=>begin(root)}><Pencil size={17}/></button>
            </div>
          </div>
          {children.length>0&&open&&<div className="category-children" id={`children-${encodeURIComponent(root.name)}`}>
            {children.filter(item=>!query.trim()||matches(root)||matches(item)).map(child=><div className="category-tree-row" key={child.name}><span className="category-tree-icon"><CategoryIcon name={child.name} size={18}/></span><div className="category-tree-name"><strong>{categoryLabel(child.name)}</strong></div><button type="button" className="icon-button" aria-label={t("{name}: tahrirlash",{name:categoryLabel(child.name)})} onClick={()=>begin(child)}><Pencil size={17}/></button></div>)}
          </div>}
        </div>;
      })}
      {!visible.length&&<p className="category-search-empty" role="status">{t("Kategoriya topilmadi.")}</p>}
    </div>
    {notice&&<p className="settings-feedback" role="status"><Check size={16}/>{t(notice)}</p>}
    {!authenticated&&<p className="settings-hint">{t("Namuna sozlamasi. Hisobingiz uchun Telegram orqali kiring.")}</p>}
    {editor&&<Modal title={t(editor.key?"Kategoriyani tahrirlash":editor.parent?"Yangi subkategoriya":"Yangi kategoriya")} className="category-editor" onClose={()=>{if(!saving)setEditor(null);}}>
      <form onSubmit={save} className="category-editor-form">
        <div className="category-editor-scroll">
        <fieldset disabled={saving}>
          <label htmlFor="category-name">{t("Nomi")}</label>
          <input id="category-name" value={editor.name} onChange={event=>setEditor({...editor,name:event.target.value,...(language==="uz"?{nameUz:event.target.value}:{nameRu:event.target.value})})} maxLength={100} placeholder={t("Masalan: Sport")} autoComplete="off" required/>
          <details className="category-translations"><summary>{t("Boshqa tildagi nom")}</summary><label htmlFor="category-name-uz">{t("O‘zbekcha nom")}</label><input id="category-name-uz" value={editor.nameUz} onChange={event=>setEditor({...editor,nameUz:event.target.value,...(language==="uz"&&event.target.value?{name:event.target.value}:{})})} maxLength={100} placeholder={t("Ixtiyoriy")}/><label htmlFor="category-name-ru">{t("Ruscha nom")}</label><input id="category-name-ru" value={editor.nameRu} onChange={event=>setEditor({...editor,nameRu:event.target.value,...(language==="ru"&&event.target.value?{name:event.target.value}:{})})} maxLength={100} placeholder={t("Ixtiyoriy")}/><p className="settings-hint">{t("Kategoriya bitta. Tarjima bo‘lmasa asosiy nomi ko‘rinadi.")}</p></details>
          <label htmlFor="category-parent">{t("Asosiy kategoriya")}</label>
          <select id="category-parent" value={editor.parent} onChange={event=>setEditor({...editor,parent:event.target.value})} disabled={Boolean(editor.key&&categories.some(item=>item.parent_name===editor.key))}>
            <option value="">{t("Asosiy kategoriya sifatida")}</option>
            {roots.filter(item=>item.name!==editor.key&&(!item.archived||item.name===editor.parent)).map(item=><option key={item.name} value={item.name}>{categoryLabel(item.name)}</option>)}
          </select>
          <span className="category-field-label">{t("Ikonka")}</span>
          <button type="button" className="category-icon-choice" aria-expanded={iconsOpen} onClick={()=>setIconsOpen(!iconsOpen)}><span className="category-tree-icon"><CategoryGlyph icon={editor.icon} size={24}/></span><span>{t("Ikonkani tanlash")}</span><ChevronDown size={18}/></button>
          {iconsOpen&&<div className="category-icon-browser"><div className="category-icon-filters"><label><span className="sr-only">{t("Ikonkani qidirish")}</span><input type="search" aria-label={t("Ikonkani qidirish")} placeholder={t("Ikonkani qidirish")} value={iconQuery} onChange={event=>setIconQuery(event.target.value)}/></label><label><span className="sr-only">{t("Mavzu")}</span><select aria-label={t("Mavzu")} value={iconTopic} onChange={event=>setIconTopic(event.target.value)}><option value="">{t("Barcha mavzular")}</option>{[...new Set(Object.values(categoryIcons).map(item=>item.topic))].map(topic=><option key={topic} value={topic}>{t(topic)}</option>)}</select></label></div><div className="category-icon-grid" role="group" aria-label={t("Ikonkalar")}>
            {visibleIcons.map(([key,{label}])=><button key={key} type="button" aria-label={t(label)} title={t(label)} aria-pressed={editor.icon===key} onClick={()=>setEditor({...editor,icon:key})}><CategoryGlyph icon={key} size={23}/>{editor.icon===key&&<Check size={12} className="category-icon-check"/>}</button>)}
          </div>{!visibleIcons.length&&<p className="settings-hint" role="status">{t("Ikonka topilmadi.")}</p>}<p className="settings-hint">{t("{count} ta ikonka",{count:visibleIcons.length})}</p></div>}
          {editor.key&&<button type="button" className="category-archive-action" onClick={()=>void archive()}>{categories.find(item=>item.name===editor.key)?.archived?<ArchiveRestore size={18}/>:<Archive size={18}/>} {t(categories.find(item=>item.name===editor.key)?.archived?"Arxivdan tiklash":"Kategoriyani arxivlash")}</button>}
          {editor.key&&<p className="settings-hint">{t("Nom va ikonka o‘zgarsa ham eski operatsiyalar saqlanadi.")}</p>}
        </fieldset>
        {error&&<p className="settings-feedback error" role="alert">{t(error)}</p>}
        </div>
        <div className="category-editor-footer"><button type="button" className="button secondary" disabled={saving} onClick={()=>setEditor(null)}>{t("Bekor qilish")}</button><button type="submit" className="button primary" disabled={saving||!editor.name.trim()}><Check size={18}/>{t(saving?"Saqlanmoqda…":"Saqlash")}</button></div>
      </form>
    </Modal>}
  </section>;
}
