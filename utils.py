"""
utils.py  —  Ortak yardımcı fonksiyonlar
Her iki sayfa da (Anlık Analiz + Haftalık Diyet) buradan import eder.
"""

import streamlit as st
import requests
import cv2
import numpy as np
from PIL import Image
import io
import base64
import json
import re

# ---------------------------------------------------------------------------
# Sabitler
# ---------------------------------------------------------------------------

DAYS = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]
MEALS = ["Kahvaltı", "Öğle Yemeği", "Akşam Yemeği", "Ara Öğün"]

VLM_CANDIDATES = [
    "Qwen/Qwen2.5-VL-7B-Instruct:nebius",
    "Qwen/Qwen2.5-VL-7B-Instruct:novita",
    "Qwen/Qwen2.5-VL-7B-Instruct:hyperbolic",
    "CohereLabs/aya-vision-32b:cohere",
]

VLM_PROMPT = """Sen Türk ve dünya mutfağı konusunda uzman bir diyetisyensin.
Bu yemek fotoğrafını analiz et ve SADECE aşağıdaki JSON objesini döndür, başka hiçbir şey yazma:

{
  "turkish_name": "<Türkçe yemek adı, örn: Mercimek Çorbası>",
  "english_name": "<İngilizce yemek adı, örn: lentil soup>",
  "portion_description": "<Görseldeki porsiyon açıklaması, örn: 1 kase, 3 adet köfte, 1 dilim>",
  "estimated_grams": <Görseldeki yemeğin tahmini gram/ml ağırlığı, sadece sayı>,
  "item_count": "<Adet bazlı yemekler için sayı ve birim, yoksa null, örn: 3 adet veya null>",
  "confidence": "<yüksek veya orta veya düşük>"
}

Önemli kurallar:
- Türk yemeklerini Türkçe adıyla yaz (köfte, dolma, börek, menemen, pilav, çorba vb.)
- estimated_grams: içecekler için ml, katılar için gram cinsinden tahmin et
- Sadece JSON döndür, açıklama veya markdown ekleme"""


# ---------------------------------------------------------------------------
# Görüntü işleme
# ---------------------------------------------------------------------------

def crop_meal_region(img_array: np.ndarray):
    gray    = cv2.cvtColor(img_array, cv2.COLOR_RGB2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    _, thresh = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return img_array, False
    c = max(contours, key=cv2.contourArea)
    x, y, w, h = cv2.boundingRect(c)
    ih, iw = img_array.shape[:2]
    if w * h > 0.90 * iw * ih:
        return img_array, False
    return img_array[y:y+h, x:x+w], True


def array_to_jpeg_bytes(img_array: np.ndarray) -> bytes:
    bgr = cv2.cvtColor(img_array, cv2.COLOR_RGB2BGR)
    ok, buf = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, 85])
    if not ok:
        raise RuntimeError("JPEG encode başarısız.")
    return bytes(buf)


def to_base64(image_bytes: bytes) -> str:
    return base64.b64encode(image_bytes).decode("utf-8")


def prepare_image(uploaded_file) -> tuple[np.ndarray, str]:
    """UploadedFile → (cropped_array, base64_string)"""
    raw_bytes = uploaded_file.read()
    image     = Image.open(io.BytesIO(raw_bytes)).convert("RGB")
    img_array = np.array(image)
    cropped, _ = crop_meal_region(img_array)
    image_bytes = array_to_jpeg_bytes(cropped)
    return cropped, to_base64(image_bytes)


# ---------------------------------------------------------------------------
# VLM yemek tanıma
# ---------------------------------------------------------------------------

