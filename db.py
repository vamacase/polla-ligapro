"""Conexión compartida a Supabase para la webapp (Streamlit) y el sync local."""
import os
from pathlib import Path
from supabase import create_client, Client

RAIZ = Path(__file__).resolve().parent


def get_client() -> Client:
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if not url or not key:
        try:
            import streamlit as st
            url = url or st.secrets["SUPABASE_URL"]
            key = key or st.secrets["SUPABASE_KEY"]
        except Exception:
            pass
    if not url or not key:
        raise RuntimeError(
            "Faltan SUPABASE_URL / SUPABASE_KEY (variables de entorno, .env o .streamlit/secrets.toml)."
        )
    return create_client(url, key)
