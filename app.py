"""Local entry point kept for backwards compatibility: `streamlit run app.py`.
The real app lives in streamlit_app.py (the Streamlit Community Cloud entry file)."""
import runpy
from pathlib import Path

runpy.run_path(str(Path(__file__).with_name("streamlit_app.py")), run_name="__main__")
