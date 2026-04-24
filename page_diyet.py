"""
page_diyet.py  —  Haftalık Diyet Takibi içerik modülü
app.py tarafından çağrılır.
"""

import streamlit as st
import pandas as pd
from utils import (
    DAYS, MEALS,
    prepare_image, recognize_food_vlm,
    get_nutrition_per_100g, scale_nutrition,
    calc_bmi, bmi_category, calc_tdee, ACTIVITY_MULT,
    translate_food_name, get_default_gram_per_piece,
    init_session_state,
)


def _init_state():
    init_session_state()


def _sidebar_metrics():
    bm = st.session_state.body_metrics
    with st.sidebar:
        st.header("⚖️ Vücut Metrikleri")
        bm["height"]   = st.number_input("Boy (cm)",  100, 250, bm["height"], 1)
        bm["weight"]   = st.number_input("Kilo (kg)",  30, 300, bm["weight"], 1)
        bm["age"]      = st.number_input("Yaş",        10, 100, bm["age"],    1)
        bm["gender"]   = st.radio("Cinsiyet", ["Erkek", "Kadın"], horizontal=True,
                                   index=0 if bm["gender"] == "Erkek" else 1)
        bm["activity"] = st.selectbox("Aktivite Seviyesi", list(ACTIVITY_MULT.keys()),
                                       index=list(ACTIVITY_MULT.keys()).index(bm["activity"]))
        st.divider()

        bmi          = calc_bmi(bm["weight"], bm["height"])
        cat, icon    = bmi_category(bmi)
        tdee         = calc_tdee(bm["weight"], bm["height"], bm["age"],
                                 bm["gender"], bm["activity"])

        st.metric("BMI",          f"{bmi}  {icon} {cat}")
        st.metric("Günlük Hedef", f"{tdee} kcal")
        st.metric("Kilo / Boy",   f"{bm['weight']} kg / {bm['height']} cm")

        bmi_norm  = min(max((bmi - 10) / 30, 0), 1)
        bar_color = (
            "#1D9E75" if cat == "Normal"
            else ("#EF9F27" if cat in ("Zayıf", "Fazla Kilolu") else "#E24B4A")
        )
        st.markdown(
            f"<div style='background:#eee;border-radius:6px;height:10px;margin-top:4px'>"
            f"<div style='width:{bmi_norm*100:.0f}%;background:{bar_color};"
            f"height:10px;border-radius:6px'></div></div>"
            f"<div style='display:flex;justify-content:space-between;font-size:11px;color:#888'>"
            f"<span>Zayıf</span><span>Normal</span><span>Fazla</span><span>Obez</span></div>",
            unsafe_allow_html=True,
        )
        st.divider()
        if st.button("🗑️ Haftalık Kaydı Sıfırla", use_container_width=True):
            st.session_state.weekly_log = {
                day: {meal: [] for meal in MEALS} for day in DAYS
            }
            st.success("Kayıtlar temizlendi.")

    return bm, bmi_category(calc_bmi(bm["weight"], bm["height"]))[0], \
           calc_tdee(bm["weight"], bm["height"], bm["age"], bm["gender"], bm["activity"])


