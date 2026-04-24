"""
food_input_widget.py
Yeniden kullanılabilir yiyecek/içecek giriş bileşeni.
Kullanım: entry = food_input_form(key_prefix="ogun")
"""
import streamlit as st
import numpy as np
from PIL import Image
import io
from utils import (
    get_nutrition_per_100g, scale_nutrition, translate_food_name,
    get_portion_info, infer_food_type, infer_unit,
    crop_meal_region, array_to_jpeg_bytes, to_base64,
    recognize_food_vlm,
)


def _piece_input(food_name: str, key_prefix: str) -> float:
    """Adet girişi; ürünün ortalama gramını tabloya göre otomatik doldurur."""
    unit_val, unit_str, _ = get_portion_info(food_name) if food_name else (None, "g", "yiyecek")
    col_a, col_info = st.columns([1, 3])
    with col_a:
        pieces = st.number_input("Adet", 1, 500, 1, 1, key=f"{key_prefix}_pieces")
    with col_info:
        if unit_val:
            auto = round(pieces * unit_val, 1)
            st.markdown(
                f"<div style='padding-top:28px;font-size:13px;color:#555'>"
                f"{pieces} adet × <b>{unit_val}{unit_str}/adet</b> = <b>{auto}{unit_str}</b>"
                f"</div>",
                unsafe_allow_html=True,
            )
            return auto
        else:
            gppiece = st.number_input(
                f"Birim ağırlık ({unit_str}/adet) — tahmin yok, gir",
                0.1, 2000.0, 5.0, 0.5, key=f"{key_prefix}_gppiece"
            )
            total = round(pieces * gppiece, 1)
            st.caption(f"Toplam: {pieces} × {gppiece}{unit_str} = **{total}{unit_str}**")
            return total


