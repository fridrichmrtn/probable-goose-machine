---
title: Gander
emoji: 🪿
colorFrom: gray
colorTo: yellow
sdk: gradio
sdk_version: "6.14.0"
app_file: app.py
python_version: "3.11"
pinned: false
---

<p align="center">
  <img src="assets/gander.svg" width="120" alt="Gander logo: a goose with a monocle"/>
</p>

<p align="center"><em>a closer look at any CV</em></p>

Bootstrap stub — full README lands in T23. See `tasks/PLAN.md` and `tasks/T23_readme.md`.

## Ingest Privacy Note

By default, Gander uses LLM-based extraction. PDF pages are rendered to images
and DOCX source text may be sent to MiniMax for transcription/normalization.
Uploaded files are not retained by Gander after processing.

Set `GANDER_INGEST_MODE=text` to use deterministic local PDF/DOCX text
extraction only.
