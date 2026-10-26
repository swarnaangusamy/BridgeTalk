# ============================================================================
# BridgeTalk frontend — Vite build served by nginx
#
#   docker build -f frontend/Dockerfile -t bridgetalk-frontend ./frontend
#
# Two stages: node builds, nginx serves. The runtime image carries no node_modules
# and no toolchain — about 50 MB instead of 500 MB.
# ============================================================================
FROM node:20-alpine AS build

WORKDIR /app

# Lockfile first, so npm ci is cached independently of source changes.
COPY package.json package-lock.json ./
RUN npm ci

COPY . .

# Vite inlines VITE_* variables AT BUILD TIME — they are not read from the
# environment when the container starts. So the API URL, the WebSocket URL and
# the ICE servers must be passed as build arguments. Getting this wrong
# produces a frontend that silently talks to localhost in production.
ARG VITE_API_BASE_URL=http://localhost:8000
ARG VITE_WS_BASE_URL=ws://localhost:8000
ARG VITE_STUN_URLS=stun:stun.l.google.com:19302,stun:stun1.l.google.com:19302
ARG VITE_TURN_URLS=
ARG VITE_TURN_USERNAME=
ARG VITE_TURN_CREDENTIAL=
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL \
    VITE_WS_BASE_URL=$VITE_WS_BASE_URL \
    VITE_STUN_URLS=$VITE_STUN_URLS \
    VITE_TURN_URLS=$VITE_TURN_URLS \
    VITE_TURN_USERNAME=$VITE_TURN_USERNAME \
    VITE_TURN_CREDENTIAL=$VITE_TURN_CREDENTIAL

RUN npm run build

# ---------------------------------------------------------------------------
FROM nginx:1.27-alpine AS runtime

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
    CMD wget -qO- http://localhost/ >/dev/null || exit 1
