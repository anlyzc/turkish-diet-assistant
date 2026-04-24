"""
page_analiz.py — Anlık Yemek Analizi
Analiz sonrası:
  - Doğru/Yanlış feedback
  - Yanlışsa: isim düzeltme + yeniden analiz
  - Kayıt paneli: Tek Öğün / Günlük / Haftalık
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

import streamlit as st
import numpy as np
from PIL import Image
import io
import datetime
import base64

from utils import (
    DAYS, MEALS,
    crop_meal_region, array_to_jpeg_bytes, to_base64,
    recognize_food_vlm, get_nutrition_per_100g, scale_nutrition,
    translate_food_name, init_session_state,
)


def _show_nutrition(n100, npor, estimated_grams):
    st.caption(f"Kaynak: **{n100['source']}** — *{n100['name']}*")
    view = st.radio(
        "Gösterim:",
        ["100g başına", f"Porsiyon (~{estimated_grams:.0f}g)"],
        horizontal=True, key="portion_view",
    )
    data = n100 if view.startswith("100") else npor
    unit = "100g" if view.startswith("100") else f"~{estimated_grams:.0f}g"

    def fmt(v): return f"{v}g" if v is not None else "—"

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("🔥 Kalori",      f"{data.get('kcal')} kcal" if data.get("kcal") else "—")
    c2.metric("🥩 Protein",      fmt(data.get("protein")))
    c3.metric("🧈 Yağ",           fmt(data.get("fat")))
    c4.metric("🍞 Karbonhidrat",  fmt(data.get("carbs")))
    c5.metric("🌿 Lif",           fmt(data.get("fiber")))
    st.caption(f"*Tüm değerler {unit} üzerindendir.*")

    with st.expander("📊 100g vs Porsiyon karşılaştırması"):
        labels = ["Kalori (kcal)", "Protein (g)", "Yağ (g)", "Karbonhidrat (g)", "Lif (g)"]
        k100   = [n100.get(k) for k in ("kcal","protein","fat","carbs","fiber")]
        kpor   = [npor.get(k) for k in ("kcal","protein","fat","carbs","fiber")]
        rows   = "".join(
            "<tr><td style='padding:5px 10px'>{l}</td>"
            "<td style='padding:5px 10px;text-align:right'>{a}</td>"
            "<td style='padding:5px 10px;text-align:right;font-weight:500'>{b}</td></tr>".format(
                l=lb, a=a if a is not None else "—", b=b if b is not None else "—"
            )
            for lb, a, b in zip(labels, k100, kpor)
        )
        st.markdown(
            "<table style='width:100%;border-collapse:collapse;font-size:13px'>"
            "<thead><tr>"
            "<th style='padding:5px 10px;text-align:left;border-bottom:1px solid #ddd'>Besin</th>"
            "<th style='padding:5px 10px;text-align:right;border-bottom:1px solid #ddd'>100g</th>"
            f"<th style='padding:5px 10px;text-align:right;border-bottom:1px solid #ddd'>"
            f"~{estimated_grams:.0f}g</th>"
            f"</tr></thead><tbody>{rows}</tbody></table>",
            unsafe_allow_html=True,
        )


def _save_panel(fi, n100, estimated_grams):
    st.divider()
    st.markdown("#### 📌 Bu yemeği kaydet")
    target = st.radio(
        "Nereye eklensin?",
        ["🍽️ Tek Öğün", "📆 Günlük", "📅 Haftalık"],
        horizontal=True, key="save_target",
    )
    t_name = fi.get("turkish_name", "Bilinmiyor")
    npor   = scale_nutrition(n100, estimated_grams)
    entry  = {
        "name":   t_name,
        "grams":  estimated_grams,
        "source": n100["source"],
        **{k: npor.get(k) for k in ("kcal","protein","fat","carbs","fiber")},
    }

    if target == "🍽️ Tek Öğün":
        if st.button("✅ Tek Öğün sekmesine ekle", key="save_to_ogun"):
            st.session_state.single_meal.append(entry)
            kcal_s = f"{entry['kcal']} kcal" if entry.get("kcal") else "?"
            st.success(f"✅ **{t_name}** → Tek Öğün sekmesine eklendi ({kcal_s})")

    elif target == "📆 Günlük":
        meal_choice = st.selectbox("Hangi öğün?", MEALS, key="save_meal_daily")
        if st.button("✅ Günlük sekmeye ekle", key="save_to_daily"):
            day_names = ["Pazartesi","Salı","Çarşamba","Perşembe","Cuma","Cumartesi","Pazar"]
            today = day_names[datetime.datetime.today().weekday()]
            st.session_state.weekly_log[today][meal_choice].append(entry)
            kcal_s = f"{entry['kcal']} kcal" if entry.get("kcal") else "?"
            st.success(f"✅ **{t_name}** → {today} / {meal_choice} eklendi ({kcal_s})")

    else:
        col_d, col_m = st.columns(2)
        with col_d:
            day_choice  = st.selectbox("Hangi gün?",  DAYS,  key="save_day_weekly")
        with col_m:
            meal_choice = st.selectbox("Hangi öğün?", MEALS, key="save_meal_weekly")
        if st.button("✅ Haftalık sekmeye ekle", key="save_to_weekly"):
            st.session_state.weekly_log[day_choice][meal_choice].append(entry)
            kcal_s = f"{entry['kcal']} kcal" if entry.get("kcal") else "?"
            st.success(f"✅ **{t_name}** → {day_choice} / {meal_choice} eklendi ({kcal_s})")


def render():
    init_session_state()

    # Extra session state keys (init_session_state handles the core ones)
    for key, val in [("analiz_correct", None), ("analiz_override_name", None)]:
        if key not in st.session_state:
            st.session_state[key] = val

    st.header("🔍 Anlık Yemek Analizi")
    st.caption("Türk mutfağı dahil tüm yemekleri tanır · Porsiyon bazlı hesaplar")

    uploaded_file = st.file_uploader(
        "Yemek fotoğrafı yükle...", type=["jpg","png","jpeg"], key="analiz_upload"
    )

    if uploaded_file is not None:
        raw_bytes = uploaded_file.read()
        img_array = np.array(Image.open(io.BytesIO(raw_bytes)).convert("RGB"))
        cropped, was_cropped = crop_meal_region(img_array)
        st.image(
            cropped if was_cropped else img_array,
            caption="Tespit edilen yemek bölgesi" if was_cropped else "Orijinal fotoğraf",
        )
        image_b64 = to_base64(array_to_jpeg_bytes(cropped))

        # Yeni fotoğraf yüklenince sıfırla
        if image_b64 != st.session_state.last_image_b64:
            st.session_state.food_info           = None
            st.session_state.nutrition_100g      = None
            st.session_state.last_image_b64      = image_b64
            st.session_state.analiz_correct       = None
            st.session_state.analiz_override_name = None

        if st.button("🔍 Analiz Et", use_container_width=True, key="analiz_btn"):
            with st.spinner("Yemek tanınıyor..."):
                try:
                    st.session_state.food_info = recognize_food_vlm(image_b64)
                except Exception as e:
                    st.error(f"Yemek tanıma başarısız: {e}"); st.stop()
            # Her yeni analizde feedback sıfırla
            st.session_state.analiz_correct       = None
            st.session_state.analiz_override_name = None
            fi = st.session_state.food_info
            with st.spinner("Besin değerleri alınıyor..."):
                try:
                    st.session_state.nutrition_100g = get_nutrition_per_100g(
                        fi.get("turkish_name",""), fi.get("english_name","")
                    )
                except Exception as e:
                    st.error(f"Besin verisi alınamadı: {e}"); st.stop()

    # ── Sonuçlar ──────────────────────────────────────────────────────────────
    if st.session_state.food_info is None:
        return

    fi   = st.session_state.food_info
    n100 = st.session_state.nutrition_100g

    turkish_name    = fi.get("turkish_name", "Bilinmiyor")
    english_name    = fi.get("english_name", "unknown")
    portion_desc    = fi.get("portion_description", "1 porsiyon")
    estimated_grams = float(fi.get("estimated_grams") or 150)
    item_count      = fi.get("item_count")
    confidence      = fi.get("confidence", "orta")
    conf_icon       = {"yüksek":"🟢","orta":"🟡","düşük":"🔴"}.get(confidence,"🟡")

    # Başlık + feedback radio yan yana
    col_title, col_fb = st.columns([5, 4])
    with col_title:
        st.markdown(f"## 🍴 {turkish_name}")
        sub = (f"*{english_name}*  ·  Güven: {conf_icon} {confidence}  ·  "
               f"Porsiyon: **{portion_desc}** (~{estimated_grams:.0f}g)")
        if item_count:
            sub += f"  /  {item_count}"
        st.caption(sub)
    with col_fb:
        st.markdown("<div style='padding-top:18px'></div>", unsafe_allow_html=True)
        fb = st.radio(
            "Tanıma doğru mu?",
            ["⬜ Değerlendirmedim", "✅ Doğru", "❌ Yanlış"],
            index=0, horizontal=True, key="analiz_fb_radio",
        )
        if fb == "✅ Doğru":
            st.session_state.analiz_correct = True
        elif fb == "❌ Yanlış":
            st.session_state.analiz_correct = False

    # ── Yanlış tanındı → düzeltme paneli ─────────────────────────────────────
    if st.session_state.analiz_correct is False:
        st.warning("⚠️ Yemek yanlış tanındı. Aşağıdan düzeltin veya yeniden analiz ettirin.")
        col_fix_name, col_fix_search, col_fix_rerun = st.columns([3, 1.5, 1.5])

        with col_fix_name:
            corrected = st.text_input(
                "Doğru yemek adı (Türkçe)",
                value=st.session_state.analiz_override_name or "",
                placeholder="örn: baklava, mercimek çorbası, pilav...",
                key="analiz_corrected_name",
            )
        with col_fix_search:
            st.markdown("<div style='padding-top:26px'></div>", unsafe_allow_html=True)
            if st.button("🔄 Bu isimle ara", key="analiz_fix_search", use_container_width=True):
                if corrected.strip():
                    en_fix = translate_food_name(corrected.strip())
                    with st.spinner("Besin değerleri aranıyor..."):
                        fixed_n100 = get_nutrition_per_100g(corrected.strip(), en_fix)
                    if fixed_n100:
                        fi2 = dict(st.session_state.food_info)
                        fi2["turkish_name"] = corrected.strip()
                        fi2["english_name"]  = en_fix
                        st.session_state.food_info            = fi2
                        st.session_state.nutrition_100g       = fixed_n100
                        st.session_state.analiz_override_name = corrected.strip()
                        st.session_state.analiz_correct        = True
                        st.rerun()
                    else:
                        st.error(f"'{corrected}' için besin verisi bulunamadı.")
                else:
                    st.warning("Lütfen doğru yemek adını yazın.")

        with col_fix_rerun:
            st.markdown("<div style='padding-top:26px'></div>", unsafe_allow_html=True)
            if st.button("🔁 Yeniden analiz", key="analiz_rerun_btn", use_container_width=True):
                b64_current = st.session_state.last_image_b64
                # Cache bypass: bytes'a 1 null ekle
                raw = base64.b64decode(b64_current)
                new_b64 = base64.b64encode(raw + b"\x00").decode()
                with st.spinner("Yeniden analiz ediliyor..."):
                    try:
                        new_fi = recognize_food_vlm(new_b64)
                    except Exception as e:
                        st.error(f"Yeniden analiz başarısız: {e}"); st.stop()
                st.session_state.food_info      = new_fi
                st.session_state.last_image_b64 = new_b64
                st.session_state.analiz_correct  = None
                st.session_state.analiz_override_name = None
                with st.spinner("Besin değerleri alınıyor..."):
                    st.session_state.nutrition_100g = get_nutrition_per_100g(
                        new_fi.get("turkish_name",""), new_fi.get("english_name","")
                    )
                st.rerun()

    # ── Güncel fi / n100 (override sonrası değişmiş olabilir) ─────────────────
    fi   = st.session_state.food_info
    n100 = st.session_state.nutrition_100g
    estimated_grams = float(fi.get("estimated_grams") or 150)

    if n100 is None:
        st.warning(f"'{fi.get('turkish_name','?')}' için besin verisi bulunamadı.")
    else:
        npor = scale_nutrition(n100, estimated_grams)
        _show_nutrition(n100, npor, estimated_grams)
        _save_panel(fi, n100, estimated_grams)