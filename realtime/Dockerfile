# syntax=docker/dockerfile:1.7
ARG ELIXIR_IMAGE=elixir:1.18.4-otp-27-slim
ARG RUNNER_IMAGE=debian:bookworm-slim

FROM ${ELIXIR_IMAGE} AS build
ENV MIX_ENV=prod
RUN apt-get update && apt-get install -y --no-install-recommends build-essential git ca-certificates \
  && rm -rf /var/lib/apt/lists/*
WORKDIR /app
RUN mix local.hex --force && mix local.rebar --force
COPY mix.exs mix.lock ./
RUN mix deps.get --only prod && mix deps.compile
COPY config config
COPY lib lib
COPY priv priv
RUN mix compile && mix release

FROM ${RUNNER_IMAGE} AS runtime
RUN apt-get update && apt-get install -y --no-install-recommends libstdc++6 openssl libncurses6 locales ca-certificates \
  && rm -rf /var/lib/apt/lists/* && sed -i '/en_US.UTF-8/s/^# //g' /etc/locale.gen && locale-gen
ENV LANG=en_US.UTF-8 MIX_ENV=prod
RUN useradd --system --uid 10001 app
WORKDIR /app
COPY --from=build --chown=app /app/_build/prod/rel/lux_rt ./
USER app
EXPOSE 4000
CMD ["/app/bin/lux_rt", "start"]
