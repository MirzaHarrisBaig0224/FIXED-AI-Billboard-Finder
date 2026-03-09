from flask import Flask, render_template, request, jsonify
import mysql.connector
import pandas as pd
from groq import Groq
import json
import re
import os

app = Flask(__name__)

# -----------------------------
# GROQ CLIENT
# -----------------------------
groq_client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

# -----------------------------
# DATABASE
# -----------------------------
def connect_db():
    return mysql.connector.connect(
        host="localhost",
        user="root",
        password="",
        database="aimnodet_selmore_db"
    )

def load_billboards():
    db = connect_db()

    query = """
    SELECT
        id,
        name,
        location,
        city,
        price,
        views,
        width,
        height,
        lighting,
        image_path,
        type
    FROM billboards
    WHERE status = 'approved'
    """

    df = pd.read_sql(query, db)

    numeric_cols = ["price","views","width","height"]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.fillna("")

    return df

# -----------------------------
# LLM INTENT EXTRACTION
# -----------------------------
def extract_campaign_intent(user_prompt, available_cities):

    city_list = ", ".join(sorted(set(available_cities)))

    llm_prompt = f"""
Extract billboard campaign intent.

Available cities:
{city_list}

Return ONLY JSON.

Format:
{{
"city":"",
"budget_preference":"neutral",
"visibility_priority":"medium",
"size_priority":"medium",
"lighting_required":false,
"premium_preference":false,
"type_preference":"",
"location_keywords":[],
"notes":""
}}

User prompt:
{user_prompt}
"""

    try:

        response = groq_client.chat.completions.create(
            model="llama3-70b-8192",
            messages=[{"role":"user","content":llm_prompt}],
            temperature=0
        )

        raw = response.choices[0].message.content.strip()

        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            raw = match.group(0)

        data = json.loads(raw)

        return {
            "city": str(data.get("city","")),
            "budget_preference": str(data.get("budget_preference","neutral")),
            "visibility_priority": str(data.get("visibility_priority","medium")),
            "size_priority": str(data.get("size_priority","medium")),
            "lighting_required": bool(data.get("lighting_required",False)),
            "premium_preference": bool(data.get("premium_preference",False)),
            "type_preference": str(data.get("type_preference","")),
            "location_keywords": data.get("location_keywords",[]),
            "notes": str(data.get("notes",""))
        }

    except Exception as e:

        # fallback heuristic
        p = user_prompt.lower()

        city=""
        for c in available_cities:
            if c.lower() in p:
                city=c
                break

        return {
            "city": city,
            "budget_preference":"neutral",
            "visibility_priority":"medium",
            "size_priority":"medium",
            "lighting_required":False,
            "premium_preference":False,
            "type_preference":"",
            "location_keywords":[],
            "notes":"fallback heuristic"
        }

# -----------------------------
# SCORING
# -----------------------------
def safe_normalize(series):
    max_val = series.max()
    if max_val == 0 or pd.isna(max_val):
        return pd.Series([0]*len(series), index=series.index)
    return series.fillna(0) / max_val

def score_billboards(df, intent):

    working = df.copy()

    if intent["city"]:
        filtered = working[working["city"].str.lower()==intent["city"].lower()]
        if not filtered.empty:
            working = filtered

    working["area"] = working["width"].fillna(0) * working["height"].fillna(0)

    working["size_score"] = safe_normalize(working["area"])
    working["visibility_score"] = safe_normalize(working["views"])

    max_price = working["price"].max()

    working["cheap_score"] = 1 - (working["price"] / max_price)
    working["premium_price_score"] = working["price"] / max_price

    working["lighting_score"] = working["lighting"].str.lower().apply(
        lambda x:1 if "light" in x else 0
    )

    working["score"] = (
        working["visibility_score"] * 0.45 +
        working["size_score"] * 0.25 +
        working["cheap_score"] * 0.20 +
        working["lighting_score"] * 0.10
    )

    return working.sort_values("score",ascending=False)

# -----------------------------
# ROUTES
# -----------------------------
@app.route("/")
def home():
    return render_template("index.html")

@app.route("/recommend", methods=["POST"])
def recommend():

    data = request.get_json()
    prompt = data.get("prompt","")

    df = load_billboards()

    available_cities = sorted(df["city"].unique())

    intent = extract_campaign_intent(prompt, available_cities)

    ranked = score_billboards(df, intent)

    top = ranked.head(6)

    results = []

    for _,row in top.iterrows():

        results.append({
            "id": int(row["id"]),
            "name": row["name"],
            "location": row["location"],
            "city": row["city"],
            "price": float(row["price"]),
            "views": float(row["views"]),
            "width": float(row["width"]),
            "height": float(row["height"]),
            "lighting": row["lighting"],
            "type": row["type"],
            "image_path": row["image_path"],
            "score": round(float(row["score"]),4)
        })

    return jsonify({
        "success":True,
        "intent":intent,
        "count":len(results),
        "billboards":results
    })

# -----------------------------
# SERVER
# -----------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT",8080))
    app.run(host="0.0.0.0", port=port)