@st.cache_data(show_spinner=False)
def recognize_food_vlm(image_b64: str) -> dict:
    hf_token = st.secrets["HF_TOKEN"]
    url     = "https://router.huggingface.co/v1/chat/completions"
    headers = {"Authorization": f"Bearer {hf_token}", "Content-Type": "application/json"}
    messages = [{
        "role": "user",
        "content": [
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
            {"type": "text", "text": VLM_PROMPT},
        ],
    }]
    last_error = None
    for model_id in VLM_CANDIDATES:
        try:
            resp = requests.post(url, headers=headers,
                                 json={"model": model_id, "max_tokens": 400, "messages": messages},
                                 timeout=60)
            if resp.status_code == 400:
                last_error = f"{model_id}: {resp.json().get('error', {}).get('message', '400')}"
                continue
            resp.raise_for_status()
            raw = resp.json()["choices"][0]["message"]["content"].strip()
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$",           "", raw)
            return json.loads(raw)
        except json.JSONDecodeError:
            last_error = f"{model_id}: JSON parse hatası"
        except requests.HTTPError as e:
            last_error = f"{model_id}: HTTP {e.response.status_code}"
        except Exception as e:
            last_error = f"{model_id}: {e}"
    raise RuntimeError(
        f"Tüm VLM adayları başarısız. Son hata: {last_error} | "
        "Provider etkinleştir: https://huggingface.co/settings/inference-providers"
    )


# ---------------------------------------------------------------------------
# Besin değeri arama  (Open Food Facts → USDA fallback)
# ---------------------------------------------------------------------------

def _off_search(query: str) -> dict | None:
    r = requests.get(
        "https://world.openfoodfacts.org/cgi/search.pl",
        params={"search_terms": query, "search_simple": 1,
                "action": "process", "json": 1,
                "page_size": 5, "fields": "product_name,nutriments"},
        timeout=15,
    )
    r.raise_for_status()
    for p in r.json().get("products", []):
        n = p.get("nutriments", {})
        if n.get("energy-kcal_100g") or n.get("energy-kcal"):
            return p
    return None


def _off_extract(product: dict) -> dict:
    n = product.get("nutriments", {})
    def get(key):
        val = n.get(f"{key}_100g") or n.get(key)
        try:    return round(float(val), 1)
        except: return None
    return {"source": "Open Food Facts", "name": product.get("product_name", "?"),
            "kcal": get("energy-kcal"), "protein": get("proteins"),
            "fat": get("fat"), "carbs": get("carbohydrates"), "fiber": get("fiber")}


def _usda_search(query: str) -> list:
    r = requests.get(
        "https://api.nal.usda.gov/fdc/v1/foods/search",
        headers={"X-Api-Key": st.secrets["USDA_API_KEY"]},
        params={"query": query, "pageSize": 5},
        timeout=15,
    )
    r.raise_for_status()
    return r.json().get("foods", [])


def _usda_extract(foods: list) -> dict:
    nutrients = foods[0].get("foodNutrients", [])
    def find(kw):
        for n in nutrients:
            if kw.lower() in n.get("nutrientName", "").lower():
                try:    return round(float(n["value"]), 1)
                except: pass
        return None
    return {"source": "USDA FoodData Central", "name": foods[0].get("description", "?"),
            "kcal": find("energy"), "protein": find("protein"),
            "fat": find("total lipid"), "carbs": find("carbohydrate"), "fiber": find("fiber")}


@st.cache_data(show_spinner=False)
def get_nutrition_per_100g(turkish_name: str, english_name: str) -> dict | None:
    # Sözlük çevirisiyle İngilizce adı zenginleştir
    dict_english = translate_food_name(turkish_name)

    # Arama listesi: Türkçe, sözlük İngilizcesi, verilen İngilizce, ilk kelimeler
    off_queries = list(dict.fromkeys(filter(None, [
        turkish_name,
        dict_english,
        english_name,
        turkish_name.split()[0] if turkish_name else "",
        dict_english.split()[0]  if dict_english  else "",
    ])))
    usda_queries = list(dict.fromkeys(filter(None, [
        dict_english,
        english_name,
        dict_english.split()[0] if dict_english else "",
    ])))

    for q in off_queries:
        try:
            p = _off_search(q)
            if p:
                r = _off_extract(p)
                if r["kcal"] is not None:
                    return r
        except Exception:
            pass

    for q in usda_queries:
        try:
            foods = _usda_search(q)
            if foods:
                r = _usda_extract(foods)
                if r["kcal"] is not None:
                    return r
        except Exception:
            pass
    return None


