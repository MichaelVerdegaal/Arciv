# Plan

Four changes, tackled in order. Each is independently committable.


## 1. Address link cleaning issues

### Bookmarks introduce duplicates
```shell
08:42:27 | INFO     | clotho.scrape.scraper:_fetch_one_async:760 - Archived https://facebook.github.io/prophet/docs/seasonality,_holiday_effects,_and_regressors.html (1982 words)
08:42:28 | INFO     | clotho.scrape.scraper:_fetch_one_async:760 - Archived https://facebook.github.io/prophet/docs/seasonality,_holiday_effects,_and_regressors.html#additional-regressors (1982 words)
```

### Medium block
```shell
Rejected https://medium.com/@cuongduong_35162/facebook-prophet-in-2023-and-beyond-c5086151c138: block page (title: 'Just a moment...')
```

### Cookie block?
```shell
 Rejected https://portal.gigaom.com/report/delivering-on-the-vision-of-mlops#Summary: too short (26 words)
 ```

 This is a long page

### Researchgate too short
```shell
 Rejected https://www.researchgate.net/publication/360644441_The_Impact_of_Artificial_Intelligence_on_Employment: too short (24 words)
 ```

 This is rejected because the summary on the page is short, but there's a PDF URL to download easily

## 2. Tiny Astro frontend

A minimal Astro site under `frontend/` that reads `data/clotho.db` at build time (via
`better-sqlite3`) and renders the archive: one searchable, filterable list of archived pages (title,
domain, word count, link to the original URL). No backend server — static output generated from the
database.
