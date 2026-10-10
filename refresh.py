"""Re-pull sources, rebuild the analysis DB, then extract product insights (incremental).
python refresh.py [--only google_play,app_store] [--analyze-only]"""
import argparse
from mms import collect, analyze, insights

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="", help="comma list: google_play,app_store,facebook,instagram,tiktok,x,linkedin")
    ap.add_argument("--analyze-only", action="store_true", help="skip pulling; re-run analysis + insights on cached data")
    a = ap.parse_args()
    if not a.analyze_only:
        collect.main([s for s in a.only.split(",") if s] or None)
    analyze.main()
    insights.run()   # rules/embeddings cached per item id + text hash -> only new items are processed
