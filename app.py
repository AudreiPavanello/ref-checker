import re
import time
import xml.etree.ElementTree as ET

import pandas as pd
import requests
import streamlit as st
from rapidfuzz import fuzz

# Constants

YEAR_RE = re.compile(r"\b(19[5-9]\d|20[0-2]\d)\b")
APA_RE = re.compile(r"\(\d{4}\)\.\s+(.+?)\.", re.UNICODE)
ABNT_RE = re.compile(r"(?:[A-ZÁÉÍÓÚÃÕÂÊÔ][^.]+\.)\s+([A-Z][^.]{10,}?)\.", re.UNICODE)
VANCOUVER_RE = re.compile(
    r"^(?:[A-Z][a-z]+\s+[A-Z]{1,2}(?:,\s*)?)+[,.]\s+(.+?)\.", re.UNICODE
)

REQUEST_TIMEOUT = 10
CONFIRMED_THRESHOLD = 0.85
SUSPICIOUS_THRESHOLD = 0.60
CROSSREF_UA = "ref-checker/1.0 (mailto:research@example.com)"
PUBMED_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"


# Parsing


def extract_title_and_year(reference: str) -> tuple[str | None, str | None]:
    year_match = YEAR_RE.search(reference)
    year = year_match.group(0) if year_match else None

    for pattern in (APA_RE, VANCOUVER_RE, ABNT_RE):
        m = pattern.search(reference)
        if m:
            candidate = m.group(1).strip().rstrip(".")
            if len(candidate) >= 10:
                return candidate, year

    return None, year


# Scoring and classification


def score_match(a: str, b: str) -> float:
    return fuzz.token_sort_ratio(a.lower(), b.lower()) / 100.0


def classify_result(score: float) -> str:
    if score > CONFIRMED_THRESHOLD:
        return "Confirmed"
    if score >= SUSPICIOUS_THRESHOLD:
        return "Suspicious"
    return "Not Found"


# API callers