def food_input_form(key_prefix: str = "fi", show_photo: bool = True) -> dict | None:
    """
    Tek giriş formu (yazarak + fotoğraf).
    dict döner: {name, grams, unit, food_type, kcal, protein, fat, carbs, fiber, source}
    Kaydedilmedi ise None.
    """
    method = st.radio(
        "Giriş yöntemi",
        ["✍️ Yazarak", "📷 Fotoğraf ile"] if show_photo else ["✍️ Yazarak"],
        horizontal=True, key=f"{key_prefix}_method",
    )

    entry = None

    # ── YAZARAK ───────────────────────────────────────────────────────────────
    if method == "✍️ Yazarak":
        food_name = st.text_input(
            "Yiyecek / içecek adı (Türkçe veya İngilizce)",
            placeholder="örn: zeytin, tavuk döner, kutu kola, mercimek çorbası...",
            key=f"{key_prefix}_food_name",
        )

        # Otomatik tip çıkar; kullanıcı değiştirebilir
        auto_tip  = infer_food_type(food_name) if food_name else "yiyecek"
        auto_unit = infer_unit(food_name) if food_name else "g"

        col_tip, col_unit = st.columns(2)
        with col_tip:
            food_type = st.radio(
                "Tür", ["🍽️ Yiyecek", "🥤 İçecek"],
                index=0 if auto_tip == "yiyecek" else 1,
                horizontal=True, key=f"{key_prefix}_type",
            )
            food_type_val = "yiyecek" if food_type.startswith("🍽️") else "içecek"
        with col_unit:
            unit = st.radio(
                "Birim", ["g", "ml"],
                index=0 if auto_unit == "g" else 1,
                horizontal=True, key=f"{key_prefix}_unit",
            )

        gmode = st.radio(
            "Miktar",
            ["⚖️ Gram / ml gir", "🔢 Adet gir (gram otomatik)"],
            horizontal=True, key=f"{key_prefix}_gmode",
        )

        if gmode.startswith("⚖️"):
            default_g = 150 if unit == "g" else 200
            final_amount = float(st.number_input(
                f"Miktar ({unit})", 1, 5000, default_g, 5, key=f"{key_prefix}_gram_direct"
            ))
            pieces_label = None
        else:
            final_amount = _piece_input(food_name, key_prefix)
            pieces_label = None  # display_name already handled below

        col_save, _ = st.columns([2, 4])
        with col_save:
            if st.button("➕ Ekle", key=f"{key_prefix}_add_btn", use_container_width=True):
                if not food_name.strip():
                    st.warning("Lütfen bir yiyecek/içecek adı yazın.")
                else:
                    en_name = translate_food_name(food_name.strip())
                    with st.spinner("Besin değerleri aranıyor..."):
                        n100 = get_nutrition_per_100g(food_name.strip(), en_name)
                    if n100 is None:
                        st.warning(
                            f"'{food_name}' için veri bulunamadı "
                            f"(denenen: '{en_name}'). Farklı bir isim deneyin."
                        )
                    else:
                        scaled = scale_nutrition(n100, final_amount)
                        display = food_name.strip()
                        if gmode.startswith("🔢"):
                            # Show piece count in name
                            pass  # final_amount already computed
                        entry = {
                            "name":      display,
                            "grams":     final_amount,
                            "unit":      unit,
                            "food_type": food_type_val,
                            "source":    n100["source"],
                            **{k: scaled.get(k) for k in ("kcal","protein","fat","carbs","fiber")},
                        }
                        kcal_s = f"{entry['kcal']} kcal" if entry.get("kcal") else "?"
                        st.success(f"✅ {display} eklendi — {final_amount}{unit} / {kcal_s}")

    # ── FOTOĞRAF ──────────────────────────────────────────────────────────────
    else:
        photo = st.file_uploader(
            "Yemek/içecek fotoğrafı yükle",
            type=["jpg","png","jpeg"],
            key=f"{key_prefix}_photo",
        )
        if photo is not None:
            raw = photo.read()
            img_arr = np.array(Image.open(io.BytesIO(raw)).convert("RGB"))
            cropped, _ = crop_meal_region(img_arr)
            st.image(cropped, width=320, caption="Yüklenen fotoğraf")
            b64 = to_base64(array_to_jpeg_bytes(cropped))

            # Fotoğraf tip/birim override
            col_pt, col_pu = st.columns(2)
            with col_pt:
                photo_type = st.radio(
                    "Tür", ["🍽️ Yiyecek", "🥤 İçecek"],
                    horizontal=True, key=f"{key_prefix}_photo_type",
                )
            with col_pu:
                photo_unit = st.radio(
                    "Birim", ["g", "ml"],
                    horizontal=True, key=f"{key_prefix}_photo_unit",
                )
            food_type_val = "yiyecek" if photo_type.startswith("🍽️") else "içecek"
            unit = photo_unit

            if st.button("🔍 Tanı ve Ekle", key=f"{key_prefix}_photo_add", use_container_width=True):
                with st.spinner("Yemek tanınıyor..."):
                    try:
                        fi = recognize_food_vlm(b64)
                    except Exception as e:
                        st.error(f"Tanıma başarısız: {e}")
                        return None

                t_name = fi.get("turkish_name","Bilinmiyor")
                e_name = fi.get("english_name","unknown")
                est_g  = float(fi.get("estimated_grams") or 150)
                conf   = fi.get("confidence","orta")

                # Override unit/type based on detected food
                auto_u = infer_unit(t_name)
                if auto_u == "ml":
                    unit = "ml"
                    food_type_val = "içecek"

                st.info(f"Tanınan: **{t_name}** (~{est_g:.0f}{unit}) — güven: {conf}")

                with st.spinner("Besin değerleri alınıyor..."):
                    n100 = get_nutrition_per_100g(t_name, e_name)

                if n100 is None:
                    st.warning(f"'{t_name}' için besin verisi bulunamadı.")
                else:
                    scaled = scale_nutrition(n100, est_g)
                    entry = {
                        "name":      t_name,
                        "grams":     est_g,
                        "unit":      unit,
                        "food_type": food_type_val,
                        "source":    n100["source"],
                        **{k: scaled.get(k) for k in ("kcal","protein","fat","carbs","fiber")},
                    }
                    kcal_s = f"{entry['kcal']} kcal" if entry.get("kcal") else "?"
                    st.success(f"✅ {t_name} eklendi — {est_g:.0f}{unit} / {kcal_s}")

    return entry


def render_entry_list(entries: list, key_prefix: str) -> list:
    """Öğün listesini gösterir, sil butonu işler. Güncel listeyi döner."""
    if not entries:
        return entries
    for i, e in enumerate(entries):
        col_i, col_d = st.columns([10, 1])
        with col_i:
            kcal_s = f"{e['kcal']} kcal" if e.get("kcal") else "?"
            unit   = e.get("unit","g")
            tip    = "🥤" if e.get("food_type") == "içecek" else "🍴"
            prot   = f"P:{e.get('protein','?')}g" if e.get("protein") else ""
            fat    = f"Y:{e.get('fat','?')}g"     if e.get("fat")     else ""
            carb   = f"K:{e.get('carbs','?')}g"   if e.get("carbs")   else ""
            st.markdown(
                f"<span style='font-size:14px'>{tip} <b>{e['name']}</b> "
                f"<span style='color:#888'>({e['grams']:.0f}{unit})</span> — {kcal_s} "
                f"<span style='color:#aaa;font-size:12px'>{prot} {fat} {carb}</span></span>",
                unsafe_allow_html=True,
            )
        with col_d:
            if st.button("✕", key=f"del_{key_prefix}_{i}"):
                entries.pop(i)
                st.rerun()
    return entries