def scale_nutrition(base: dict, grams: float) -> dict:
    factor = grams / 100.0
    return {k: round(v * factor, 1) if v is not None else None
            for k in ("kcal", "protein", "fat", "carbs", "fiber")
            for v in [base.get(k)]}


# ---------------------------------------------------------------------------
# Vücut metrikleri & TDEE
# ---------------------------------------------------------------------------

def calc_bmi(weight_kg: float, height_cm: float) -> float:
    h = height_cm / 100
    return round(weight_kg / (h * h), 1)


def bmi_category(bmi: float) -> tuple[str, str]:
    if bmi < 18.5: return "Zayıf",        "🔵"
    if bmi < 25:   return "Normal",        "🟢"
    if bmi < 30:   return "Fazla Kilolu",  "🟡"
    return             "Obez",             "🔴"


ACTIVITY_MULT = {
    "Hareketsiz (masa başı, spor yok)":         1.2,
    "Az Aktif (haftada 1-2 gün hafif egzersiz)": 1.375,
    "Orta Aktif (haftada 3-5 gün egzersiz)":     1.55,
    "Çok Aktif (haftada 6-7 gün yoğun egzersiz)": 1.725,
    "Aşırı Aktif (günlük ağır fiziksel iş)":      1.9,
}


def calc_tdee(weight_kg: float, height_cm: float, age: int,
              gender: str, activity_label: str) -> int:
    """Mifflin-St Jeor BMR × aktivite katsayısı"""
    if gender == "Erkek":
        bmr = 10 * weight_kg + 6.25 * height_cm - 5 * age + 5
    else:
        bmr = 10 * weight_kg + 6.25 * height_cm - 5 * age - 161
    mult = ACTIVITY_MULT.get(activity_label, 1.55)
    return int(bmr * mult)

# ---------------------------------------------------------------------------
# Türkçe → İngilizce gıda çeviri sözlüğü
# Kullanıcı Türkçe yazınca bu sözlükten İngilizce karşılığı bulunur,
# besin API araması her iki dille yapılır.
# ---------------------------------------------------------------------------

