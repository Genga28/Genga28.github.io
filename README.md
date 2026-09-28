# Genga K — Portfolio

A single self-contained page. No build step, no npm, no framework. Open `index.html` in a
browser and it runs; drop the folder on any static host and it's live.

```
Portfolio/
  index.html                 the whole site
  README.md                  this file
  GENGA_K_RESUME.pdf         <- add this
  assets/
    genga.jpg                <- add this (headshot, portrait crop, ~1000x1250)
    og.png                   <- add this (1200x630 LinkedIn preview card)
    video/                   <- demo recordings go here
    img/
```

## The three things to add

Everything else is already written. Open `index.html`, find the `CONFIG` block near the top
of the `<script>` (around line 900), and fill in what you have.

**1. Headshot** — save it as `assets/genga.jpg`. Until then the About section shows a "GK"
monogram plate, which looks deliberate rather than broken, so there's no rush.

**2. Résumé** — drop `GENGA_K_RESUME.pdf` next to `index.html`. The Résumé button checks
whether the file exists and shows an email prompt instead of a 404 if it doesn't.

**3. Demo videos** — one line each in `CONFIG.videos`. Both forms work:

```js
videos: {
  proctoring: "assets/video/proctor.mp4",              // local file
  rag:        "https://www.youtube.com/embed/XXXXXXX", // YouTube EMBED url, not /watch
  voice:      "",                                      // empty = no player, card still complete
}
```

Valid ids: `proctoring`, `rag`, `voice`, `ocr`, `shelf`, `telecaller`, `desktop`.
A 16:9 player appears inside that case-study card. Keep clips under ~30 MB — GitHub Pages
rejects files over 100 MB, and a big autoplay-less MP4 still costs the visitor bandwidth.
For anything longer than about 90 seconds, use the YouTube embed form instead.

## Adding a blog post

Add an object to the `POSTS` array. The card and the reader overlay build themselves.

```js
{
  tag:"Retrieval", date:"2026", read:"5 min",
  title:"Your title",
  dek:"One sentence that makes someone click.",
  body:`<p>HTML. <code>code</code>, <strong>bold</strong>,
        and <p class="pull">for a pull quote.</p>`
}
```

The three posts shipped in there are drafts written from your résumé facts — read them and
make them yours before sharing the link.

## Deploying

**GitHub Pages** — free, and the URL sits under your own name.

```bash
cd "C:\ZZZ Genga\LinkedIn\Portfolio"
git init
git add .
git commit -m "Portfolio"
git branch -M main
git remote add origin https://github.com/Genga28/Genga28.github.io.git
git push -u origin main
```

Naming the repo `Genga28.github.io` publishes it at `https://genga28.github.io` — no
settings to change. Any other repo name works too; then go to Settings → Pages → Source →
`main` / root, and it lands at `genga28.github.io/<repo-name>`.

**Netlify / Vercel** — drag the folder onto their dashboard drop zone. Done in about ten
seconds, and you get a custom subdomain.

## Before posting the link to LinkedIn

LinkedIn reads the `og:` meta tags at the top of `index.html` to build the preview card.
Add `assets/og.png` at 1200x630 — without it the post shows a bare link. If you edit the
tags after LinkedIn has already scraped the URL, clear its cache with the
[Post Inspector](https://www.linkedin.com/post-inspector/).

## Notes on how it's built

- **Smooth scrolling** comes from Lenis, loaded from jsDelivr. If that request is ever
  blocked the page falls back to native scrolling — nothing breaks.
- **Fonts** are Archivo (display), IBM Plex Sans (body), IBM Plex Mono (data and labels),
  from Google Fonts, each with a real fallback stack.
- **The hero canvas** draws four signal traces converging into one — the proctoring engine's
  fusion model, as ambient motion.
- **The fusion widget** in the first case study is live: the weights, the exponential boost
  above 70, and the risk bands are all in the `fusion instrument` block. It's labelled as
  illustrative on the page, so it makes no claim about Jobtwine's production constants.
- **`prefers-reduced-motion`** is respected throughout — animation, canvas, and smooth
  scroll all stand down.
- Everything is one file on purpose. It's easier to host, easier to hand to someone, and
  there's no toolchain to rot in six months.
