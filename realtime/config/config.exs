# This file is responsible for configuring your application
# and its dependencies with the aid of the Config module.
#
# This configuration file is loaded before any dependency and
# is restricted to this project.

# General application configuration
import Config

config :lux_rt,
  ecto_repos: [LuxRt.Repo],
  generators: [timestamp_type: :utc_datetime, binary_id: true]

# Phoenix owns the `rt` schema (doc 04 §1). The schema is created on connect so migrations,
# including the schema_migrations table, can live inside it.
config :lux_rt, LuxRt.Repo,
  migration_default_prefix: "rt",
  after_connect:
    {Postgrex, :query!,
     [
       "DO $$ BEGIN CREATE SCHEMA IF NOT EXISTS rt; EXCEPTION WHEN insufficient_privilege THEN NULL; END $$",
       []
     ]}

# Game rules for the default stream (doc 07 §1). Must match the Django RULESET.
config :lux_rt, :ruleset,
  house_edge_bp: 300,
  max_multiplier_x10000: 100_000_000,
  curve_lambda_per_ms: "0.00006",
  panels: 2

# Round timing (ms) and coordinator parameters (doc 06 §3-§5).
config :lux_rt, :timing,
  betting_window_ms: 7_000,
  close_grace_ms: 1_000,
  crash_grace_ms: 50,
  cooldown_ms: 2_000,
  tick_ms: 250,
  journal_flush_ms: 5,
  lease_ttl_ms: 6_000,
  lease_renew_ms: 2_000

config :lux_rt, :streams, ["global"]
config :lux_rt, :game_origins, ["http://localhost:3000"]

# Django internal API (doc 06 §8). Overridden from the environment in runtime.exs.
config :lux_rt, :platform,
  base_url: "http://localhost:8000",
  service_token: "dev-internal-token",
  bet_timeout_ms: 900

# Seed-chain settings. The KEK comes from a secret store (SEED_KEK_B64); dev and test derive
# a throwaway key instead (see :dev_derived_kek below), production refuses to start without it.
config :lux_rt, :fairness,
  chain_length: 100_000,
  checkpoint_every: 1_000,
  seed_kek_b64: nil,
  # Dev convenience: create a local-random ACTIVE chain when a stream has none. Production
  # turns this off (runtime.exs) and plays only ceremony-committed, drand-salted chains.
  auto_chain: true

# Public randomness beacon for chain salts (doc 07 §6.1): drand "quicknet" (League of Entropy).
# A chain's salt is the randomness of a round fixed at commitment, at least min_delay_s later.
config :lux_rt, :drand,
  chain_hash: "52db9ba70e0cc0f6eaf7803dd07447a1f5477735fd3f661792ba94600c84e971",
  genesis_time: 1_692_803_367,
  period_s: 3,
  min_delay_s: 86_400

# Configures the endpoint
config :lux_rt, LuxRtWeb.Endpoint,
  url: [host: "localhost"],
  adapter: Bandit.PhoenixAdapter,
  render_errors: [
    formats: [json: LuxRtWeb.ErrorJSON],
    layout: false
  ],
  pubsub_server: LuxRt.PubSub,
  live_view: [signing_salt: "91nQFS9q"]

# Configures Elixir's Logger
config :logger, :console,
  format: "$time $metadata[$level] $message\n",
  metadata: [:request_id]

# Use Jason for JSON parsing in Phoenix
config :phoenix, :json_library, Jason

# Import environment specific config. This must remain at the bottom
# of this file so it overrides the configuration defined above.
import_config "#{config_env()}.exs"
