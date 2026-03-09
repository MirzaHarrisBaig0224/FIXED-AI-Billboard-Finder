from flask import Flask, render_template, request, jsonify
import mysql.connector
import pandas as pd
import ollama
import json
import re

app = Flask(__name__)


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

    numeric_cols = ["price", "views", "width", "height"]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df["lighting"] = df["lighting"].fillna("").astype(str)
    df["city"] = df["city"].fillna("").astype(str)
    df["location"] = df["location"].fillna("").astype(str)
    df["name"] = df["name"].fillna("").astype(str)
    df["type"] = df["type"].fillna("").astype(str)
    df["image_path"] = df["image_path"].fillna("").astype(str)

    return df


# -----------------------------
# LLM INTENT EXTRACTION
# -----------------------------
def extract_campaign_intent(user_prompt: str, available_cities: list[str]):
    city_list = ", ".join(sorted(set([c for c in available_cities if c])))

    llm_prompt = f"""
You are extracting billboard campaign intent for a database search.

Available cities in the database:
{city_list}

Return ONLY valid JSON.
Do not include markdown.
Do not explain anything.

JSON format:
{{
  "city": "",
  "budget_preference": "neutral",
  "visibility_priority": "medium",
  "size_priority": "medium",
  "lighting_required": false,
  "premium_preference": false,
  "type_preference": "",
  "location_keywords": [],
  "notes": ""
}}

Rules:
- city must be one of the available cities if clearly mentioned, otherwise "".
- budget_preference must be one of: "low", "medium", "high", "neutral".
- visibility_priority must be one of: "low", "medium", "high".
- size_priority must be one of: "low", "medium", "high".
- lighting_required must be true only if clearly requested.
- premium_preference should be true for words like luxury, premium, upscale.
- type_preference should be a short value only if clearly mentioned.
- location_keywords should contain short area/intent words from the prompt.
- notes should be short.

User prompt:
{user_prompt}
"""

    default = {
        "city": "",
        "budget_preference": "neutral",
        "visibility_priority": "medium",
        "size_priority": "medium",
        "lighting_required": False,
        "premium_preference": False,
        "type_preference": "",
        "location_keywords": [],
        "notes": ""
    }

    try:
        response = ollama.chat(
            model="llama3.2:1b",
            messages=[{"role": "user", "content": llm_prompt}]
        )

        raw = response["message"]["content"].strip()

        # Extract JSON safely if model adds extra text
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            raw = match.group(0)

        data = json.loads(raw)

        result = {
            "city": str(data.get("city", "")).strip(),
            "budget_preference": str(data.get("budget_preference", "neutral")).strip().lower(),
            "visibility_priority": str(data.get("visibility_priority", "medium")).strip().lower(),
            "size_priority": str(data.get("size_priority", "medium")).strip().lower(),
            "lighting_required": bool(data.get("lighting_required", False)),
            "premium_preference": bool(data.get("premium_preference", False)),
            "type_preference": str(data.get("type_preference", "")).strip(),
            "location_keywords": data.get("location_keywords", []) if isinstance(data.get("location_keywords", []), list) else [],
            "notes": str(data.get("notes", "")).strip()
        }

        if result["city"] not in available_cities:
            result["city"] = ""

        allowed_budget = {"low", "medium", "high", "neutral"}
        allowed_level = {"low", "medium", "high"}

        if result["budget_preference"] not in allowed_budget:
            result["budget_preference"] = "neutral"

        if result["visibility_priority"] not in allowed_level:
            result["visibility_priority"] = "medium"

        if result["size_priority"] not in allowed_level:
            result["size_priority"] = "medium"

        return result

    except Exception:
        # Fallback heuristic if LLM output fails
        p = user_prompt.lower()

        city = ""
        for c in available_cities:
            if c and c.lower() in p:
                city = c
                break

        budget_pref = "neutral"
        if any(x in p for x in ["cheap", "affordable", "budget", "low cost", "economical"]):
            budget_pref = "low"
        elif any(x in p for x in ["premium budget", "high budget", "large budget", "luxury spend"]):
            budget_pref = "high"

        visibility = "high" if any(x in p for x in ["high traffic", "maximum visibility", "heavy traffic", "busy road", "commuter"]) else "medium"
        size = "high" if any(x in p for x in ["large", "big billboard", "maximum size"]) else "medium"
        lighting_required = any(x in p for x in ["lighted", "lit", "night visibility", "night campaign"])
        premium = any(x in p for x in ["luxury", "premium", "upscale", "elite"])

        return {
            "city": city,
            "budget_preference": budget_pref,
            "visibility_priority": visibility,
            "size_priority": size,
            "lighting_required": lighting_required,
            "premium_preference": premium,
            "type_preference": "",
            "location_keywords": [],
            "notes": "Fallback heuristic used"
        }


# -----------------------------
# RANKING
# -----------------------------
def safe_normalize(series):
    max_val = series.max()
    if pd.isna(max_val) or max_val == 0:
        return pd.Series([0] * len(series), index=series.index)
    return series.fillna(0) / max_val