def render():
    _init_state()
    st.header("📅 Haftalık Diyet Takibi")
    st.caption("Boy, kilo ve BMI değerlendirmesi · Günlük öğün kaydı · Haftalık özet")

    bm, bmi_cat, tdee = _sidebar_metrics()
    bmi = calc_bmi(bm["weight"], bm["height"])

    # ---------------------------------------------------------------- Öğün Ekle
    st.subheader("➕ Öğün Ekle")
    col_day, col_meal = st.columns(2)
    with col_day:
        selected_day  = st.selectbox("Gün",  DAYS,  key="add_day")
    with col_meal:
        selected_meal = st.selectbox("Öğün", MEALS, key="add_meal")

    input_method = st.radio(
        "Giriş Yöntemi", ["✍️ Yazarak", "📷 Fotoğraf ile"],
        horizontal=True, key="input_method"
    )

    if input_method == "✍️ Yazarak":
        food_text = st.text_input(
            "Yiyecek adı (Türkçe veya İngilizce)",
            placeholder="örn: zeytin, ceviz, tavuk göğsü, apple...",
            key="food_text_input",
        )

        # Girilen addan varsayılan gram/adet hesapla
        default_gppiece = get_default_gram_per_piece(food_text) if food_text else None

        # Giriş modu: gram, adet, ya da ikisi birden
        gmode = st.radio(
            "Miktar",
            ["⚖️ Gram/ml", "🔢 Adet (gram otomatik)"],
            horizontal=True, key="gram_mode",
        )

        final_grams = 150.0

        if gmode == "⚖️ Gram/ml":
            final_grams = float(st.number_input("Gram / ml", 1, 2000, 150, 5, key="gram_only"))
        else:
            col_adet, col_info = st.columns([1, 3])
            with col_adet:
                pieces = st.number_input("Adet", 1, 500, 5, 1, key="pieces_only")
            with col_info:
                if default_gppiece:
                    auto_g = round(pieces * default_gppiece, 1)
                    st.markdown(
                        f"<div style='padding-top:28px;font-size:13px;color:#555'>"
                        f"{pieces} adet × {default_gppiece}g/adet = <b>{auto_g}g</b></div>",
                        unsafe_allow_html=True,
                    )
                    final_grams = auto_g
                else:
                    gppiece = st.number_input(
                        "Gram/adet (bu ürün için tahmin yok, gir)",
                        0.5, 500.0, 5.0, 0.5, key="gppiece_manual",
                    )
                    final_grams = round(pieces * gppiece, 1)
                    st.caption(f"Toplam: {pieces} × {gppiece}g = **{final_grams}g**")

        if st.button("➕ Kaydet", key="save_text", use_container_width=True) and food_text.strip():
            en_name = translate_food_name(food_text.strip())
            with st.spinner("Besin değerleri aranıyor..."):
                n100 = get_nutrition_per_100g(food_text.strip(), en_name)
            if n100 is None:
                st.warning(
                    f"'{food_text}' için besin verisi bulunamadı. "
                    f"İngilizce denendi: '{en_name}'. Daha açık bir isim yazın."
                )
            else:
                scaled = scale_nutrition(n100, final_grams)
                if gmode == "🔢 Adet (gram otomatik)":
                    display_name = f"{food_text.strip()} ({int(pieces)} adet, {final_grams}g)"
                else:
                    display_name = food_text.strip()
                entry = {
                    "name":   display_name,
                    "grams":  final_grams,
                    "source": n100["source"],
                    **{k: scaled.get(k) for k in ("kcal","protein","fat","carbs","fiber")},
                }
                st.session_state.weekly_log[selected_day][selected_meal].append(entry)
                kcal_s = f"{entry['kcal']} kcal" if entry["kcal"] else "?"
                st.success(f"✅ {display_name} eklendi — {final_grams}g / {kcal_s}")
    else:
        photo = st.file_uploader("Yemek fotoğrafı yükle", type=["jpg","png","jpeg"],
                                  key="photo_upload")
        if photo is not None:
            cropped_arr, b64 = prepare_image(photo)
            st.image(cropped_arr, width=300, caption="Yüklenen fotoğraf")
            col_g2, _ = st.columns([1, 3])
            with col_g2:
                gram_photo = st.number_input("Gram / ml", 1, 2000, 150, 10, key="gram_photo")

            if st.button("🔍 Tanı ve Kaydet", key="save_photo", use_container_width=True):
                with st.spinner("Yemek tanınıyor..."):
                    try:
                        fi = recognize_food_vlm(b64)
                    except Exception as e:
                        st.error(f"Yemek tanıma başarısız: {e}")
                        st.stop()

                t_name = fi.get("turkish_name", "Bilinmiyor")
                e_name = fi.get("english_name",  "unknown")
                est_g  = float(fi.get("estimated_grams") or gram_photo)
                st.info(f"Tanınan: **{t_name}** *(~{est_g:.0f}g)* — güven: {fi.get('confidence','?')}")

                with st.spinner("Besin değerleri alınıyor..."):
                    n100 = get_nutrition_per_100g(t_name, e_name)
                if n100 is None:
                    st.warning(f"'{t_name}' için besin verisi bulunamadı.")
                else:
                    scaled = scale_nutrition(n100, est_g)
                    entry  = {"name": t_name, "grams": est_g, "source": n100["source"],
                              **{k: scaled.get(k) for k in ("kcal","protein","fat","carbs","fiber")}}
                    st.session_state.weekly_log[selected_day][selected_meal].append(entry)
                    kcal_s = f"{entry['kcal']} kcal" if entry["kcal"] else "?"
                    st.success(f"✅ {t_name} eklendi — {est_g:.0f}g / {kcal_s}")

    st.divider()

    # --------------------------------------------------------- Günlük Kayıtlar
    st.subheader("📋 Günlük Öğün Kayıtları")
    tabs = st.tabs(DAYS)
    for tab, day in zip(tabs, DAYS):
        with tab:
            day_log   = st.session_state.weekly_log[day]
            day_total = {k: 0.0 for k in ("kcal","protein","fat","carbs","fiber")}
            has_any   = False

            for meal in MEALS:
                entries = day_log[meal]
                if not entries:
                    continue
                has_any = True
                st.markdown(f"**{meal}**")
                for i, e in enumerate(entries):
                    col_info, col_del = st.columns([9, 1])
                    with col_info:
                        kcal_s = f"{e['kcal']} kcal" if e.get("kcal") else "?"
                        prot   = f"P:{e.get('protein','?')}g" if e.get("protein") else ""
                        fat    = f"Y:{e.get('fat','?')}g"     if e.get("fat")     else ""
                        carb   = f"K:{e.get('carbs','?')}g"   if e.get("carbs")   else ""
                        st.markdown(
                            f"<span style='font-size:14px'>🍴 <b>{e['name']}</b> "
                            f"<span style='color:#888'>({e['grams']:.0f}g)</span> — "
                            f"{kcal_s}  <span style='color:#aaa;font-size:12px'>"
                            f"{prot} {fat} {carb}</span></span>",
                            unsafe_allow_html=True,
                        )
                    with col_del:
                        if st.button("✕", key=f"del_{day}_{meal}_{i}", help="Sil"):
                            st.session_state.weekly_log[day][meal].pop(i)
                            st.rerun()
                    for k in day_total:
                        if e.get(k):
                            day_total[k] += e[k]

            if not has_any:
                st.caption("Bu gün için henüz öğün eklenmedi.")
            else:
                day_kcal = round(day_total["kcal"])
                pct      = min(day_kcal / tdee, 1.0)
                bar_col  = "#1D9E75" if pct <= 1.0 else "#E24B4A"
                st.markdown(
                    f"<div style='margin-top:12px;font-size:13px;color:#555'>"
                    f"Günlük toplam: <b>{day_kcal} kcal</b> / hedef {tdee} kcal</div>"
                    f"<div style='background:#eee;border-radius:6px;height:10px;margin:4px 0 8px'>"
                    f"<div style='width:{pct*100:.0f}%;background:{bar_col};"
                    f"height:10px;border-radius:6px'></div></div>",
                    unsafe_allow_html=True,
                )
                mc1, mc2, mc3, mc4 = st.columns(4)
                mc1.metric("Protein",      f"{round(day_total['protein'],1)}g")
                mc2.metric("Yağ",           f"{round(day_total['fat'],1)}g")
                mc3.metric("Karbonhidrat",  f"{round(day_total['carbs'],1)}g")
                mc4.metric("Lif",           f"{round(day_total['fiber'],1)}g")

    st.divider()

    # ------------------------------------------------------- Haftalık Özet
    st.subheader("📈 Haftalık Özet ve Değerlendirme")

    daily_totals = {}
    for day in DAYS:
        t = {k: 0.0 for k in ("kcal","protein","fat","carbs","fiber")}
        for meal in MEALS:
            for e in st.session_state.weekly_log[day][meal]:
                for k in t:
                    if e.get(k):
                        t[k] += e[k]
        daily_totals[day] = {k: round(v, 1) for k, v in t.items()}

    logged_days = [d for d in DAYS if daily_totals[d]["kcal"] > 0]
    n_logged    = len(logged_days)

    if n_logged == 0:
        st.info("Henüz öğün kaydı yok. Kayıt ekleyince grafik ve değerlendirme burada çıkar.")
        return

    df_chart = pd.DataFrame({
        "Gün":    DAYS,
        "Kalori": [daily_totals[d]["kcal"] for d in DAYS],
        "Hedef":  [tdee] * 7,
    }).set_index("Gün")
    st.bar_chart(df_chart[["Kalori", "Hedef"]], height=260)
    st.caption("Mavi = Günlük alınan kalori  ·  Turuncu = Günlük hedef")

    week = {k: round(sum(daily_totals[d][k] for d in logged_days), 1) for k in ("kcal","protein","fat","carbs","fiber")}
    avg  = {k: round(week[k] / n_logged, 1) for k in week}

    wc1, wc2, wc3, wc4, wc5 = st.columns(5)
    wc1.metric("Ort. Kalori",      f"{avg['kcal']} kcal")
    wc2.metric("Ort. Protein",     f"{avg['protein']}g")
    wc3.metric("Ort. Yağ",          f"{avg['fat']}g")
    wc4.metric("Ort. Karbonhidrat", f"{avg['carbs']}g")
    wc5.metric("Ort. Lif",          f"{avg['fiber']}g")

    st.markdown("#### 🧑‍⚕️ Değerlendirme")
    diff     = avg["kcal"] - tdee
    diff_abs = abs(int(diff))
    lines    = []

    if diff_abs <= tdee * 0.05:
        lines.append(f"✅ **Kalori dengesi mükemmel.** Ort. {avg['kcal']} kcal/gün ≈ hedef {tdee} kcal/gün.")
    elif diff > 0:
        lines.append(
            f"⚠️ **Fazla kalori.** Günlük ~{diff_abs} kcal fazla. "
            f"Haftalık {diff_abs*7:,} kcal ≈ {diff_abs*7/7700:.1f} kg birikim riski."
        )
    else:
        lines.append(
            f"⚠️ **Düşük kalori.** Günlük ~{diff_abs} kcal eksik. "
            f"Kas kaybı ve yorgunluğa yol açabilir."
        )

    prot_min   = round(bm["weight"] * 0.8)
    prot_ideal = round(bm["weight"] * 1.6)
    if avg["protein"] < prot_min:
        lines.append(
            f"🔴 **Protein yetersiz.** Min {prot_min}g/gün gerekli (şu an {avg['protein']}g). "
            f"Baklagil, et, yumurta ve süt ürünleri ekleyin."
        )
    elif avg["protein"] < prot_ideal:
        lines.append(f"🟡 **Protein yeterli ama artırılabilir.** İdeal: {prot_ideal}g/gün (şu an {avg['protein']}g).")
    else:
        lines.append(f"✅ **Protein iyi.** {avg['protein']}g/gün — ideal {prot_ideal}g hedefini karşılıyor.")

    if avg["fiber"] < 15:
        lines.append(f"🔴 **Lif çok düşük** ({avg['fiber']}g/gün, hedef ≥25g). Sebze, meyve, tam tahıl ekleyin.")
    elif avg["fiber"] < 25:
        lines.append(f"🟡 **Lif geliştirilmeli** ({avg['fiber']}g/gün). Biraz daha sebze ve tam tahıl ekleyin.")
    else:
        lines.append(f"✅ **Lif yeterli** ({avg['fiber']}g/gün).")

    if bmi_cat == "Obez":
        lines.append(f"🔴 **BMI {bmi} (Obez).** Bir diyetisyenle görüşmeniz önerilir.")
    elif bmi_cat == "Fazla Kilolu":
        lines.append(f"🟡 **BMI {bmi} (Fazla Kilolu).** Hafif kalori kısıtlaması ve egzersiz önerilir.")
    elif bmi_cat == "Zayıf":
        lines.append(f"🔵 **BMI {bmi} (Zayıf).** Kalori ve protein alımınızı artırın.")
    else:
        lines.append(f"✅ **BMI {bmi} — Normal.** Mevcut düzeninizi sürdürün.")

    if n_logged < 7:
        lines.append(f"ℹ️ {n_logged}/7 gün kayıt mevcut. Değerlendirme mevcut kayıtlara göre yapıldı.")

    for line in lines:
        st.markdown(f"> {line}")