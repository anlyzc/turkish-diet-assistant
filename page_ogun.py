"""
page_ogun.py — Tek Öğün Analizi
Yazarak + Fotoğraf giriş · Yiyecek/İçecek ayrımı · Haftalık aktarım
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
import streamlit as st
from utils import (
    DAYS, MEALS, calc_bmi, bmi_category, calc_tdee, ACTIVITY_MULT, init_session_state,
)
from food_input_widget import food_input_form, render_entry_list


def render():
    init_session_state()
    st.header("🍽️ Tek Öğün Analizi")
    st.caption("Bir öğünü oluştur · Yazarak veya fotoğraf ile ekle · Besin dengesi değerlendirmesi")

    # ── Kişisel bilgiler ──────────────────────────────────────────────────────
    with st.expander("⚙️ Kişisel bilgiler", expanded=False):
        bm = st.session_state.body_metrics
        c1, c2, c3, c4 = st.columns(4)
        bm["weight"] = c1.number_input("Kilo (kg)", 30, 300, bm["weight"], 1, key="ogun_w")
        bm["height"] = c2.number_input("Boy (cm)", 100, 250, bm["height"], 1, key="ogun_h")
        bm["age"]    = c3.number_input("Yaş", 10, 100, bm["age"], 1,         key="ogun_age")
        bm["gender"] = c4.radio("Cinsiyet", ["Erkek","Kadın"], horizontal=True,
                                 index=0 if bm["gender"]=="Erkek" else 1, key="ogun_sex")

    bm   = st.session_state.body_metrics
    tdee = calc_tdee(bm["weight"], bm["height"], bm["age"], bm["gender"],
                     list(ACTIVITY_MULT.keys())[2])
    meal_target = int(tdee * 0.30)

    # ── Yiyecek Ekle ─────────────────────────────────────────────────────────
    st.subheader("➕ Öğüne Ekle")
    entry = food_input_form(key_prefix="ogun")
    if entry:
        st.session_state.single_meal.append(entry)

    st.divider()

    # ── Öğün İçeriği ─────────────────────────────────────────────────────────
    entries = st.session_state.single_meal
    col_t, col_c = st.columns([7, 3])
    with col_t:
        st.subheader("🍱 Öğün İçeriği")
    with col_c:
        if st.button("🗑️ Öğünü Temizle", key="clear_ogun", use_container_width=True):
            st.session_state.single_meal = []
            st.rerun()

    if not entries:
        st.info("Henüz bu öğüne yiyecek eklenmedi.")
        return

    render_entry_list(entries, "ogun")

    # ── Toplam & Değerlendirme ────────────────────────────────────────────────
    totals = {k: 0.0 for k in ("kcal","protein","fat","carbs","fiber")}
    for e in entries:
        for k in totals:
            if e.get(k): totals[k] += e[k]
    totals = {k: round(v, 1) for k, v in totals.items()}

    st.divider()
    st.subheader("📊 Öğün Toplamı")

    m1,m2,m3,m4,m5 = st.columns(5)
    m1.metric("🔥 Kalori",      f"{totals['kcal']} kcal")
    m2.metric("🥩 Protein",     f"{totals['protein']}g")
    m3.metric("🧈 Yağ",          f"{totals['fat']}g")
    m4.metric("🍞 Karbonhidrat", f"{totals['carbs']}g")
    m5.metric("🌿 Lif",          f"{totals['fiber']}g")

    pct = min((totals["kcal"] or 0) / meal_target, 1.5)
    bar = "#1D9E75" if pct <= 1.0 else "#E24B4A"
    st.markdown(
        f"<div style='font-size:13px;color:#555;margin-top:6px'>"
        f"Tahmini öğün hedefi: <b>{meal_target} kcal</b> (günlük {tdee} kcal ÷ ~%30)</div>"
        f"<div style='background:#eee;border-radius:6px;height:10px;margin:4px 0 12px'>"
        f"<div style='width:{min(pct,1)*100:.0f}%;background:{bar};height:10px;border-radius:6px'>"
        f"</div></div>",
        unsafe_allow_html=True,
    )

    st.subheader("🧑‍⚕️ Öğün Değerlendirmesi")
    lines = []
    diff = totals["kcal"] - meal_target
    if abs(diff) <= meal_target * 0.15:
        lines.append("✅ Kalori dengesi iyi — öğün hedef aralığında.")
    elif diff > 0:
        lines.append(f"⚠️ Kalori fazla: hedefin **{diff:.0f} kcal** üzerinde.")
    else:
        lines.append(f"⚠️ Kalori düşük: hedefin **{abs(diff):.0f} kcal** altında.")

    prot_min = round(bm["weight"] * 0.8 / 3)
    if totals["protein"] < prot_min:
        lines.append(f"🔴 Protein yetersiz: {totals['protein']}g (min ~{prot_min}g önerilir).")
    else:
        lines.append(f"✅ Protein yeterli: {totals['protein']}g.")

    if totals["fiber"] < 5:
        lines.append("🟡 Lif düşük — sebze, meyve veya tam tahıl ekleyin.")
    else:
        lines.append(f"✅ Lif iyi: {totals['fiber']}g.")

    tm = sum(totals.get(k,0) or 0 for k in ("protein","fat","carbs"))
    if tm > 0:
        lines.append(
            f"📐 Makro dağılımı: Protein **{round(totals['protein']/tm*100)}%** · "
            f"Yağ **{round(totals['fat']/tm*100)}%** · "
            f"Karbonhidrat **{round(totals['carbs']/tm*100)}%**"
        )
    for line in lines:
        st.markdown(f"> {line}")

    # ── Haftalık Aktarım ──────────────────────────────────────────────────────
    st.divider()
    st.markdown("#### 📅 Bu öğünü haftalık diyete ekle")
    cwd, cwm, cwb = st.columns([2,2,2])
    with cwd: w_day  = st.selectbox("Gün",  DAYS,  key="ogun_wday")
    with cwm: w_meal = st.selectbox("Öğün", MEALS, key="ogun_wmeal")
    with cwb:
        st.markdown("<div style='padding-top:26px'></div>", unsafe_allow_html=True)
        if st.button("📅 Haftalık sekmeye aktar", key="ogun_to_weekly", use_container_width=True):
            added = 0
            for e in st.session_state.single_meal:
                st.session_state.weekly_log[w_day][w_meal].append(dict(e))
                added += 1
            if added:
                total_k = round(sum(e.get("kcal",0) or 0 for e in st.session_state.single_meal),1)
                st.success(f"✅ {added} öğe → {w_day}/{w_meal} eklendi (toplam {total_k} kcal)")
            else:
                st.warning("Öğünde eklenecek yiyecek yok.")