def search_crossref(title: str, full_ref: str = "") -> dict | None:
    time.sleep(0.5)
    try:
        # query.bibliographic matches against full reference strings; more
        # accurate than query.title for short or common titles
        query = full_ref if full_ref else title
        resp = requests.get(
            "https://api.crossref.org/works",
            params={"query.bibliographic": query, "rows": 1},
            headers={"User-Agent": CROSSREF_UA},
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        item = resp.json()["message"]["items"][0]
        return {
            "found_title": item["title"][0],
            "doi": item.get("DOI", "N/A"),
        }
    except (
        requests.Timeout,
        requests.ConnectionError,
        requests.HTTPError,
        KeyError,
        IndexError,
        ValueError,
    ):
        return None


def search_pubmed(title: str) -> dict | None:
    time.sleep(0.5)
    try:
        search_resp = requests.get(
            f"{PUBMED_BASE}/esearch.fcgi",
            params={
                "db": "pubmed",
                "term": f"{title}[Title]",
                "retmax": 1,
                "retmode": "json",
            },
            timeout=REQUEST_TIMEOUT,
        )
        search_resp.raise_for_status()
        ids = search_resp.json()["esearchresult"]["idlist"]
        if not ids:
            return None
    except (
        requests.Timeout,
        requests.ConnectionError,
        requests.HTTPError,
        KeyError,
        ValueError,
    ):
        return None

    time.sleep(0.5)
    try:
        fetch_resp = requests.get(
            f"{PUBMED_BASE}/efetch.fcgi",
            params={
                "db": "pubmed",
                "id": ids[0],
                "rettype": "abstract",
                "retmode": "xml",
            },
            timeout=REQUEST_TIMEOUT,
        )
        fetch_resp.raise_for_status()
        root = ET.fromstring(fetch_resp.content)
        found_title = root.findtext(".//ArticleTitle") or ""
        doi_el = root.find(".//ELocationID[@EIdType='doi']")
        doi = doi_el.text if doi_el is not None else "N/A"
        return {"found_title": found_title, "doi": doi}
    except (
        requests.Timeout,
        requests.ConnectionError,
        requests.HTTPError,
        ET.ParseError,
        KeyError,
        IndexError,
    ):
        return None


def search_scielo(title: str) -> dict | None:
    time.sleep(0.5)
    try:
        resp = requests.get(
            "https://articlemeta.scielo.org/api/v1/article/",
            params={"format": "json", "titles": title},
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        # Response is a list of articles; each has nested title structures
        first = data[0] if isinstance(data, list) else next(iter(data.values()))
        titles = first.get("article", {}).get("v12", [])
        found_title = titles[0].get("_", "") if titles else ""
        if not found_title:
            return None
        return {"found_title": found_title, "doi": "N/A"}
    except (
        requests.Timeout,
        requests.ConnectionError,
        requests.HTTPError,
        KeyError,
        IndexError,
        TypeError,
        ValueError,
        StopIteration,
    ):
        return None


# Orchestrator


def check_reference(reference: str) -> dict:
    title, year = extract_title_and_year(reference)
    base = {
        "reference": reference,
        "year": year or "N/A",
        "doi": "N/A",
        "source": "N/A",
    }

    if not title:
        return {**base, "status": "Not Found", "score": 0.0}

    best: dict = {"score": 0.0, "source": "N/A", "doi": "N/A"}

    for source_name, search_fn in [
        ("CrossRef", lambda t: search_crossref(t, reference)),
        ("PubMed", search_pubmed),
        ("SciELO", search_scielo),
    ]:
        result = search_fn(title)
        if result is None:
            continue
        score = score_match(title, result["found_title"])
        if score > best["score"]:
            best = {
                "score": score,
                "source": source_name,
                "doi": result.get("doi") or "N/A",
            }
        if score > CONFIRMED_THRESHOLD:
            break

    return {
        **base,
        "status": classify_result(best["score"]),
        "score": round(best["score"], 4),
        "source": best["source"],
        "doi": best["doi"],
    }


# DataFrame helpers


def build_results_dataframe(results: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(results)
    df["Reference"] = df["reference"].apply(
        lambda s: s[:80] + "…" if len(s) > 80 else s
    )
    df["DOI"] = df["doi"].apply(
        lambda d: f"https://doi.org/{d}"
        if d and d != "N/A" and not d.startswith("http")
        else (d if d != "N/A" else "")
    )
    df = df.rename(
        columns={
            "year": "Year",
            "status": "Status",
            "source": "Source",
            "score": "Score",
        }
    )
    return df[["Reference", "Year", "Status", "Source", "DOI", "Score"]]


def to_csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8")


# Streamlit UI


def main() -> None:
    st.set_page_config(page_title="Reference Checker", layout="wide")
    st.title("Reference Checker")
    st.caption(
        "Validates bibliographic references (ABNT, APA, Vancouver) against "
        "CrossRef, PubMed, and SciELO."
    )

    uploaded_file = st.file_uploader(
        "Upload a .txt file with one reference per line", type=["txt"]
    )

    if uploaded_file is None:
        st.info("Upload a .txt file to begin.")
        return

    raw_text = uploaded_file.read().decode("utf-8", errors="replace")
    references = [line.strip() for line in raw_text.splitlines() if line.strip()]

    if not references:
        st.warning("The file appears to be empty or contains no readable lines.")
        return

    st.write(f"Found **{len(references)}** reference(s). Click **Run Validation** to start.")

    if not st.button("Run Validation", type="primary"):
        return

    results: list[dict] = []
    progress_bar = st.progress(0)
    status_text = st.empty()
    total = len(references)

    for i, ref in enumerate(references):
        status_text.text(f"Checking reference {i + 1} of {total}...")
        results.append(check_reference(ref))
        progress_bar.progress((i + 1) / total)

    status_text.text("Validation complete.")

    df = build_results_dataframe(results)

    col1, col2, col3 = st.columns(3)
    col1.metric("Confirmed", int((df["Status"] == "Confirmed").sum()))
    col2.metric("Suspicious", int((df["Status"] == "Suspicious").sum()))
    col3.metric("Not Found", int((df["Status"] == "Not Found").sum()))

    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Score": st.column_config.ProgressColumn(
                "Score", min_value=0.0, max_value=1.0, format="%.2f"
            ),
            "DOI": st.column_config.LinkColumn("DOI"),
        },
    )

    st.download_button(
        label="Download results as CSV",
        data=to_csv_bytes(df),
        file_name="ref_checker_results.csv",
        mime="text/csv",
    )


if __name__ == "__main__":
    main()
