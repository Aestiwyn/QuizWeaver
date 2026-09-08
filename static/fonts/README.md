# OpenDyslexic Font

This directory is intended for locally-hosted OpenDyslexic font files.

OpenDyslexic is a free, open-source typeface designed to increase readability
for readers with dyslexia. It is licensed under the SIL Open Font License.

## How to add local font files

1. Download OpenDyslexic from https://opendyslexic.org/
2. Place the .woff2 and .woff files in this directory:
   - OpenDyslexic-Regular.woff2
   - OpenDyslexic-Regular.woff
   - OpenDyslexic-Bold.woff2
   - OpenDyslexic-Bold.woff

The CSS in `static/css/accessibility.css` will automatically use local files
if present, falling back to the CDN if not found.

## License

OpenDyslexic is licensed under the SIL Open Font License, Version 1.1.
See https://opendyslexic.org/ for details.

## Chinese PDF font

`NotoSansSC-VF.ttf` is Noto Sans SC, a Simplified Chinese variable font from
the Noto project. It is distributed under the SIL Open Font License, Version
1.1, and is bundled for PDF export only. ReportLab embeds the used font subset
in each generated PDF, so teacher and student PDFs do not depend on the
recipient having a Chinese font installed.

Word exports specify `Noto Sans SC` for the East Asian font property and use
Microsoft YaHei as the document font. Word files are not font-embedded, so
the exact appearance may vary on devices without either font; Chinese text
remains editable and a compatible local fallback is selected by Word.
