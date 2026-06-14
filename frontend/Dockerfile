# ── Dependencies + dev server stage ──────────────────────────
# Used by docker-compose.override.yml for local development (Vite dev server
# with hot-reload). The override bind-mounts ./frontend/src over /app/src.
FROM node:20-alpine AS dev
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install
COPY . .
EXPOSE 3000
CMD ["npm", "run", "dev", "--", "--host"]

# ── Build stage ──────────────────────────────────────────────
# Produces the optimized static bundle in /app/dist (vite build, after tsc).
FROM node:20-alpine AS build
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install
COPY . .
RUN npm run build

# ── Production runtime (default) ──────────────────────────────
# nginx serves the static bundle and proxies /api and /ws to the backend,
# replacing the Vite dev proxy that only exists in development.
FROM nginx:alpine AS prod
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 3000
CMD ["nginx", "-g", "daemon off;"]
