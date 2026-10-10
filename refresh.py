"""Re-pull all sources and rebuild the analysis DB.  python refresh.py [--only google_play,app_store]"""
import argparse
from mms import collect, analyze

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="", help="comma list: google_play,app_store,facebook,instagram,tiktok,x,linkedin")
    ap.add_argument("--analyze-only", action="store_true", help="skip pulling; just re-run analysis on cached raw data")
    a = ap.parse_args()
    if not a.analyze_only:
        collect.main([s for s in a.only.split(",") if s] or None)
    analyze.main()
