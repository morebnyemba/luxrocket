# syntax=docker/dockerfile:1.7
# Operator portal: static export behind nginx, which also proxies /api/portal to the platform
# API on the same origin (doc 13: no CORS, host-only cookies). Build from the repository root:
#   docker build -f apps/portal/Dockerfile .
FROM node:22-slim AS build
ENV NEXT_TELEMETRY_DISABLED=1
RUN corepack enable
WORKDIR /repo
COPY . .
RUN pnpm install --frozen-lockfile --filter @luxrocket/portal... && pnpm --filter @luxrocket/portal build

FROM nginx:1.27-alpine
ENV PORTAL_API_UPSTREAM=http://api:8000
COPY apps/portal/nginx.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /repo/apps/portal/out /usr/share/nginx/html
EXPOSE 8080
