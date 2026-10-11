# syntax=docker/dockerfile:1.7
# Static game build served by nginx. Build from the repository root:
#   docker build -f apps/game/Dockerfile --build-arg NEXT_PUBLIC_API_URL=... .
FROM node:22-slim AS build
ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ARG NEXT_PUBLIC_RT_URL=ws://localhost:4000/socket
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL NEXT_PUBLIC_RT_URL=$NEXT_PUBLIC_RT_URL NEXT_TELEMETRY_DISABLED=1
RUN corepack enable
WORKDIR /repo
COPY . .
RUN pnpm install --frozen-lockfile --filter @luxrocket/game... && pnpm --filter @luxrocket/game build

FROM nginx:1.27-alpine
COPY apps/game/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /repo/apps/game/out /usr/share/nginx/html
EXPOSE 8080
