# Chart Screenshot OCR Fallback

When `vision_analyze` repeatedly returns "no image visible" but the file is on disk and valid, fall back to OCR to extract structural data from a TradingView-style chart screenshot.

This recipe is grounded in a real failure on AIGENSYNUSDT 15m chart (1280x775 JPEG): vision tool returned "no image" 3 times in a row even though `file` and `stat` confirmed a valid 82KB JPEG. OCR with strategic crops successfully extracted ticker, timeframe, OHLC, EMA values, and RSI reading.

## Pre-flight checks

```bash
# Confirm file is real and an image
ls -la <path>
file <path>      # must show JPEG/PNG image data, not text/HTML
stat <path>      # confirms size and timestamps

# Install Pillow if needed (pip on this host requires --break-system-packages)
python3 -c "from PIL import Image" || pip install Pillow --break-system-packages --quiet
```

## Crop strategy

A TradingView chart has 3 high-value text regions that OCR well when isolated; full-image OCR usually returns junk because the chart body (candles, axes) confuses tesseract.

```python
from PIL import Image, ImageEnhance, ImageOps

img = Image.open('<path>')
W, H = img.size

# 1. Header strip — ticker, exchange, TF, last OHLC, % change, indicator legend
header = img.crop((0, 0, W, 80))
header = header.resize((header.size[0]*3, header.size[1]*3), Image.LANCZOS)
header.save('/tmp/header.png')

# 2. Right price scale — visible price levels and EMA value labels
right = img.crop((W-150, 60, W, H-100))
right = right.resize((right.size[0]*3, right.size[1]*3), Image.LANCZOS)
right.save('/tmp/right_scale.png')

# 3. Bottom indicator panel — RSI/MACD numeric readout
bottom = img.crop((0, H-180, W, H))
bottom = bottom.resize((bottom.size[0]*2, bottom.size[1]*2), Image.LANCZOS)
bottom.save('/tmp/bottom.png')
```

Optional enhancement when default crops still fail:

```python
gray = img.convert('L')
gray2x = gray.resize((gray.size[0]*2, gray.size[1]*2), Image.LANCZOS)
ImageEnhance.Contrast(gray2x).enhance(2.0).save('/tmp/chart_enhanced.png')
ImageOps.invert(gray2x).save('/tmp/chart_inverted.png')   # for dark-theme charts
```

## OCR per crop

```bash
# PSM 6 = single uniform block of text — works well for header and scale strips
tesseract /tmp/header.png      stdout -l eng --psm 6
tesseract /tmp/right_scale.png stdout -l eng --psm 6
tesseract /tmp/bottom.png      stdout -l eng --psm 6
```

If output is still garbled, try `--psm 11` (sparse text) on the inverted version.

## Cross-check with live data

OCR is noisy. After extracting numbers, fetch live Binance data and validate:

- If header says "AIGENSYN ... 15-Binance C0.04146" → query `fapi.binance.com/fapi/v1/klines?symbol=AIGENSYNUSDT&interval=15m&limit=3` and confirm a recent candle close near 0.04146.
- If scale shows "EMA value 0.04241" → compute EMA20 from live klines and confirm match within tolerance.

This grounds the analysis in fresh data and catches OCR misreads (e.g. `0` vs `O`, `,` vs `.`).

## What OCR can and cannot read

Can read:
- Ticker, exchange, contract type (PERPETUAL CONTRACT)
- Timeframe (15, 30, 1H, 4H, 1D — usually after a dash)
- Last candle OHLC + % change in header
- Indicator legend (EMA 20, EMA 50, SMA 100, EMA 200, MA Ribbon)
- RSI numeric readout ("RSI 14 close 45.07")
- Visible price levels on the right scale

Cannot read:
- Candle patterns (engulfing, pin bar, hammer, doji shapes)
- User-drawn trendlines, S/R lines, supply/demand zones, fib levels
- Chart formations (head & shoulders, triangle, wedge, flag)
- Color information that conveys meaning (green/red candles via OCR are inferred by position only)

When OCR is the path used, explicitly tell the user what was extracted via OCR vs what cannot be extracted, and ask them to type out any drawings/zones manually. Do not pretend to "see" candle shapes from OCR output.

## When NOT to use OCR fallback

- Vision tool worked once in this session. Try vision again first; OCR is fallback only.
- Chart is not a typical TradingView layout (mobile screenshot, candle-only no header). OCR will return little useful data; ask user to share the data directly.
- File is HEIC/WebP/uncommon format. Convert to JPEG/PNG first or ask user to re-export.
