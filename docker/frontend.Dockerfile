# The React client, built to static files and served by nginx.
#
# nginx also proxies /api to the backend, which is the point: it puts the API
# on the same origin as the page. Without that the browser refuses an https:
# page calling an http: backend, and the deployment needs a second certificate
# for the API alone.

FROM node:20-alpine AS build

WORKDIR /app

# The image never runs Electron, only builds the web assets with its toolchain.
# Left unset, `npm ci` downloads ~100 MB of Electron binary that is then
# discarded with the build stage — and fails the build outright behind a proxy.
ENV ELECTRON_SKIP_BINARY_DOWNLOAD=1

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

# Empty means same-origin, which is what the nginx proxy below provides.
# Override only to point the bundle at a backend on another host.
ARG VITE_SERVER_URL=""
ENV VITE_SERVER_URL=$VITE_SERVER_URL

# `prebuild` copies pdf.js fonts and cmaps into public/ — see
# scripts/copy-pdfjs-assets.mjs. Without them a document with non-embedded
# fonts renders as blank pages.
RUN npm run build


FROM nginx:1.27-alpine

COPY --from=build /app/dist /usr/share/nginx/html
COPY docker/nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
