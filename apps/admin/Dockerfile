# syntax=docker/dockerfile:1.7
# Platform console: static export behind nginx, which also proxies /api/admin to the platform
# API on the same origin (doc 12: no CORS, host-only cookies). Build from the repository root:
#   docker build -f apps/admin/Dockerfile .
FROM node:22-slim AS build
ENV NEXT_TELEMETRY_DISABLED=1
RUN corepack enable
WORKDIR /repo
COPY . .
RUN pnpm install --frozen-lockfile --filter @luxrocket/admin... && pnpm --filter @luxrocket/admin build

FROM nginx:1.27-alpine
ENV ADMIN_API_UPSTREAM=http://api:8000
COPY apps/admin/nginx.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /repo/apps/admin/out /usr/share/nginx/html
EXPOSE 8080
