# UI Vision Fallback via Subagent OCR

When the host's `vision_analyze` pipeline keeps returning "I don't see an
image" across `file://`, public HTTPS, and `browser_vision` paths, the
attachment is being dropped before reaching the model. Retrying inline is
wasted. This file documents the working fallback: hand the verification job
to a `delegate_task` subagent that combines OCR (`tesseract`) with pixel
sampling, and have it return a structural description in text.

## When to use this

- UI verification after a non-trivial layout change the user can't
  immediately eyeball ("is the dashboard symmetric now?", "did the percent
  card show up correctly?").
- When the user says "kenapa kamu gak bisa lihat gambar? coba alternatif"
  and you've already tried 3+ image-hosting paths inline.

Do **not** use this for chart analysis — for trade screenshots the inline
`vision_analyze` + OCR-on-chart-strips recipe in
`references/chart-ocr-fallback.md` keeps the post-mortem in main context.

## Setup: make the image reachable

The subagent runs in a clean sandbox; it can't read `/root/.hermes/cache`
directly. Expose the screenshot through the existing public tunnel:

```bash
mkdir -p /root/calendar_app/public/img
cp <screenshot> /root/calendar_app/public/img/<name>.png
# verify
curl -sS --max-time 15 -o /dev/null -w "code=%{http_code} size=%{size_download}\n" \
  "https://<your-tunnel>.trycloudflare.com/img/<name>.png"
```

Find the active tunnel URL with:

```bash
grep -oE "https://[a-z0-9.-]+trycloudflare\.com" /var/log/calendar-tunnel.log | tail -1
```

## Subagent prompt skeleton

```python
delegate_task(
    context="...what the dashboard is, what the user wants verified, and any constraints (Indonesian language, etc)...",
    goal=(
        "Fetch <public URL> and analyze the redesigned dashboard. "
        "Verify: (1) all stat cards uniform height with 3-line layout, "
        "(2) sub-text values present and meaningful, "
        "(3) day cells show date+dots top, WL center, R bold colored, % muted, "
        "(4) tabular-nums alignment, (5) symmetric layout no truncation, dots visible. "
        "Use vision_analyze first; if it returns 'I don't see image', fall back to "
        "curl + tesseract OCR per region (top stats row, calendar grid, individual cells), "
        "use imagemagick crop + Pillow LANCZOS upscale to verify. "
        "Return concrete confirmation of what works and what still needs fixing. "
        "Respond in Indonesian."
    ),
    toolsets=["vision", "web", "terminal"],
)
```

## What the subagent should do (canonical recipe)

1. Download once: `curl -sS -o /tmp/dash.png <url>`. Confirm size and
   `file /tmp/dash.png` reports valid PNG/JPEG.
2. Try `vision_analyze` directly on the URL — sometimes a different provider
   variant inside the subagent works.
3. If vision returns the same "no image" reply, fall back to OCR + pixel:
   - `pip install Pillow --break-system-packages --quiet` if not present.
   - Crop per region with PIL — full-image OCR on a UI screenshot returns
     mostly noise. Recommended crops for the trading calendar dashboard:
     - **Header strip** (top ~80px): title, live badge, last update, total.
     - **Stat row** (next ~110px): 6 cards horizontally, crop per card.
     - **Source explainer** (next ~120px): three description cards.
     - **Filter+nav row** (~50px): month label, prev/next, filter pills.
     - **Calendar weekday header** (~30px): Sen..Min.
     - **Calendar grid rows** (each ~150–180px tall, 7 cells).
     - **Per-cell** (one cell ~150x150px): date+dots top, WL/R/% center.
   - Upscale 2–3x with `Image.LANCZOS`, convert to grayscale, bump contrast,
     then `tesseract <crop>.png stdout -l eng --psm 6`.
4. Pixel sampling for color verification (HSV space):
   - Read the cell's top-right corner where dots live; count saturated pixels
     by hue. Hue ~119 = green source dot, ~24 = amber, ~242 = red/violet
     loss.
   - Read the value text band of each stat card; the dominant non-bg hue
     tells you whether the colour-by-sign rendered (emerald-400 ~146, rose-400 ~340).
5. Return a structured findings table in the user's language. Include:
   - What each region rendered (label + value + sub-text).
   - Card heights and column boundaries (in pixels) to prove symmetry.
   - Per-cell content: date, dots, WL, R, %.
   - Issues with concrete fix suggestions.

## Performance budget

- Typical run: 100–500 seconds, 15–40 tool calls.
- Token cost stays in the subagent; main context only sees the final summary.
- If the subagent burns >40 tool calls without producing a structured
  finding, abort and ask the user to describe specific issues directly —
  that's faster than a fourth try.

## Why this works when inline vision fails

The host's vision pipeline drops the attachment before the model sees it.
A subagent spawns a separate model invocation with its own toolset; when
both inline `vision_analyze` AND `browser_vision` fail in the parent, the
subagent's deterministic fallback (OCR + pixel) doesn't depend on the
attachment-passing path at all. It treats the image as an HTTP resource
the same way curl would.

## Anti-patterns

- **Don't loop inline.** If three vision calls return "no image", stop
  retrying with new hosts. The provider isn't getting the attachment;
  re-hosting won't fix that.
- **Don't ask the subagent to do trading analysis from the screenshot.**
  Use it only for layout/structural verification. Trade decisions need
  Binance API data, not OCR'd numbers.
- **Don't skip the public-URL step.** Subagents run sandboxed and can't
  read your `/root/.hermes/cache/screenshots/...` directly. Always copy
  to `/root/calendar_app/public/img/` first.
