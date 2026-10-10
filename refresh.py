"""Incremental refresh: pull only items newer than data/masmovil.db, analyse only those, then update the
product insights (rules/embeddings cached per item id + text hash -> only new items are processed).
python refresh.py [--only google_play,app_store] [--full] [--analyze-only]"""
import argparse
from mms import collect, analyze, insights

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="", help="comma list: google_play,app_store,facebook,instagram,tiktok,x,linkedin")
    ap.add_argument("--full", action="store_true",
                    help="ignore date watermarks and re-pull the full LOOKBACK_DAYS window (costs more Apify credit); "
                         "already-stored items are still skipped")
    ap.add_argument("--analyze-only", action="store_true", help="skip pulling; append any new raw items + rebuild insights")
    a = ap.parse_args()
    if not a.analyze_only:
        collect.main([s for s in a.only.split(",") if s] or None, full=a.full)
    analyze.main()
    insights.run()