def score_billboards(df: pd.DataFrame, intent: dict):
    working = df.copy()

    if intent["city"]:
        city_match = working["city"].str.lower() == intent["city"].lower()
        filtered = working[city_match].copy()
        if not filtered.empty:
            working = filtered

    # Base scores
    working["area"] = working["width"].fillna(0) * working["height"].fillna(0)
    working["size_score"] = safe_normalize(working["area"])
    working["visibility_score"] = safe_normalize(working["views"])

    max_price = working["price"].max()
    if pd.isna(max_price) or max_price == 0:
        working["cheap_score"] = 0
        working["premium_price_score"] = 0
    else:
        working["cheap_score"] = 1 - (working["price"].fillna(max_price) / max_price)
        working["premium_price_score"] = working["price"].fillna(0) / max_price

    working["lighting_score"] = working["lighting"].str.lower().apply(
        lambda x: 1 if any(k in x for k in ["light", "lit", "illuminated"]) else 0
    )

    working["location_match_score"] = 0
    keywords = [str(k).strip().lower() for k in intent.get("location_keywords", []) if str(k).strip()]
    if keywords:
        combined = (
            working["name"].fillna("") + " " +
            working["location"].fillna("") + " " +
            working["city"].fillna("") + " " +
            working["type"].fillna("")
        ).str.lower()

        def keyword_score(text):
            matches = sum(1 for k in keywords if k in text)
            return matches

        working["location_match_score"] = combined.apply(keyword_score)
        working["location_match_score"] = safe_normalize(working["location_match_score"])

    # Dynamic weights
    weights = {
        "visibility": 0.40,
        "size": 0.25,
        "budget": 0.20,
        "lighting": 0.10,
        "location": 0.05
    }

    if intent["visibility_priority"] == "high":
        weights["visibility"] = 0.55
        weights["size"] = 0.20
        weights["budget"] = 0.10
        weights["lighting"] = 0.10
        weights["location"] = 0.05

    if intent["size_priority"] == "high":
        weights["size"] += 0.15
        weights["visibility"] -= 0.05
        weights["budget"] -= 0.05

    if intent["budget_preference"] == "low":
        budget_component = working["cheap_score"]
        weights["budget"] = 0.35
        weights["visibility"] -= 0.10
        weights["size"] -= 0.05
    elif intent["budget_preference"] == "high" or intent["premium_preference"]:
        budget_component = working["premium_price_score"]
        weights["budget"] = 0.25
    else:
        budget_component = 1 - abs(working["price"].fillna(0) - working["price"].median()) / (working["price"].max() if working["price"].max() not in [0, None] else 1)
        budget_component = budget_component.fillna(0).clip(lower=0)

    if intent["lighting_required"]:
        weights["lighting"] = 0.20
        weights["visibility"] -= 0.05
        weights["budget"] -= 0.05

    # Keep weights sane
    for k in weights:
        if weights[k] < 0:
            weights[k] = 0

    total = sum(weights.values())
    if total == 0:
        total = 1

    for k in weights:
        weights[k] = weights[k] / total

    working["score"] = (
        working["visibility_score"] * weights["visibility"] +
        working["size_score"] * weights["size"] +
        budget_component * weights["budget"] +
        working["lighting_score"] * weights["lighting"] +
        working["location_match_score"] * weights["location"]
    )

    working = working.sort_values("score", ascending=False)

    return working


# -----------------------------
# ROUTES
# -----------------------------
@app.route("/")
def home():
    return render_template("index.html")


@app.route("/recommend", methods=["POST"])
def recommend():
    data = request.get_json(force=True)
    user_prompt = str(data.get("prompt", "")).strip()

    if not user_prompt:
        return jsonify({"success": False, "message": "Prompt is required."}), 400

    df = load_billboards()

    if df.empty:
        return jsonify({"success": False, "message": "No approved billboards found in database."}), 404

    available_cities = sorted(df["city"].dropna().astype(str).unique().tolist())
    intent = extract_campaign_intent(user_prompt, available_cities)
    ranked = score_billboards(df, intent)

    top = ranked.head(6).copy()

    # Nice tags for cards
    top["tag"] = ""
    if not top.empty:
        idx_vis = top["visibility_score"].idxmax() if "visibility_score" in top.columns else None
        idx_size = top["size_score"].idxmax() if "size_score" in top.columns else None
        idx_budget = top["cheap_score"].idxmax() if "cheap_score" in top.columns else None

        if idx_vis in top.index:
            top.loc[idx_vis, "tag"] = "Best Visibility"
        if idx_size in top.index and top.loc[idx_size, "tag"] == "":
            top.loc[idx_size, "tag"] = "Largest Format"
        if idx_budget in top.index and top.loc[idx_budget, "tag"] == "":
            top.loc[idx_budget, "tag"] = "Best Value"

    results = []
    for _, row in top.iterrows():
        results.append({
            "id": int(row["id"]) if pd.notna(row["id"]) else None,
            "name": row["name"],
            "location": row["location"],
            "city": row["city"],
            "price": float(row["price"]) if pd.notna(row["price"]) else 0,
            "views": float(row["views"]) if pd.notna(row["views"]) else 0,
            "width": float(row["width"]) if pd.notna(row["width"]) else 0,
            "height": float(row["height"]) if pd.notna(row["height"]) else 0,
            "lighting": row["lighting"],
            "type": row["type"],
            "image_path": row["image_path"],
            "score": round(float(row["score"]), 4),
            "tag": row["tag"]
        })

    return jsonify({
        "success": True,
        "intent": intent,
        "count": len(results),
        "billboards": results
    })


import os

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
