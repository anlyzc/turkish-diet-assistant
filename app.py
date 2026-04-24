"""
app.py — Ana giriş noktası · 4 sekme · Mobil responsive CSS
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
import streamlit as st

st.set_page_config(
    page_title="Akıllı Diyet Asistanı",
    page_icon="🍽️",
    layout="wide",
)

try:
    _ = st.secrets["USDA_API_KEY"]
    _ = st.secrets["HF_TOKEN"]
except KeyError as e:
    st.error(f"secrets.toml içinde eksik anahtar: {e}")
    st.stop()

from utils import init_session_state
init_session_state()

# ── Mobil Responsive CSS ──────────────────────────────────────────────────────
st.markdown("""
<style>
/* ── Genel layout ── */
.block-container {
    padding: 1rem 1rem 2rem 1rem !important;
    max-width: 900px !important;
}

/* ── Mobil: tek sütunlu layout ── */
@media (max-width: 640px) {
    .block-container { padding: 0.5rem 0.5rem 2rem 0.5rem !important; }

    /* Metrikler tam genişlik */
    div[data-testid="metric-container"] {
        min-width: 80px;
        font-size: 12px;
    }

    /* Butonlar tam genişlik */
    .stButton > button {
        width: 100% !important;
        font-size: 14px !important;
        padding: 0.5rem !important;
    }

    /* Input alanları */
    .stTextInput input, .stNumberInput input, .stSelectbox select {
        font-size: 16px !important;
    }

    /* Radio yatay yerine dikey */
    div[data-testid="stHorizontalBlock"] {
        flex-wrap: wrap !important;
        gap: 6px !important;
    }

    /* Tab başlıkları */
    .stTabs [data-baseweb="tab"] {
        padding: 8px 10px !important;
        font-size: 13px !important;
    }

    /* Kolon stacking */
    div[data-testid="column"] {
        min-width: 100% !important;
        flex: 1 1 100% !important;
    }

    /* Görseller tam genişlik */
    img { max-width: 100% !important; }
}

/* ── Genel iyileştirmeler ── */
.stTabs [data-baseweb="tab-list"] {
    gap: 4px;
    overflow-x: auto;
    white-space: nowrap;
    scrollbar-width: none;
}
.stTabs [data-baseweb="tab-list"]::-webkit-scrollbar { display: none; }
.stTabs [data-baseweb="tab"] {
    white-space: nowrap;
    border-radius: 8px 8px 0 0;
}

/* Metrik kartları */
div[data-testid="metric-container"] {
    background: var(--secondary-background-color, #f8f8f8);
    border-radius: 8px;
    padding: 0.6rem 0.8rem;
    border: 1px solid var(--secondary-background-color, #ebebeb);
}

/* Expander daha sıkı */
details > summary { font-weight: 500; }
</style>
""", unsafe_allow_html=True)

# ── Başlık ────────────────────────────────────────────────────────────────────
st.title("🍽️ Akıllı Diyet Asistanı")

# ── 4 Sekme ───────────────────────────────────────────────────────────────────
tab1, tab2, tab3, tab4 = st.tabs([
    "🔍 Anlık Analiz",
    "🍽️ Tek Öğün",
    "📆 Günlük",
    "📅 Haftalık",
])

with tab1:
    from page_analiz import render as r1; r1()

with tab2:
    from page_ogun import render as r2; r2()

with tab3:
    from page_gunluk import render as r3; r3()

with tab4:
    from page_diyet import render as r4; r4()