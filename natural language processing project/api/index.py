"""
Vercel serverless entry point.

Vercel looks for a WSGI-compatible `app` object in this file.
We import the Flask `app` from the project root's app.py by
adding the parent directory to sys.path first.
"""
import sys
import os

# Make the project root importable from inside the api/ folder
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app  # noqa: F401  – Vercel uses this `app` as the WSGI handler