TR_EN_FOOD: dict[str, str] = {
    # Zeytinler & yağlar
    "zeytin": "olive", "siyah zeytin": "black olive", "yeşil zeytin": "green olive",
    "zeytinyağı": "olive oil", "tereyağı": "butter", "margarin": "margarine",
    "ayçiçek yağı": "sunflower oil",
    # Kuruyemişler
    "ceviz": "walnut", "fındık": "hazelnut", "badem": "almond", "fıstık": "peanut",
    "antep fıstığı": "pistachio", "kaju": "cashew", "çam fıstığı": "pine nut",
    "kestane": "chestnut", "susam": "sesame", "ay çekirdeği": "sunflower seed",
    "kabak çekirdeği": "pumpkin seed",
    # Meyveler
    "elma": "apple", "armut": "pear", "muz": "banana", "portakal": "orange",
    "mandalina": "mandarin", "limon": "lemon", "üzüm": "grape",
    "çilek": "strawberry", "kiraz": "cherry", "vişne": "sour cherry",
    "şeftali": "peach", "kayısı": "apricot", "erik": "plum", "karpuz": "watermelon",
    "kavun": "melon", "incir": "fig", "nar": "pomegranate", "ananas": "pineapple",
    "mango": "mango", "avokado": "avocado", "hurma": "date",
    "kuru üzüm": "raisin", "kuru kayısı": "dried apricot", "kuru incir": "dried fig",
    # Sebzeler
    "domates": "tomato", "salatalık": "cucumber", "biber": "pepper",
    "soğan": "onion", "sarımsak": "garlic", "patates": "potato",
    "patlıcan": "eggplant", "kabak": "zucchini", "havuç": "carrot",
    "ıspanak": "spinach", "marul": "lettuce", "roka": "arugula",
    "brokoli": "broccoli", "karnabahar": "cauliflower", "lahana": "cabbage",
    "kırmızı lahana": "red cabbage", "bezelye": "pea", "mısır": "corn",
    "mantar": "mushroom", "taze fasulye": "green bean", "pırasa": "leek",
    "kereviz": "celery", "turp": "radish", "bamya": "okra",
    # Baklagiller
    "mercimek": "lentil", "kırmızı mercimek": "red lentil",
    "nohut": "chickpea", "fasulye": "kidney bean", "barbunya": "borlotti bean",
    "börülce": "black eyed pea", "soya fasulyesi": "soybean",
    # Tahıllar & ekmek
    "pirinç": "rice", "bulgur": "bulgur", "makarna": "pasta", "spagetti": "spaghetti",
    "ekmek": "bread", "tam buğday ekmeği": "whole wheat bread",
    "çavdar ekmeği": "rye bread", "pide": "pita bread", "simit": "sesame bagel",
    "poğaça": "pastry", "börek": "borek", "gözleme": "gozleme",
    "yufka": "phyllo dough", "un": "flour", "irmik": "semolina",
    "yulaf": "oat", "mısır unu": "cornmeal",
    # Et & tavuk & balık
    "tavuk": "chicken", "tavuk göğsü": "chicken breast", "tavuk but": "chicken thigh",
    "et": "beef", "kıyma": "ground beef", "kuzu": "lamb", "dana": "veal",
    "sosis": "sausage", "sucuk": "sucuk sausage", "pastırma": "pastrami",
    "balık": "fish", "somon": "salmon", "ton balığı": "tuna", "hamsi": "anchovy",
    "sardalye": "sardine", "levrek": "sea bass", "çipura": "sea bream",
    "karides": "shrimp", "midye": "mussel",
    # Süt ürünleri & yumurta
    "süt": "milk", "yoğurt": "yogurt", "kefir": "kefir", "peynir": "cheese",
    "beyaz peynir": "feta cheese", "kaşar": "kashar cheese", "tulum peyniri": "tulum cheese",
    "lor": "ricotta", "ayran": "ayran yogurt drink", "krema": "cream",
    "yumurta": "egg", "haşlanmış yumurta": "boiled egg",
    # Türk yemekleri
    "mercimek çorbası": "lentil soup", "domates çorbası": "tomato soup",
    "tarhana çorbası": "tarhana soup", "ezogelin çorbası": "ezogelin soup",
    "köfte": "meatball", "izgara köfte": "grilled meatball",
    "döner": "doner kebab", "şiş kebap": "shish kebab", "adana kebap": "adana kebab",
    "urfa kebap": "urfa kebab", "lahmacun": "lahmacun",
    "menemen": "menemen egg dish", "pilav": "rice pilaf",
    "dolma": "stuffed grape leaves", "sarma": "stuffed cabbage roll",
    "zeytinyağlı fasulye": "turkish green beans olive oil",
    "imam bayıldı": "imam bayildi eggplant", "karnıyarık": "karniyarik stuffed eggplant",
    "musakka": "moussaka", "güveç": "turkish stew", "etli nohut": "chickpea stew",
    "kuru fasulye": "white bean stew", "pilaki": "bean pilaki",
    "cacık": "cacik tzatziki", "haydari": "haydari yogurt dip",
    "hummus": "hummus", "tahin": "tahini", "tahin pekmez": "tahini molasses",
    "baklava": "baklava", "kadayıf": "kadayif", "lokum": "turkish delight",
    "helva": "halva", "aşure": "ashure pudding", "sütlaç": "rice pudding",
    "muhallebi": "milk pudding", "revani": "revani semolina cake",
    # İçecekler
    "çay": "tea", "kahve": "coffee", "türk kahvesi": "turkish coffee",
    "su": "water", "meyve suyu": "fruit juice", "portakal suyu": "orange juice",
    "elma suyu": "apple juice", "soda": "sparkling water", "kola": "cola",
    # Atıştırmalıklar & diğer
    "çikolata": "chocolate", "bisküvi": "biscuit", "kraker": "cracker",
    "cips": "potato chips", "bal": "honey", "reçel": "jam", "pekmez": "molasses",
    "şeker": "sugar", "tuz": "salt",
}

