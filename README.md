# Genga K, Portfolio

Static site. No build step, no npm, no framework. Open `index.html` and it runs; push the
folder anywhere static and it's live.

```
Portfolio/
  index.html              markup shell
  content.json            your published edits  (created by the editor)
  GENGA_K_RESUME.pdf      <- add this
  assets/
    css/main.css          design system + all styles
    js/app.js             content + rendering + interactions
    js/admin.js           the editor panel
    img/genga.jpg         <- add this (or upload via the editor)
    img/og.png            <- add this (1200x630 LinkedIn preview)
    video/                demo recordings
```

## Deploying to GitHub Pages

The repo is already initialised and committed. Create an empty repo on GitHub named
**`Genga28.github.io`**, then:

```bash
cd "C:\ZZZ Genga\LinkedIn\Portfolio"
git branch -M main
git remote add origin https://github.com/Genga28/Genga28.github.io.git
git push -u origin main
```

Git Credential Manager will pop a browser sign-in on the first push. The site goes live at
**https://genga28.github.io** within a minute, with no settings to change, because a repo named
`<username>.github.io` is served from root automatically.

Any other repo name works too; then Settings → Pages → Source → `main` / root, and it lands
at `genga28.github.io/<repo-name>`.

## The editor

Open it with **`#admin`** on the URL (`genga28.github.io/#admin`), or **Ctrl+Shift+E**, or
the small *Editor* link in the footer. Passcode is `genga`. Change `ADMIN_PASS` at the top
of [assets/js/admin.js](assets/js/admin.js).

> The passcode only hides the panel. It is client-side, so anyone can read it in the page
> source. Treat it as a convenience latch, not security. Real auth needs a backend.

**Profile**: upload a headshot by dragging it onto the drop zone, edit your name, role,
location, availability pill, the three headline lines, and the intro paragraph. Everything
updates on the page as you type.

**Writing**: add, edit, reorder and delete notes. Each takes a title, tag, date, read time,
a one-sentence summary, an optional cover image, and an HTML body. Useful tags inside the
body: `<h3>`, `<p class="pull">` for a pull quote, `<code>`, `<ul><li>`, `<img src="…">`.

**Demo videos**: one field per system. A path like `assets/video/proctor.mp4`, or a YouTube
**embed** URL (`youtube.com/embed/ID`, not `/watch?v=`). Blank means no player and the card
stays complete. Keep local clips under ~30 MB; GitHub Pages rejects files over 100 MB.

### How publishing works

There's no server, so edits save to **localStorage**, so only you, in that browser, see them.
An amber bar appears while a local draft is active. To make edits public:

1. Editor → **Publish** tab → **Download content.json** (or **Copy JSON**).
2. Save it as `content.json` next to `index.html`.
3. `git add content.json && git commit -m "Update notes" && git push`

The site loads `content.json` on every visit and layers it over the defaults in `app.js`.
Uploaded images are embedded as data URIs, so `content.json` grows with each one. For a
large photo, save the file to `assets/img/` and point the path field at it instead.

## Editing without the panel

All content lives in the `DEFAULTS` object at the top of [assets/js/app.js](assets/js/app.js):
`profile`, `telemetry`, `roles`, `cases`, `stack`, `videos`, `posts`, `links`. Roles and case
studies are only editable here, not in the panel, because they're structural.

Each role and case carries a `c:` colour from the `COLORS` map at the top of the file; that
colour drives its timeline bar, accent stripe, chips and hover glow.

## Before posting to LinkedIn

LinkedIn builds its preview card from the `og:` meta tags in `index.html`. Add
`assets/img/og.png` at 1200x630, or the post shows a bare link. If you edit the tags after
LinkedIn has already scraped the URL, clear its cache with the
[Post Inspector](https://www.linkedin.com/post-inspector/).

## Notes on the build

- **Smooth scrolling** is Lenis from jsDelivr. If that request is blocked the page falls back
  to native scrolling, nothing breaks.
- **Type** is Archivo for display, IBM Plex Sans for everything else. No monospace anywhere
  except inline `<code>`.
- **Colour**: seven accents, one per section, carried through the side rail, eyebrows,
  timeline bars and case-study stripes. Semantic green to red is reserved for the risk bands in
  the fusion widget and used nowhere else.
- **The timeline** is a Gantt, not a single track, because Yubi and Space Marvel overlap
  Jan–Jun 2025. Positions are computed from the `start`/`end` dates on each role, so the axis
  extends itself as time passes.
- **The fusion widget** is live: weights, the exponential boost above 70, and the band cuts
  are all in `initFusion()`. It's labelled illustrative on the page, so it claims nothing
  about Jobtwine's production constants.
- **Roles don't repeat the case studies.** Each role links across to the systems built there
  instead of restating them.
- `prefers-reduced-motion` stands down animation, the canvas and smooth scroll.
