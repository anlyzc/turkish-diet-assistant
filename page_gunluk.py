"""
page_gunluk.py — Günlük Değerler
Yazarak + Fotoğraf giriş · Yiyecek/İçecek ayrımı · Gün seçimi · Değerlendirme
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
import streamlit as st
import datetime
from utils import (
    DAYS, MEALS, calc_bmi, bmi_category, calc_tdee, ACTIVITY_MULT, init_session_state,
)
from food_input_widget import food_input_form, render_entry_list


def render():
    init_session_state()
    st.header("📆 Günlük Değerler")
    st.caption("Seçili günün öğünlerini takip et · Yazarak veya fotoğraf ile ekle")

    # ── Kişisel bilgiler ──────────────────────────────────────────────────────
    with st.expander("⚙️ Kişisel bilgiler", expanded=False):
        bm = st.session_state.body_metrics
        c1,c2,c3,c4,c5 = st.columns(5)
        bm["weight"]   = c1.number_input("Kilo (kg)", 30,300, bm["weight"],1, key="gun_w")
        bm["height"]   = c2.number_input("Boy (cm)",100,250, bm["height"],1,  key="gun_h")
        bm["age"]      = c3.number_input("Yaş",10,100,bm["age"],1,             key="gun_age")
        bm["gender"]   = c4.radio("Cinsiyet",["Erkek","Kadın"],horizontal=True,
                                   index=0 if bm["gender"]=="Erkek" else 1,    key="gun_sex")
        bm["activity"] = c5.selectbox("Aktivite",list(ACTIVITY_MULT.keys()),
                                       index=list(ACTIVITY_MULT.keys()).index(bm["activity"]),
                                       key="gun_act")

    bm   = st.session_state.body_metrics
    bmi  = calc_bmi(bm["weight"], bm["height"])
    tdee = calc_tdee(bm["weight"], bm["height"], bm["age"], bm["gender"], bm["activity"])
    cat, icon = bmi_category(bmi)

    hc1, hc2, hc3 = st.columns(3)
    hc1.metric("BMI",          f"{bmi}  {icon} {cat}")
    hc2.metric("Günlük Hedef", f"{tdee} kcal")
    hc3.metric("Kilo / Boy",   f"{bm['weight']} kg / {bm['height']} cm")

    st.divider()

    # ── Gün + öğün seçici ─────────────────────────────────────────────────────
    col_day, col_meal = st.columns(2)
    with col_day:
        selected_day = st.selectbox(
            "Gün", DAYS, index=datetime.datetime.today().weekday(), key="gun_day_sel"
        )
    with col_meal:
        selected_meal = st.selectbox("Öğün", MEALS, key="gun_meal_sel")

    # ── Yiyecek ekle ─────────────────────────────────────────────────────────
    with st.expander(f"➕ {selected_day} — {selected_meal} için ekle", expanded=True):
        entry = food_input_form(key_prefix=f"gun_{selected_day}_{selected_meal}")
        if entry:
            st.session_state.weekly_log[selected_day][selected_meal].append(entry)

    st.divider()

    # ── Günün öğünleri ────────────────────────────────────────────────────────
    day_log   = st.session_state.weekly_log[selected_day]
    day_total = {k: 0.0 for k in ("kcal","protein","fat","carbs","fiber")}
    has_any   = False

    st.subheader(f"📋 {selected_day} — Öğünler")

    for meal in MEALS:
        entries = day_log[meal]
        if not entries:
            continue
        has_any = True
        with st.expander(f"**{meal}** — {len(entries)} öğe", expanded=True):
            meal_kcal = 0.0
            for i, e in enumerate(entries):
                ci, cd = st.columns([10,1])
                with ci:
                    unit   = e.get("unit","g")
                    tip    = "🥤" if e.get("food_type")=="içecek" else "🍴"
                    kcal_s = f"{e['kcal']} kcal" if e.get("kcal") else "?"
                    st.markdown(
                        f"<span style='font-size:13px'>{tip} <b>{e['name']}</b> "
                        f"<span style='color:#888'>({e['grams']:.0f}{unit})</span> — {kcal_s}</span>",
                        unsafe_allow_html=True,
                    )
                with cd:
                    if st.button("✕", key=f"del_gun_{selected_day}_{meal}_{i}"):
                        st.session_state.weekly_log[selected_day][meal].pop(i)
                        st.rerun()
                for k in day_total:
                    if e.get(k): day_total[k] += e[k]
                if e.get("kcal"): meal_kcal += e["kcal"]
            st.caption(f"Bu öğün: **{round(meal_kcal)} kcal**")

    if not has_any:
        st.info(f"{selected_day} için henüz öğün eklenmedi.")
        return

    day_total = {k: round(v,1) for k,v in day_total.items()}
    st.divider()
    st.subheader("📊 Günlük Toplam")

    d1,d2,d3,d4,d5 = st.columns(5)
    d1.metric("🔥 Kalori",      f"{day_total['kcal']} kcal")
    d2.metric("🥩 Protein",     f"{day_total['protein']}g")
    d3.metric("🧈 Yağ",          f"{day_total['fat']}g")
    d4.metric("🍞 Karbonhidrat", f"{day_total['carbs']}g")
    d5.metric("🌿 Lif",          f"{day_total['fiber']}g")

    pct = min((day_total["kcal"] or 0)/tdee, 1.5)
    bar = "#1D9E75" if pct<=1.0 else "#E24B4A"
    diff_str = f"{day_total['kcal']-tdee:+.0f}"
    st.markdown(
        f"<div style='font-size:13px;color:#555;margin-top:6px'>"
        f"Alınan: <b>{day_total['kcal']} kcal</b> / Hedef: <b>{tdee} kcal</b> "
        f"({diff_str} kcal)</div>"
        f"<div style='background:#eee;border-radius:6px;height:12px;margin:6px 0 14px'>"
        f"<div style='width:{min(pct,1)*100:.0f}%;background:{bar};height:12px;border-radius:6px'>"
        f"</div></div>",
        unsafe_allow_html=True,
    )

    # Değerlendirme
    st.subheader("🧑‍⚕️ Günlük Değerlendirme")
    lines = []
    diff = day_total["kcal"] - tdee
    if abs(diff) <= tdee*0.05:
        lines.append(f"✅ Kalori dengesi mükemmel — {day_total['kcal']} kcal ≈ hedef {tdee} kcal.")
    elif diff>0:
        lines.append(f"⚠️ Fazla kalori: hedefinizin **{diff:.0f} kcal** üzerinde.")
    else:
        lines.append(f"⚠️ Düşük kalori: hedefinizin **{abs(diff):.0f} kcal** altında.")

    pmin=round(bm["weight"]*0.8); pideal=round(bm["weight"]*1.6)
    if day_total["protein"]<pmin:
        lines.append(f"🔴 Protein yetersiz: {day_total['protein']}g (min {pmin}g/gün).")
    elif day_total["protein"]<pideal:
        lines.append(f"🟡 Protein artırılabilir: {day_total['protein']}g (ideal {pideal}g).")
    else:
        lines.append(f"✅ Protein iyi: {day_total['protein']}g.")

    if day_total["fiber"]<15:
        lines.append(f"🔴 Lif çok düşük: {day_total['fiber']}g (hedef ≥25g).")
    elif day_total["fiber"]<25:
        lines.append(f"🟡 Lif geliştirilmeli: {day_total['fiber']}g.")
    else:
        lines.append(f"✅ Lif yeterli: {day_total['fiber']}g.")

    tm = sum(day_total.get(k,0) or 0 for k in ("protein","fat","carbs"))
    if tm>0:
        lines.append(
            f"📐 Makro: Protein **{round(day_total['protein']/tm*100)}%** · "
            f"Yağ **{round(day_total['fat']/tm*100)}%** · "
            f"Karbonhidrat **{round(day_total['carbs']/tm*100)}%**"
        )
    for line in lines:
        st.markdown(f"> {line}")

    # ── Başka güne kopyala ────────────────────────────────────────────────────
    st.divider()
    st.markdown("#### 📅 Bu günü başka bir güne kopyala")
    ct, cb = st.columns([3,2])
    with ct:
        target = st.selectbox("Hedef gün", DAYS,
                               index=DAYS.index(selected_day), key="gun_copy_target")
    with cb:
        st.markdown("<div style='padding-top:26px'></div>", unsafe_allow_html=True)
        if st.button("📋 Kopyala", key="gun_copy_btn", use_container_width=True):
            if target==selected_day:
                st.info("Aynı gün — kopyalama yapılmadı.")
            else:
                added=0
                for m in MEALS:
                    for e in day_log[m]:
                        st.session_state.weekly_log[target][m].append(dict(e))
                        added+=1
                st.success(f"✅ {selected_day} → {target}: {added} öğe kopyalandı.") if added else st.warning("Kayıt yok.")

    st.divider()
    if st.button("🗑️ Bu Günü Temizle", key="clear_gun_day"):
        st.session_state.weekly_log[selected_day] = {m:[] for m in MEALS}
        st.rerun()