def translate_food_name(turkish: str) -> str:
    """
    Türkçe gıda adını İngilizceye çevirir.
    Önce tam eşleşme, sonra kısmi eşleşme dener.
    Bulamazsa orijinal adı döner.
    """
    key = turkish.strip().lower()
    if key in TR_EN_FOOD:
        return TR_EN_FOOD[key]
    # Kısmi eşleşme: sözlükte geçen en uzun anahtar kelimeyi bul
    best = ""
    for tr_key, en_val in TR_EN_FOOD.items():
        if tr_key in key and len(tr_key) > len(best):
            best = tr_key
    return TR_EN_FOOD[best] if best else turkish


# ---------------------------------------------------------------------------
# Adet → gram dönüşüm tablosu (ortalama birim ağırlıklar)
# Kullanıcı adet girince gram otomatik hesaplanır.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Gerçekçi porsiyon/adet ağırlık tablosu
# Değer: (birim_ağırlık_g_veya_ml, birim_str, tip)
# tip: "yiyecek" | "içecek"
# ---------------------------------------------------------------------------

PORTION_TABLE: dict[str, tuple[float, str, str]] = {
    # ── Zeytinler (küçük)
    "zeytin": (3.5, "g", "yiyecek"), "siyah zeytin": (3.5, "g", "yiyecek"),
    "yeşil zeytin": (4.5, "g", "yiyecek"), "olive": (3.5, "g", "yiyecek"),
    # ── Kuruyemişler
    "ceviz": (5.0, "g", "yiyecek"), "walnut": (5.0, "g", "yiyecek"),
    "fındık": (1.5, "g", "yiyecek"), "hazelnut": (1.5, "g", "yiyecek"),
    "badem": (1.2, "g", "yiyecek"), "almond": (1.2, "g", "yiyecek"),
    "fıstık": (0.9, "g", "yiyecek"), "peanut": (0.9, "g", "yiyecek"),
    "antep fıstığı": (0.7, "g", "yiyecek"), "pistachio": (0.7, "g", "yiyecek"),
    "kaju": (1.5, "g", "yiyecek"), "cashew": (1.5, "g", "yiyecek"),
    "kestane": (8.0, "g", "yiyecek"), "chestnut": (8.0, "g", "yiyecek"),
    "ay çekirdeği": (0.3, "g", "yiyecek"), "sunflower seed": (0.3, "g", "yiyecek"),
    # ── Yumurta
    "yumurta": (60.0, "g", "yiyecek"), "egg": (60.0, "g", "yiyecek"),
    "haşlanmış yumurta": (60.0, "g", "yiyecek"), "boiled egg": (60.0, "g", "yiyecek"),
    # ── Meyveler
    "elma": (180.0, "g", "yiyecek"), "apple": (180.0, "g", "yiyecek"),
    "armut": (170.0, "g", "yiyecek"), "pear": (170.0, "g", "yiyecek"),
    "muz": (120.0, "g", "yiyecek"), "banana": (120.0, "g", "yiyecek"),
    "portakal": (200.0, "g", "yiyecek"), "orange": (200.0, "g", "yiyecek"),
    "mandalina": (80.0, "g", "yiyecek"), "mandarin": (80.0, "g", "yiyecek"),
    "şeftali": (150.0, "g", "yiyecek"), "peach": (150.0, "g", "yiyecek"),
    "kayısı": (35.0, "g", "yiyecek"), "apricot": (35.0, "g", "yiyecek"),
    "erik": (30.0, "g", "yiyecek"), "plum": (30.0, "g", "yiyecek"),
    "kiraz": (8.0, "g", "yiyecek"), "cherry": (8.0, "g", "yiyecek"),
    "vişne": (7.0, "g", "yiyecek"), "sour cherry": (7.0, "g", "yiyecek"),
    "çilek": (12.0, "g", "yiyecek"), "strawberry": (12.0, "g", "yiyecek"),
    "hurma": (8.0, "g", "yiyecek"), "date": (8.0, "g", "yiyecek"),
    "kuru kayısı": (8.0, "g", "yiyecek"), "dried apricot": (8.0, "g", "yiyecek"),
    "kuru incir": (15.0, "g", "yiyecek"), "dried fig": (15.0, "g", "yiyecek"),
    "incir": (50.0, "g", "yiyecek"), "fig": (50.0, "g", "yiyecek"),
    # ── Ekmek / unlu
    "ekmek": (30.0, "g", "yiyecek"), "bread": (30.0, "g", "yiyecek"),
    "simit": (120.0, "g", "yiyecek"), "sesame bagel": (120.0, "g", "yiyecek"),
    "pide": (250.0, "g", "yiyecek"), "pita bread": (80.0, "g", "yiyecek"),
    "poğaça": (80.0, "g", "yiyecek"), "pastry": (80.0, "g", "yiyecek"),
    "börek": (120.0, "g", "yiyecek"), "borek": (120.0, "g", "yiyecek"),
    "gözleme": (200.0, "g", "yiyecek"), "lahmacun": (150.0, "g", "yiyecek"),
    # ── Tatlılar / atıştırmalıklar
    "çikolata": (10.0, "g", "yiyecek"), "chocolate": (10.0, "g", "yiyecek"),
    "baklava": (60.0, "g", "yiyecek"), "kadayıf": (80.0, "g", "yiyecek"),
    "lokum": (10.0, "g", "yiyecek"), "turkish delight": (10.0, "g", "yiyecek"),
    "bisküvi": (7.0, "g", "yiyecek"), "biscuit": (7.0, "g", "yiyecek"),
    "kraker": (5.0, "g", "yiyecek"), "cracker": (5.0, "g", "yiyecek"),
    # ── Köfte / et ürünleri
    "köfte": (30.0, "g", "yiyecek"), "meatball": (30.0, "g", "yiyecek"),
    "izgara köfte": (35.0, "g", "yiyecek"), "grilled meatball": (35.0, "g", "yiyecek"),
    "sosis": (40.0, "g", "yiyecek"), "sausage": (40.0, "g", "yiyecek"),
    "sucuk": (15.0, "g", "yiyecek"), "sucuk sausage": (15.0, "g", "yiyecek"),
    # ── Büyük porsiyonlar
    "döner": (250.0, "g", "yiyecek"), "doner kebab": (250.0, "g", "yiyecek"),
    "tavuk döner": (250.0, "g", "yiyecek"), "chicken doner": (250.0, "g", "yiyecek"),
    "şiş kebap": (200.0, "g", "yiyecek"), "shish kebab": (200.0, "g", "yiyecek"),
    "adana kebap": (200.0, "g", "yiyecek"), "adana kebab": (200.0, "g", "yiyecek"),
    "hamburger": (200.0, "g", "yiyecek"), "pizza dilimi": (100.0, "g", "yiyecek"),
    "tavuk göğsü": (150.0, "g", "yiyecek"), "chicken breast": (150.0, "g", "yiyecek"),
    "balık filetosu": (150.0, "g", "yiyecek"), "fish fillet": (150.0, "g", "yiyecek"),
    "dolma": (20.0, "g", "yiyecek"), "stuffed grape leaves": (20.0, "g", "yiyecek"),
    # ── İçecekler (ml)
    "çay": (200.0, "ml", "içecek"), "tea": (200.0, "ml", "içecek"),
    "türk kahvesi": (60.0, "ml", "içecek"), "turkish coffee": (60.0, "ml", "içecek"),
    "kahve": (150.0, "ml", "içecek"), "coffee": (150.0, "ml", "içecek"),
    "americano": (240.0, "ml", "içecek"), "latte": (300.0, "ml", "içecek"),
    "su": (200.0, "ml", "içecek"), "water": (200.0, "ml", "içecek"),
    "şişe su": (500.0, "ml", "içecek"), "bottle water": (500.0, "ml", "içecek"),
    "kola": (330.0, "ml", "içecek"), "cola": (330.0, "ml", "içecek"),
    "kutu kola": (330.0, "ml", "içecek"), "can cola": (330.0, "ml", "içecek"),
    "şişe kola": (500.0, "ml", "içecek"), "bottle cola": (500.0, "ml", "içecek"),
    "meyve suyu": (200.0, "ml", "içecek"), "fruit juice": (200.0, "ml", "içecek"),
    "portakal suyu": (200.0, "ml", "içecek"), "orange juice": (200.0, "ml", "içecek"),
    "ayran": (200.0, "ml", "içecek"), "ayran yogurt drink": (200.0, "ml", "içecek"),
    "süt": (200.0, "ml", "içecek"), "milk": (200.0, "ml", "içecek"),
    "kefir": (200.0, "ml", "içecek"), "kefir": (200.0, "ml", "içecek"),
    "soda": (200.0, "ml", "içecek"), "sparkling water": (200.0, "ml", "içecek"),
    "enerji içeceği": (250.0, "ml", "içecek"), "energy drink": (250.0, "ml", "içecek"),
    "bira": (330.0, "ml", "içecek"), "beer": (330.0, "ml", "içecek"),
    "şarap": (150.0, "ml", "içecek"), "wine": (150.0, "ml", "içecek"),
    "çorba": (250.0, "ml", "içecek"), "soup": (250.0, "ml", "içecek"),
    "mercimek çorbası": (250.0, "ml", "içecek"), "lentil soup": (250.0, "ml", "içecek"),
}

