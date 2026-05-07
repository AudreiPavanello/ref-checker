# ref-checker

Validates bibliographic references (ABNT, APA, Vancouver) with `.txt` files against CrossRef, PubMed, and SciELO.

---

## Features

- Upload a `.txt` file with one reference per line
- Automatic title and year extraction for ABNT, APA, and Vancouver formats
- Sequential search across CrossRef → PubMed → SciELO (stops on first confirmed match)
- String similarity scoring via `rapidfuzz` (token sort ratio)
- Classification of results: Confirmed / Suspicious / Not Found
- Interactive results table with clickable DOI links and visual score bars
- One-click CSV export

---

## Usage

1. Prepare a plain-text file with one bibliographic reference per line.
2. Open the app and upload the file using the file uploader.
3. Click **Run Validation**.
4. Review the results table (references are truncated to 80 characters for readability).
5. Click **Download results as CSV** to export.

---

## Scoring

| Status     | Score range  |
| ---------- | ------------ |
| Confirmed  | > 0.85       |
| Suspicious | 0.60 to 0.85 |
| Not Found  | < 0.60       |

## Supported Reference Formats

**ABNT**

```
SILVA, João; OLIVEIRA, Maria. Título do artigo. Revista Brasileira, v. 10, n. 2, p. 45-60, 2021.
```

**APA**

```
Silva, J., & Oliveira, M. (2021). Article title here. Journal Name, 10(2), 45-60.
```

**Vancouver**

```
Silva J, Oliveira M. Article title here. J Abbrev. 2021;10(2):45-60.
```

---

## Limitations

- Title extraction relies on heuristic regex patterns. References with non-standard formatting (book chapters, theses, conference proceedings) may not extract cleanly and will be classified as Not Found.
- SciELO coverage is strongest for Latin American journals; CrossRef and PubMed cover a broader international corpus.
- Validation speed depends on API response times (approximately 0.5 s minimum per API call per reference). A file with 50 references takes approximately 1 to 3 minutes.
- Rate limiting: 0.5 s delay between every individual HTTP request to respect API usage policies.

---

## License

MIT
