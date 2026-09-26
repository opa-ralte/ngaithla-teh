# LaTeX project report

This directory contains the version-controlled report source for Ngaithla teh.

## Build

From the repository root:

```bash
cd report
pdflatex -interaction=nonstopmode report.tex
pdflatex -interaction=nonstopmode report.tex
```

The second pass resolves the table of contents and cross-reference metadata. Generated `.aux`, `.log`, `.out`, and `.toc` files are build artifacts and should not be committed. The report includes the version-controlled screenshots in `docs/` and draws the architecture and database diagrams in TikZ.

## Adding screenshots

The current report uses `docs/homepage-with-songs.png`, `docs/registration-page.png`, `docs/upload-form.png`, and `docs/rating-song.png`. Keep screenshots focused on the homepage, registration, upload, and rating workflows. Do not include passwords, database credentials, or private user data.