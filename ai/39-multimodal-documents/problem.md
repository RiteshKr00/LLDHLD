# Design scenario 25: multimodal document pipeline

## The prompt

> "Your documents contain scanned pages, tables and charts. Make them answerable."

*There is a ceiling argument here and finding it is the test. If 30% of the salient numbers live
in tables and figures, a text-only pipeline has a **hard 70% ceiling on numeric recall** no
matter how good the model is. That single sentence justifies the entire design.*

---

## Clarifying questions to ask FIRST

1. **Are numbers inside tables and charts required in answers?** *(Usually yes, and that is
   the hard part. If the answer is no, this is a much smaller project and you should say so.)*
2. **Scanned or native PDFs?** *(Native has a text layer. Scanned means OCR, which means a
   confidence threshold and a quality floor you do not control.)*
3. **Is layout meaningful?** *(Multi-column, sidebars, footnotes. Reading order is not
   obvious, and getting it wrong turns a page into soup.)*
4. **Do answers need to be checkable?** *(If a number goes into a decision, provenance to
   page and region is not a nice-to-have.)*
5. **What is the query mix?** *(Numeric lookup, comparison, narrative summary? Decides
   whether table extraction is the priority or a refinement.)*
6. **How many documents, and how often do they change?** *(Sets whether ingest cost or query
   cost dominates — and the whole design rests on paying at ingest.)*

---

## The follow-up bank

1. Why not just send the page image to a vision model at query time?
2. A number lives in a chart with no data table. What do you do?
3. How do you index a table so a numeric question finds it?
4. OCR returns garbage on a bad scan. How do you know?
5. What is your chunk, once a page has text, a table and a figure?
6. A user asks for a number. How do they check it?
7. Two-column layout with footnotes. What breaks?
8. How do you measure whether this pipeline is any good?
9. Your table extractor is 85% accurate. Is the product viable?

Answers: `explained.md` · runnable: `solution.py` · scaling: `hld.md`