# Eski adla uyumluluk için
GRAM_PER_PIECE = {k: v[0] for k, v in PORTION_TABLE.items()}


def get_portion_info(food_key: str) -> tuple[float | None, str, str]:
    """
    (birim_ağırlık, birim_str, tip) döner.
    birim_str: "g" veya "ml"
    tip: "yiyecek" veya "içecek"
    Bulunamazsa (None, "g", "yiyecek") döner.
    """
    key = food_key.strip().lower()
    if key in PORTION_TABLE:
        return PORTION_TABLE[key]
    # Kısmi eşleşme
    best_key, best_len = "", 0
    for k in PORTION_TABLE:
        if k in key and len(k) > best_len:
            best_key, best_len = k, len(k)
    if best_key:
        return PORTION_TABLE[best_key]
    # İçecek kelime tahmini
    drink_words = ["suyu","çay","kahve","su","kola","bira","şarap","ayran","süt","kefir","soda","çorba","juice","tea","coffee","water","milk","beer","wine","soup"]
    for w in drink_words:
        if w in key:
            return (200.0, "ml", "içecek")
    return (None, "g", "yiyecek")


def get_default_gram_per_piece(food_key: str) -> float | None:
    val, _, _ = get_portion_info(food_key)
    return val


def grams_from_pieces(food_key: str, pieces: float) -> float | None:
    val, _, _ = get_portion_info(food_key)
    return round(pieces * val, 1) if val else None


def infer_food_type(food_key: str) -> str:
    """'yiyecek' veya 'içecek' döner."""
    _, _, tip = get_portion_info(food_key)
    return tip


def infer_unit(food_key: str) -> str:
    """'g' veya 'ml' döner."""
    _, unit, _ = get_portion_info(food_key)
    return unit


# ---------------------------------------------------------------------------
# Ortak session state başlatıcı — tüm sayfalar çağırır
# ---------------------------------------------------------------------------

def init_session_state():
    """Her sayfa başında çağrılır; eksik key'leri oluşturur."""
    from utils import DAYS, MEALS, ACTIVITY_MULT
    defaults = {
        # Haftalık log
        "weekly_log":  {day: {meal: [] for meal in MEALS} for day in DAYS},
        # Günlük log (weekly_log ile aynı veriyi paylaşır — sadece 1 gün görünümü)
        # Tek öğün log
        "single_meal": [],
        # Vücut metrikleri
        "body_metrics": {
            "height": 170, "weight": 70, "age": 30,
            "gender": "Erkek",
            "activity": list(ACTIVITY_MULT.keys())[2],
        },
        # Anlık analiz sonuçları
        "food_info":       None,
        "nutrition_100g":  None,
        "last_image_b64":  None,
    }
    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val