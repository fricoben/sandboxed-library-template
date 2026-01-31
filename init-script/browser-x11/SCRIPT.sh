#!/usr/bin/env bash
# Description: X11, i3 window manager, Chromium, and Playwright browser setup

export PLAYWRIGHT_BROWSERS_PATH="${PLAYWRIGHT_BROWSERS_PATH:-/root/.cache/ms-playwright}"

# Install X11, desktop, and browser packages
retry apt-get install -y --no-install-recommends \
  xauth dbus-x11 xvfb i3 scrot xdotool x11-utils \
  libgl1 libglu1-mesa libgl1-mesa-dri libxi6 libxrender1 libxtst6 libxext6 \
  libnss3 libnspr4 libasound2t64 libpulse0 libxrandr2 libxinerama1 libxcursor1 \
  libxcomposite1 libxdamage1 libxfixes3 libxkbcommon0 libdrm2 libgbm1 libx11-xcb1 libxshmfence1 \
  libatk1.0-0 libatk-bridge2.0-0 libatspi2.0-0 libgtk-3-0 libcups2 libdbus-1-3 libpango-1.0-0 libcairo2 \
  mesa-utils fonts-dejavu-core fonts-liberation fonts-noto \
  imagemagick at-spi2-core python3-pil python3-gi python3-gi-cairo gir1.2-atspi-2.0 \
  tesseract-ocr

# Install Chromium
retry apt-get install -y chromium chromium-sandbox || retry apt-get install -y chromium-browser || true

# Install Playwright browsers
if command -v bun >/dev/null 2>&1; then
  bunx playwright install --with-deps chromium || true
fi
if command -v node >/dev/null 2>&1; then
  npx -y @playwright/test@latest install --with-deps chromium || true
fi

# Ensure Chromium is available as a fallback via Playwright
if ! command -v chromium >/dev/null 2>&1 && ! command -v chromium-browser >/dev/null 2>&1; then
  if [ -d "$PLAYWRIGHT_BROWSERS_PATH" ]; then
    PW_CHROME="$(find "$PLAYWRIGHT_BROWSERS_PATH" -type f -name chrome -path "*chromium*" | head -n 1 || true)"
    if [ -n "$PW_CHROME" ] && [ -f "$PW_CHROME" ]; then
      ln -sf "$PW_CHROME" /usr/local/bin/chromium
    fi
  fi
fi

# Create i3 configuration
mkdir -p /root/.config/i3
cat >/root/.config/i3/config <<'I3CFG'
set $mod Mod4
font pango:DejaVu Sans Mono 10

default_border pixel 3
default_floating_border pixel 3

client.focused          #4c7899 #285577 #ffffff #2e9ef4   #ff5500
client.focused_inactive #333333 #5f676a #ffffff #484e50   #333333
client.unfocused        #333333 #222222 #888888 #292d2e   #333333
client.urgent           #2f343a #900000 #ffffff #900000   #900000
client.placeholder      #000000 #0c0c0c #ffffff #000000   #0c0c0c

bar {
    status_command i3status 2>/dev/null || echo "i3"
    position top
    colors {
        background #222222
        statusline #dddddd
    }
}
I3CFG
