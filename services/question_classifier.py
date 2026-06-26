"""Question classification shared across Hoppr + MCP Beta pages.

One taxonomy, two consumers. Update keywords here and both charts move.

Buckets are the 4 meta-categories the team tracks (Revenue / Ads / SKU /
Downloads) plus supporting absorbers (Performance / Channels / Customers
/ Affiliates / Competitors / Data Scope / Data Accuracy).

`classify_question(q)` returns a list of bucket names a question matches.
`is_accuracy(q)` is a fast-path check used to flag accuracy issues
separately on the Hoppr page.
"""

ACCURACY_KEYWORDS = [
    "wrong", "incorrect", "inaccurate", "not matching", "doesn't match",
    "mismatch", "missing data", "no data", "data not", "data accuracy",
    "data quality", "data issue", "different from", "discrepancy",
    "not available", "not showing", "showing wrong", "can't find",
    "cannot find", "not found",
]

QUESTION_BUCKETS = {
    # ── 4 meta-categories the team tracks ─────────────────────────────────────
    "Revenue & GMV/NMV": [
        "gmv", "nmv", "revenue", "sales", "orders", "gross merchandise",
        "net merchandise", "nett merchandise", "gross revenue", "net revenue",
        "gross sales", "net sales", "aov", "average order value", "conversion",
        "checkout", "purchase", "transaction", "top line", "topline",
        "income", "earning", "profit", "margin", "growth", "selling",
        "total sales", "total revenue", "monthly sales", "daily sales",
        "weekly sales", "sale performance", "sales performance",
        "cancellation", "cancellations", "cancelled", "canceled",
        "refund", "refunds", "refunded", "return rate", "returned order",
    ],
    "Ads, Traffic & ROAS": [
        "roas", "return on ad", "campaign", "paid", "advertisement",
        " ad ", " ads ", "cpc", "cpa", "ctr", "click-through",
        "traffic", "visitor", "visit", "session", "pageview", "page view",
        "impression", "reach", "ad spend", "budget", "marketing spend",
        "facebook ads", "google ads", "tiktok ads", "meta ads", "shopee ads",
        "lazada ads", "sponsored", "search ads", "display ads",
    ],
    "SKU & Products": [
        "sku", "product", "listing", "catalogue", "catalog", "item",
        "variant", "inventory", "stock", "category", "brand",
        "bestseller", "best seller", "best selling", "top product",
        "top selling", "top sku", "hero product", "slow moving",
        "new product", "out of stock",
        "units", "units sold", "quantity sold", "qty sold", "sold",
        "pieces sold", "pcs sold",
    ],
    "Downloads & Exports": [
        "download", "export", "excel", "csv", "spreadsheet", "sheet",
        "file", "data export", "extract", "pull data", "get data",
        "raw data", "data download", "generate report", "download report",
        "export data", "download data",
    ],
    # ── Supporting buckets to absorb common "General" content ──────────────────
    "Performance & Trends": [
        "trend", "trending", "drop", "decline", "fell", "decreased", "decreasing",
        "increase", "increased", "increasing", "grow", "growing", "growth",
        "yesterday", "last week", "this week", "last month", "this month", "today",
        "last 7 days", "last 30 days", "past week", "past month",
        "week on week", "week-on-week", "wow", "month on month", "month-on-month",
        "mom", "yoy", "year on year", "year-on-year", "last year",
        "how is", "how was", "how are", "how's", "how am i",
        "why did", "why is", "why are", "what happened", "what's happening",
        "performance", "performing", "recent", "lately", "over time", "historical",
    ],
    "Channels & Marketplaces": [
        "shopee", "lazada", "tiktok shop", "tiktok", "tokopedia", "amazon",
        "qoo10", "blibli", "bukalapak", "shopify", "woocommerce", "magento",
        "marketplace", "marketplaces", "channel", "channels", "platform",
    ],
    "Customers & Buyers": [
        "customer", "customers", "buyer", "buyers", "shopper", "shoppers",
        "audience", "consumer", "consumers", "repeat", "returning", "loyalty",
        "retention", "new customer", "user base", "demographics", "demographic",
        "age group", "gender split",
    ],
    "Affiliates & Creators": [
        "affiliate", "affiliates", "kol", "kols", "creator", "creators",
        "influencer", "influencers", "commission", "ambassador", "ambassadors",
        "livestream", "live stream", "live-stream", "live streaming",
        "livestreaming", "ugc",
    ],
    "Competitors": [
        "competitor", "competitors", "competition", "compete", "competing",
        "market share", "peer", "peers", "rival", "rivals",
        "against other", "other brand", "other brands", "vs other",
        "benchmark", "benchmarks", "industry average", "industry avg",
        "category leader", "category benchmark",
    ],
    "Data Scope / Features": [
        "what period", "what time period", "which period",
        "what date range", "what time range", "which date range",
        "what month", "which month", "what year", "which year",
        "data start", "data starts", "starts from", "start from",
        "data range", "date range", "time range",
        "how recent", "how current", "how old", "how fresh",
        "up to date", "up-to-date", "last updated", "freshness",
        "give me insights", "give insights", "any insights",
        "create chart", "make chart", "show me chart", "show me a chart",
        "build chart", "draw chart", "plot chart",
        "about the data", "about this data", "what data",
        "which data", "data you have", "data you analyze",
        "data available", "what's available",
    ],
    # ── Additional signal ──────────────────────────────────────────────────────
    "Data Accuracy":    ACCURACY_KEYWORDS,
}


def classify_question(q: str) -> list:
    ql = (q or "").lower()
    tags = [b for b, kws in QUESTION_BUCKETS.items() if any(kw in ql for kw in kws)]
    return tags if tags else ["General"]


def is_accuracy(q: str) -> bool:
    return any(kw in (q or "").lower() for kw in ACCURACY_KEYWORDS)
